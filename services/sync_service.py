# services/sync_service.py
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Dict, Iterable, List, Optional, Tuple

from flask import current_app
from requests import Session
from requests.auth import HTTPDigestAuth, HTTPBasicAuth
from requests.adapters import HTTPAdapter
from requests.exceptions import RequestException, ConnectTimeout, ReadTimeout
from urllib3.util.retry import Retry
from dateutil import parser as dtparser
from sqlalchemy import func

from models import db
from models.operator import Operator
from models.attendance import AttendanceEvent
from blueprints.attendance.db_helpers import insert_events_from_device

log = logging.getLogger(__name__)

# ------------------------- config helpers -------------------------

def _cfg(key: str, default=None):
    return current_app.config.get(key, default)

def _base_url() -> str:
    scheme = _cfg("DEVICE_SCHEME", "http")
    host   = _cfg("DEVICE_IP", "127.0.0.1")
    port   = _cfg("DEVICE_PORT", None)
    if port:
        return f"{scheme}://{host}:{port}"
    return f"{scheme}://{host}"

EMP_SEARCH = "/ISAPI/AccessControl/UserInfo/Search?format=json"
ACS_EVENT  = "/ISAPI/AccessControl/AcsEvent?format=json"

def _timeouts() -> tuple[float, float]:
    # (connect, read)
    return (
        float(_cfg("DEVICE_CONNECT_TIMEOUT", 5.0)),
        float(_cfg("DEVICE_READ_TIMEOUT", 30.0)),
    )

# ------------------------- http session -------------------------

def _session() -> Session:
    s = Session()
    user = _cfg("USERNAME", "admin")
    pw   = _cfg("PASSWORD", "12345")
    auth_mode = str(_cfg("DEVICE_HTTP_AUTH", "auto")).lower()

    if auth_mode == "basic":
        s.auth = HTTPBasicAuth(user, pw)
    else:
        # default to digest (works for digest and for auto-first-try)
        s.auth = HTTPDigestAuth(user, pw)

    s.verify = False  # self-signed certs are common on these devices
    s.headers.update({"Content-Type": "application/json", "Accept": "application/json"})

    retry = Retry(
        total=2, connect=2, read=2,
        backoff_factor=0.4,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET", "POST"])
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=8, pool_maxsize=8)
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    return s

# ------------------------- diagnostics -------------------------

def probe_device() -> dict:
    """
    Lightweight probe to help you see what is reachable without failing the sync.
    Returns info dict; safe to call from a temporary admin endpoint or shell.
    """
    base = _base_url()
    connect_to, read_from = _timeouts()
    info = {
        "base_url": base,
        "employees_endpoint": base + EMP_SEARCH,
        "events_endpoint": base + ACS_EVENT,
        "ok": False,
        "employees_ok": False,
        "events_ok": False,
        "error": None,
    }
    try:
        with _session() as s:
            # try employees with tiny page
            payload_emp = {"UserInfoSearchCond": {"searchID": "ping", "maxResults": 1, "searchResultPosition": 0}}
            r1 = s.post(base + EMP_SEARCH, json=payload_emp, timeout=(connect_to, min(read_from, 10)))
            info["employees_ok"] = r1.ok
            # try events with a 1-minute window today
            today = date.today()
            tz = _cfg("DEVICE_TZ_OFFSET", "")
            payload_ev = {
                "AcsEventCond": {
                    "searchID": "ping",
                    "searchResultPosition": 0,
                    "maxResults": 1,
                    "major": 5, "minor": 75,
                    "startTime": f"{today.isoformat()}T00:00:00{tz}",
                    "endTime":   f"{today.isoformat()}T00:01:00{tz}",
                    "timeReverseOrder": False,
                    "picEnable": False
                }
            }
            r2 = s.post(base + ACS_EVENT, json=payload_ev, timeout=(connect_to, min(read_from, 10)))
            info["events_ok"] = r2.ok
            info["ok"] = info["employees_ok"] and info["events_ok"]
    except Exception as e:
        info["error"] = str(e)
    return info

# ------------------------- employees -------------------------

def _fallback_employee_map_from_db() -> Dict[str, Dict]:
    mapping: Dict[str, Dict] = {}
    for op in Operator.query.all():
        if not op.emp_no:
            continue
        mapping[op.emp_no] = {
            "name": op.full_name or op.username,
            "room_number": op.room_number,
        }
    return mapping

