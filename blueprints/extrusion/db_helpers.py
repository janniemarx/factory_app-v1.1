# blueprints/extrusion/db_helpers.py
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple
from sqlalchemy.exc import SQLAlchemyError

from models import db
from models.extrusion import (
    Extruder, ExtrudedProfile,
    ExtrusionSession, ExtrusionRunSegment, ExtrusionRatePlan,
    ExtrusionMaterialUsage, ExtrusionCycleLog, ExtrusionPrestartChecklist,
    MaterialType, UsageUnit, ReadingType, BAG_25KG, OIL_CAN_5L, ExtrusionProfileSettings
)

# ---------------------------
# Utilities / Commit wrapper
# ---------------------------

def safe_commit() -> Tuple[bool, Optional[str]]:
    try:
        db.session.commit()
        return True, None
    except SQLAlchemyError as e:
        db.session.rollback()
        return False, str(e)


def _now() -> datetime:
    return datetime.utcnow()


# ---------------------------
# Master data helpers
# ---------------------------

def get_extruders(active_only: bool = True) -> List[Extruder]:
    q = Extruder.query
    if active_only:
        q = q.filter_by(is_active=True)
    rows = q.order_by(Extruder.id.asc()).all()
    if not rows:
        # first run / empty DB: create EXTR-1 and EXTR-2
        ensure_two_extruders()
        rows = q.order_by(Extruder.id.asc()).all()
    return rows

def ensure_two_extruders() -> None:
    """
    Ensure EXTR-1 and EXTR-2 exist (active). Ids will be whatever the DB assigns.
    """
    created = False
    want = [("EXTR-1", "Extruder 1"), ("EXTR-2", "Extruder 2")]
    for code, name in want:
        if not Extruder.query.filter_by(code=code).first():
            db.session.add(Extruder(code=code, name=name, is_active=True))
            created = True
    if created:
        db.session.commit()




def get_profiles() -> List[ExtrudedProfile]:
    return ExtrudedProfile.query.order_by(ExtrudedProfile.code.asc()).all()



def get_latest_profile_template(profile_id: int, extruder_id: int) -> Optional[ExtrusionProfileSettings]:
    return (ExtrusionProfileSettings.query
            .filter_by(profile_id=profile_id, extruder_id=extruder_id, is_active=True)
            .order_by(ExtrusionProfileSettings.effective_from.desc())
            .first())


def create_profile_template(
    profile_id: int,
    extruder_id: int,                 # <-- add this
    rpm: Optional[int] = None,
    gpps_kg_h: Optional[float] = None,
    talc_kg_h: Optional[float] = None,
    fire_retardant_kg_h: Optional[float] = None,
    recycling_kg_h: Optional[float] = None,
    co2_kg_h: Optional[float] = None,
    alcohol_l_h: Optional[float] = None,
    # Hz fields (Machine-1)
    extruder_hz: Optional[float] = None,
    co2_hz: Optional[float] = None,
    alcohol_hz: Optional[float] = None,
    oil_hz: Optional[float] = None,
    heat_table: Optional[Dict[str, Any]] = None,
    notes: Optional[str] = None,
) -> Tuple[Optional[ExtrusionProfileSettings], Optional[str]]:
    tpl = ExtrusionProfileSettings(
        profile_id=profile_id,
        extruder_id=extruder_id,
        rpm=rpm,
        gpps_kg_h=gpps_kg_h,
        talc_kg_h=talc_kg_h,
        fire_retardant_kg_h=fire_retardant_kg_h,
        recycling_kg_h=recycling_kg_h,
        co2_kg_h=co2_kg_h,
        alcohol_l_h=alcohol_l_h,
        extruder_hz=extruder_hz,
        co2_hz=co2_hz,
        alcohol_hz=alcohol_hz,
        oil_hz=oil_hz,
        heat_table=heat_table or {},
        notes=notes,
        created_at=_now(),
        is_active=True,
    )
    db.session.add(tpl)
    ok, err = safe_commit()
    return (tpl if ok else None), err



# ----------- seed master data (2 extruders + your profiles) -----------