def fetch_employees_from_device() -> Dict[str, Dict]:
    url = _base_url() + EMP_SEARCH
    search_position = 0
    max_results = 50
    mapping: Dict[str, Dict] = {}

    try:
        with _session() as s:
            while True:
                payload = {
                    "UserInfoSearchCond": {
                        "searchID": "1",
                        "maxResults": max_results,
                        "searchResultPosition": search_position
                    }
                }
                data = _post_json_with_auth_fallback(s, url, payload, _timeouts())
                users = (data.get("UserInfoSearch", {}) or {}).get("UserInfo", []) or []
                if not users:
                    break
                for u in users:
                    emp_no = u.get("employeeNo") or u.get("employeeNoString")
                    if not emp_no:
                        continue
                    name = u.get("name")
                    room = u.get("roomNumber")
                    try:
                        room = int(room) if room not in (None, "",) else None
                    except Exception:
                        room = None
                    mapping[emp_no] = {"name": name, "room_number": room}

                status = (data.get("UserInfoSearch", {}) or {}).get("responseStatusStrg", "")
                if str(status).upper() != "MORE":
                    break
                search_position += len(users)
    except Exception as e:
        log.warning("Failed to fetch employees: %s", e)
        return _fallback_employee_map_from_db()

    # fill missing from DB if needed
    if mapping:
        for emp_no, row in mapping.items():
            if (row.get("name") and row.get("room_number") is not None):
                continue
            op = Operator.query.filter_by(emp_no=emp_no).first()
            if op:
                row.setdefault("name", op.full_name or op.username)
                if row.get("room_number") is None:
                    row["room_number"] = op.room_number
    return mapping

def upsert_operators_from_map(emp_map: Dict[str, Dict]) -> int:
    """
    Ensure our Operator table mirrors device users enough for fallback enrichment.
    Creates missing Operators (username=emp_no), updates full_name / room_number.
    Returns number of upserts.
    """
    if not emp_map:
        return 0
    changed = 0
    existing = {op.emp_no: op for op in Operator.query.all() if op.emp_no}
    for emp_no, data in emp_map.items():
        name = (data.get("name") or "").strip() or None
        room = data.get("room_number")
        op = existing.get(emp_no)
        if not op:
            op = Operator(username=emp_no.lower(), full_name=name, emp_no=emp_no, room_number=room, active=True)
            # set a dummy password hash for completeness; they won’t log in
            op.set_password(emp_no.lower())
            db.session.add(op)
            changed += 1
        else:
            upd = False
            if name and op.full_name != name:
                op.full_name = name; upd = True
            if op.room_number != room:
                op.room_number = room; upd = True
            if upd:
                changed += 1
    if changed:
        db.session.commit()
    return changed

# ------------------------- events -------------------------

def _parse_device_time(s: str) -> datetime:
    """
    Convert device time string to naive UTC datetime (your app stores naive UTC).
    """
    dt = dtparser.isoparse(s)
    if dt.tzinfo:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt

def _label_to_event_type(label: str) -> Optional[str]:
    if not label:
        return None
    l = label.strip().lower()
    if "check in" in l or l == "in":
        return "check_in"
    if "check out" in l or l == "out":
        return "check_out"
    # common Hik labels
    if "access granted" in l or "valid" in l:
        # treat as "check_in" if you don’t have in/out per door
        return "check_in"
    return None

def fetch_events(start_date: date, end_date: date, employee_map: Dict[str, Dict]) -> Iterable[Dict]:
    url = _base_url() + ACS_EVENT
    search_id = str(uuid.uuid4())
    search_position = 0
    max_results = 1000
    connect_to, read_from = _timeouts()

    tz = _cfg("DEVICE_TZ_OFFSET", None)
    # Extend the end boundary to the next morning 06:00 + NIGHT_END_GRACE_MINUTES to capture
    # night-shift checkouts after midnight when syncing per-day or per-week.
    grace_min = int(_cfg("NIGHT_END_GRACE_MINUTES", 15))
    end_next_day = end_date + timedelta(days=1)
    start_iso = f"{start_date.isoformat()}T00:00:00{tz or ''}"
    end_iso   = f"{end_next_day.isoformat()}T06:{grace_min:02d}:00{tz or ''}"

    with _session() as s:
        while True:
            payload = {
                "AcsEventCond": {
                    "searchID": search_id,
                    "searchResultPosition": search_position,
                    "maxResults": max_results,
                    "major": 5,
                    "minor": 75,
                    "startTime": start_iso,
                    "endTime": end_iso,
                    "timeReverseOrder": False,
                    "picEnable": False
                }
            }
            data = _post_json_with_auth_fallback(s, url, payload, (connect_to, read_from))
            records = (data.get("AcsEvent", {}) or {}).get("InfoList", []) or []
            if not records:
                break

            for r in records:
                emp_no = r.get("employeeNoString") or r.get("employeeNo")
                if not emp_no:
                    continue
                event_type = _label_to_event_type(r.get("label") or "")
                if not event_type:
                    continue
                ts = _parse_device_time(r["time"])
                info = employee_map.get(emp_no) or {}
                yield {
                    "emp_no": emp_no,
                    "emp_name": info.get("name"),
                    "timestamp": ts,
                    "event_type": event_type,
                    "room_number": info.get("room_number"),
                    "source": "hikvision",
                    "source_uid": r.get("serialNo") or r.get("index") or None
                }

            status = (data.get("AcsEvent", {}) or {}).get("responseStatusStrg", "")
            if str(status).upper() != "MORE":
                break
            search_position += len(records)