def ensure_seed_master_data() -> Tuple[bool, Optional[str]]:
    """
    Creates EXTR-1/EXTR-2 and the profiles you listed if they don't exist.
    """
    try:
        # Extruders
        want = [("EXTR-1", "Extruder 1"), ("EXTR-2", "Extruder 2")]
        for code, name in want:
            if not Extruder.query.filter_by(code=code).first():
                db.session.add(Extruder(code=code, name=name, is_active=True))

        # Profiles
        profiles = [
            ("CC12", 3.0, 114, "Cornice CC12"),
            ("EX12", 2.0, 84,  "Extruded EX12"),
            ("EX03", 2.0, 72,  "Extruded EX03"),
            ("EX04", 2.0, 96,  "Extruded EX04"),
            ("EX02", 2.0, 72,  "Extruded EX02"),
            ("EX01", 2.0, 72,  "Extruded EX01"),
        ]
        for code, length_m, ppb, desc in profiles:
            if not ExtrudedProfile.query.filter_by(code=code).first():
                db.session.add(ExtrudedProfile(code=code, length_m=length_m, pieces_per_box=ppb, description=desc))

        return safe_commit()
    except Exception as e:
        db.session.rollback()
        return False, str(e)


# ---------------------------
# Session lifecycle
# ---------------------------

def start_extrusion_session(
    extruder_id: int,
    profile_id: int,
    operator_id: Optional[int],
    # snapshot overrides intentionally None – follow latest active settings
    snapshot_setpoints: Optional[Dict[str, Any]] = None,
    snapshot_heat_table: Optional[Dict[str, Any]] = None,
    # seed a first rate plan from these values (recommended)
    initial_rate_plan: Optional[Dict[str, Any]] = None,
    # Prestart (REQUIRED)
    checklist_answers: Dict[str, Any] | None = None,
    checklist_approved: bool = True,
    checklist_notes: Optional[str] = None,
    start_time: Optional[datetime] = None,
) -> Tuple[Optional[ExtrusionSession], Optional[str]]:
    """
    Creates a session, stores settings snapshot, opens first run segment,
    persists prestart checklist and initial rate plan.
    Enforces that a prestart checklist exists and is approved.
    """
    try:
        if not checklist_answers or not checklist_approved:
            return None, "Pre-start checklist is required and must be approved before starting."

        start = start_time or _now()

        latest = get_latest_profile_template(profile_id, extruder_id)
        snapshot = {
            # Machine-2 (if present)
            "rpm": latest.rpm if latest else None,
            "gpps_kg_h": latest.gpps_kg_h if latest else None,
            "talc_kg_h": latest.talc_kg_h if latest else None,
            "fire_retardant_kg_h": latest.fire_retardant_kg_h if latest else None,
            "recycling_kg_h": latest.recycling_kg_h if latest else None,
            "co2_kg_h": latest.co2_kg_h if latest else None,
            "alcohol_l_h": latest.alcohol_l_h if latest else None,
            # Machine-1 (if present)
            "extruder_hz": latest.extruder_hz if latest else None,
            "co2_hz": latest.co2_hz if latest else None,
            "alcohol_hz": latest.alcohol_hz if latest else None,
            "oil_hz": latest.oil_hz if latest else None,
        }
        heat_snapshot = (latest.heat_table.copy() if latest and latest.heat_table else {})
        if snapshot_setpoints:
            snapshot.update({k: v for k, v in snapshot_setpoints.items() if v is not None})

        heat_snapshot = (latest.heat_table.copy() if latest and latest.heat_table else {})
        if snapshot_heat_table:
            heat_snapshot.update(snapshot_heat_table)

        sess = ExtrusionSession(
            extruder_id=extruder_id,
            profile_id=profile_id,
            operator_id=operator_id,
            status="running",
            started_at=start,
            is_paused=False,
            pause_start=None,
            setpoints_snapshot=snapshot,
            heat_table_snapshot=heat_snapshot,
        )
        db.session.add(sess)
        db.session.flush()  # need id for children

        seg = ExtrusionRunSegment(session_id=sess.id, started_at=start)
        db.session.add(seg)

        # Initialize first rate plan
        plan_values = {
            "rpm": snapshot.get("rpm"),
            "gpps_kg_h": snapshot.get("gpps_kg_h"),
            "talc_kg_h": snapshot.get("talc_kg_h"),
            "fire_retardant_kg_h": snapshot.get("fire_retardant_kg_h"),
            "recycling_kg_h": snapshot.get("recycling_kg_h"),
            "co2_kg_h": snapshot.get("co2_kg_h"),
            "alcohol_l_h": snapshot.get("alcohol_l_h"),
        }
        if initial_rate_plan:
            plan_values.update({k: v for k, v in initial_rate_plan.items() if v is not None})

        db.session.add(ExtrusionRatePlan(session_id=sess.id, effective_from=start, **plan_values))

        # Required pre-start checklist
        db.session.add(ExtrusionPrestartChecklist(
            session_id=sess.id,
            completed_by_id=operator_id,
            completed_at=start,
            answers=checklist_answers or {},
            approved=bool(checklist_approved),
            notes=checklist_notes,
        ))

        ok, err = safe_commit()
        return (sess if ok else None), err

    except Exception as e:
        db.session.rollback()
        return None, str(e)


def pause_session(session: ExtrusionSession) -> Tuple[bool, Optional[str]]:
    if session.status != "running" or session.is_paused:
        return True, None
    now = _now()
    open_seg = (ExtrusionRunSegment.query
                .filter_by(session_id=session.id, ended_at=None)
                .order_by(ExtrusionRunSegment.started_at.desc())
                .first())
    if open_seg:
        open_seg.ended_at = now
    session.is_paused = True
    session.pause_start = now
    return safe_commit()


def resume_session(session: ExtrusionSession) -> Tuple[bool, Optional[str]]:
    if session.status != "running" or not session.is_paused:
        return True, None
    now = _now()
    session.is_paused = False
    session.pause_start = None
    db.session.add(ExtrusionRunSegment(session_id=session.id, started_at=now))
    return safe_commit()


def complete_session(session: ExtrusionSession, end_time: Optional[datetime] = None) -> Tuple[bool, Optional[str]]:
    if session.status not in ("running",):
        return False, "Only a running session can be completed."

    now = end_time or _now()

    if session.is_paused:
        ok, err = resume_session(session)
        if not ok:
            return False, err

    open_seg = (ExtrusionRunSegment.query
                .filter_by(session_id=session.id, ended_at=None)
                .order_by(ExtrusionRunSegment.started_at.desc())
                .first())
    if open_seg:
        open_seg.ended_at = now

    session.ended_at = now
    session.status = "completed"
    session.is_boxing_ready = True            # <-- NEW: ready for boxing

    ok, err = safe_commit()
    if not ok:
        return False, err

    ok2, err2, _metrics = recompute_session_metrics(session)
    if not ok2:
        return False, err2
    return True, None



# ---------------------------
# Rate plans & logs
# ---------------------------

def add_rate_plan(
    session_id: int,
    effective_from: Optional[datetime] = None,
    rpm: Optional[int] = None,
    gpps_kg_h: Optional[float] = None,
    talc_kg_h: Optional[float] = None,
    fire_retardant_kg_h: Optional[float] = None,
    recycling_kg_h: Optional[float] = None,
    co2_kg_h: Optional[float] = None,
    alcohol_l_h: Optional[float] = None,
) -> Tuple[Optional[ExtrusionRatePlan], Optional[str]]:
    try:
        rp = ExtrusionRatePlan(
            session_id=session_id,
            effective_from=effective_from or _now(),
            rpm=rpm,
            gpps_kg_h=gpps_kg_h,
            talc_kg_h=talc_kg_h,
            fire_retardant_kg_h=fire_retardant_kg_h,
            recycling_kg_h=recycling_kg_h,
            co2_kg_h=co2_kg_h,
            alcohol_l_h=alcohol_l_h,
        )
        db.session.add(rp)
        ok, err = safe_commit()
        return (rp if ok else None), err
    except Exception as e:
        db.session.rollback()
        return None, str(e)


def log_material_usage(
    session_id: int,
    material: MaterialType | str,
    unit: UsageUnit | str,
    quantity: float,
    note: Optional[str] = None,
    timestamp: Optional[datetime] = None,
) -> Tuple[bool, Optional[str]]:
    try:
        if isinstance(material, str):
            material = MaterialType(material)
        if isinstance(unit, str):
            unit = UsageUnit(unit)

        row = ExtrusionMaterialUsage(
            session_id=session_id,
            timestamp=timestamp or _now(),
            material=material,
            unit=unit,
            quantity=float(quantity or 0.0),
            note=note,
        )
        db.session.add(row)
        return safe_commit()
    except Exception as e:
        db.session.rollback()
        return False, str(e)