# ------------------------- sync entrypoint -------------------------

def _default_range() -> Tuple[date, date]:
    """
    Incremental range: last ingested day minus 1 → today.
    """
    last_ts: Optional[datetime] = db.session.query(func.max(AttendanceEvent.timestamp)).scalar()
    if last_ts:
        start = (last_ts.date() - timedelta(days=1))
    else:
        start = date.today() - timedelta(days=int(_cfg("SYNC_LOOKBACK_DAYS", 30)))
    end = date.today()
    if start > end:
        start = end
    return start, end

def run_full_sync() -> Dict:
    """
    Returns:
    {
      "fetched_events": int,
      "inserted_events": int,
      "min_date": date|None,
      "max_date": date|None,
      "errors": str|None
    }
    """
    stats = {
        "fetched_events": 0,
        "inserted_events": 0,
        "min_date": None,
        "max_date": None,
        "errors": None
    }

    # 1) Employee directory (and mirror it locally so we always have names/rooms)
    emp_map = fetch_employees_from_device()
    try:
        upsert_operators_from_map(emp_map)
    except Exception as e:
        log.warning("Could not upsert Operators from device map: %s", e)

    # 2) Date range (incremental)
    start, end = _default_range()
    stats["min_date"] = start
    stats["max_date"] = end

    # 3) Pull events + insert (fetch window internally includes next morning 06:00+grace)
    try:
        events_iter = fetch_events(start, end, emp_map)
        fetched, inserted = insert_events_from_device(events_iter)
        stats["fetched_events"] = fetched
        stats["inserted_events"] = inserted
    except (ConnectTimeout, ReadTimeout) as e:
        msg = f"Device timeout: {e}"
        log.error(msg)
        stats["errors"] = msg
    except RequestException as e:
        # include server challenge if present
        hdr = getattr(getattr(e, "response", None), "headers", {}) or {}
        chal = hdr.get("WWW-Authenticate")
        extra = f" (WWW-Authenticate: {chal})" if chal else ""
        msg = f"Device HTTP error: {e}{extra}"
        log.error(msg)
        stats["errors"] = msg
    except Exception as e:
        log.exception("Sync failed")
        stats["errors"] = str(e)

    return stats

# helper: POST with auth fallback if server demands Basic
def _post_json_with_auth_fallback(s: Session, url: str, payload: dict, timeout: tuple[float, float]) -> dict:
    """
    POST JSON and handle Hik quirkiness:
    - Try preferred auth (per DEVICE_HTTP_AUTH: auto=digest first).
    - On 401, log the server challenge and retry once with the other scheme.
    - Return {} on empty bodies, raise for_status otherwise.
    """
    user = _cfg("USERNAME", "admin")
    pw   = _cfg("PASSWORD", "12345")
    mode = str(_cfg("DEVICE_HTTP_AUTH", "auto")).lower()

    def _set_auth(kind: str):
        s.auth = HTTPBasicAuth(user, pw) if kind == "basic" else HTTPDigestAuth(user, pw)

    # decide order
    order = ["digest", "basic"] if mode in ("auto", "digest") else ["basic", "digest"]

    last_resp = None
    tried = []
    for kind in order:
        tried.append(kind)
        _set_auth(kind)
        resp = s.post(url, json=payload, timeout=timeout)
        # success and non-401 errors handled uniformly below
        if resp.status_code != 401:
            last_resp = resp
            break

        # 401 – log what the device asked for and try the other auth once
        chal = resp.headers.get("WWW-Authenticate", "")
        log.warning("401 from %s with %s auth; WWW-Authenticate: %r", url, kind.upper(), chal)
        last_resp = resp
        # loop proceeds to the other kind

    # At this point we either have non-401 or we exhausted both
    last_resp.raise_for_status()
    try:
        return last_resp.json() or {}
    except Exception:
        return {}