def log_cycle(
    session_id: int,
    reading_value: int,
    reading_type: ReadingType | str = ReadingType.ABSOLUTE,
    note: Optional[str] = None,
    timestamp: Optional[datetime] = None,
) -> Tuple[bool, Optional[str]]:
    try:
        if isinstance(reading_type, str):
            reading_type = ReadingType(reading_type)

        row = ExtrusionCycleLog(
            session_id=session_id,
            timestamp=timestamp or _now(),
            reading_type=reading_type,
            reading_value=int(reading_value or 0),
            note=note,
        )
        db.session.add(row)
        ok, err = safe_commit()
        if not ok:
            return False, err

        sess = ExtrusionSession.query.get(session_id)
        ok2, err2, _ = recompute_session_metrics(sess)
        return ok2, err2
    except Exception as e:
        db.session.rollback()
        return False, str(e)


def save_prestart_checklist(
    session_id: int,
    completed_by_id: Optional[int],
    answers: Dict[str, Any],
    approved: bool = True,
    notes: Optional[str] = None,
) -> Tuple[bool, Optional[str]]:
    try:
        chk = ExtrusionPrestartChecklist.query.filter_by(session_id=session_id).first()
        if chk:
            chk.answers = answers or {}
            chk.completed_by_id = completed_by_id
            chk.completed_at = _now()
            chk.approved = bool(approved)
            chk.notes = notes
        else:
            chk = ExtrusionPrestartChecklist(
                session_id=session_id,
                completed_by_id=completed_by_id,
                completed_at=_now(),
                answers=answers or {},
                approved=bool(approved),
                notes=notes,
            )
            db.session.add(chk)
        return safe_commit()
    except Exception as e:
        db.session.rollback()
        return False, str(e)


# ---------------------------
# Metrics & computations
# ---------------------------

def _total_run_seconds(session: ExtrusionSession, as_of: Optional[datetime] = None) -> float:
    total = 0.0
    now = as_of or _now()
    for seg in session.run_segments:
        start = seg.started_at
        end = seg.ended_at or now
        if start and end and end > start:
            total += (end - start).total_seconds()
    return total


def _rate_intervals(session: ExtrusionSession, as_of: Optional[datetime] = None) -> List[Tuple[datetime, datetime, ExtrusionRatePlan]]:
    now = as_of or _now()
    bounds_end = session.ended_at or now
    rates = sorted(session.rate_plans, key=lambda r: r.effective_from or session.started_at)
    if not rates:
        return []

    intervals: List[Tuple[datetime, datetime, ExtrusionRatePlan]] = []
    for idx, rp in enumerate(rates):
        start = max(rp.effective_from or session.started_at, session.started_at)
        if idx + 1 < len(rates):
            next_start = rates[idx + 1].effective_from or bounds_end
            end = min(next_start, bounds_end)
        else:
            end = bounds_end
        if end > start:
            intervals.append((start, end, rp))
    return intervals


def _overlap_seconds(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> float:
    start = max(a_start, b_start)
    end = min(a_end, b_end)
    return max(0.0, (end - start).total_seconds())


def compute_expected_usage(session: ExtrusionSession, as_of: Optional[datetime] = None) -> Dict[str, float]:
    now = as_of or _now()
    intervals = _rate_intervals(session, as_of=now)
    expected = dict(gpps_kg=0.0, talc_kg=0.0, fire_retardant_kg=0.0, recycling_kg=0.0, co2_kg=0.0, alcohol_l=0.0)
    if not intervals:
        return {k: 0.0 for k in expected}

    for (rp_start, rp_end, rp) in intervals:
        for seg in session.run_segments:
            seg_start = seg.started_at
            seg_end = seg.ended_at or now
            secs = _overlap_seconds(rp_start, rp_end, seg_start, seg_end)
            if secs <= 0:
                continue
            hours = secs / 3600.0
            if rp.gpps_kg_h:            expected["gpps_kg"]           += rp.gpps_kg_h * hours
            if rp.talc_kg_h:            expected["talc_kg"]           += rp.talc_kg_h * hours
            if rp.fire_retardant_kg_h:  expected["fire_retardant_kg"] += rp.fire_retardant_kg_h * hours
            if rp.recycling_kg_h:       expected["recycling_kg"]      += rp.recycling_kg_h * hours
            if rp.co2_kg_h:             expected["co2_kg"]            += rp.co2_kg_h * hours
            if rp.alcohol_l_h:          expected["alcohol_l"]         += rp.alcohol_l_h * hours

    for k in expected:
        expected[k] = round(float(expected[k]), 3)
    return expected


def compute_actual_usage(session: ExtrusionSession) -> Dict[str, float]:
    totals = {
        "gpps_kg": 0.0,
        "talc_kg": 0.0,
        "fire_retardant_kg": 0.0,
        "recycling_kg": 0.0,
        "co2_kg": 0.0,
        "alcohol_l": 0.0,
        "oil_l": 0.0,
    }
    for row in session.material_usages:
        if row.material == MaterialType.GPPS:
            totals["gpps_kg"] += row.as_kg
        elif row.material == MaterialType.TALC:
            totals["talc_kg"] += row.as_kg
        elif row.material == MaterialType.FIRE_RETARDANT:
            totals["fire_retardant_kg"] += row.as_kg
        elif row.material == MaterialType.RECYCLING:
            totals["recycling_kg"] += row.as_kg
        elif row.material == MaterialType.CO2:
            totals["co2_kg"] += row.as_kg
        elif row.material == MaterialType.ALCOHOL:
            totals["alcohol_l"] += row.as_litres
        elif row.material == MaterialType.OIL:
            totals["oil_l"] += row.as_litres

    for k in totals:
        totals[k] = round(float(totals[k]), 3)
    return totals


def compute_pieces_from_cycles(session: ExtrusionSession) -> int:
    pieces = 0
    last_abs: Optional[int] = None
    for log in sorted(session.cycle_logs, key=lambda r: r.timestamp):
        if log.reading_type == ReadingType.DELTA:
            if log.reading_value and log.reading_value > 0:
                pieces += int(log.reading_value)
        else:
            if last_abs is None:
                last_abs = int(log.reading_value or 0)
            else:
                delta = int((log.reading_value or 0) - last_abs)
                if delta > 0:
                    pieces += delta
                last_abs = int(log.reading_value or 0)
    return max(0, int(pieces))


def recompute_session_metrics(session: ExtrusionSession) -> Tuple[bool, Optional[str], Dict[str, Any]]:
    try:
        run_seconds = _total_run_seconds(session)
        run_hours = round(run_seconds / 3600.0, 3)

        expected = compute_expected_usage(session)
        actual = compute_actual_usage(session)

        pieces = compute_pieces_from_cycles(session)
        per_box = int(session.profile.pieces_per_box or 1)
        theoretical_boxes = pieces // per_box

        session.pieces_produced = int(pieces)
        session.theoretical_boxes = int(theoretical_boxes)

        ok, err = safe_commit()
        metrics = {
            "run_hours": run_hours,
            "expected": expected,
            "actual": actual,
            "pieces": pieces,
            "theoretical_boxes": theoretical_boxes,
            "actual_boxes_boxed": int(session.actual_boxes_boxed or 0),
            "estimated_damage_pieces": int(session.estimated_damage_pieces),
        }
        return ok, err, metrics
    except Exception as e:
        db.session.rollback()
        return False, str(e), {}


# ---------------------------
# Convenience queries
# ---------------------------

def get_session(session_id: int) -> Optional[ExtrusionSession]:
    return ExtrusionSession.query.get(session_id)


def list_sessions(
    status: Optional[str] = None,
    extruder_id: Optional[int] = None,
    profile_id: Optional[int] = None,
    limit: int = 200,
) -> List[ExtrusionSession]:
    q = ExtrusionSession.query
    if status:
        q = q.filter_by(status=status)
    if extruder_id:
        q = q.filter_by(extruder_id=extruder_id)
    if profile_id:
        q = q.filter_by(profile_id=profile_id)
    return q.order_by(ExtrusionSession.started_at.desc()).limit(limit).all()


# ---------------------------
# Human helpers (units)
# ---------------------------

def bags_to_kg(bags: float) -> float:
    return float(bags or 0.0) * BAG_25KG


def cans5l_to_l(cans: float) -> float:
    return float(cans or 0.0) * OIL_CAN_5L
