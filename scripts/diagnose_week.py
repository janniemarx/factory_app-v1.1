from __future__ import annotations
from datetime import datetime, date, time, timedelta
from typing import List

from app import create_app
from models import db
from models.operator import Operator
from models.attendance import AttendanceEvent, AttendanceDaily, OvertimeRequest
from blueprints.attendance.helpers import iso_monday
from blueprints.attendance.db_helpers import recompute_range


def _tz_offset(cfg) -> timedelta:
    s = str(cfg.get('DEVICE_TZ_OFFSET', '+02:00')).strip()
    try:
        sign = 1 if s[0] == '+' else -1
        hh, mm = s[1:].split(':')
        return timedelta(hours=sign*int(hh), minutes=sign*int(mm))
    except Exception:
        return timedelta(hours=2)


def to_local(dt: datetime, cfg) -> datetime:
    if not dt:
        return None
    return dt + _tz_offset(cfg)


def pick_recent_week(cfg) -> tuple[date, date]:
    max_ts = db.session.query(db.func.max(AttendanceEvent.timestamp)).scalar()
    if not max_ts:
        # fallback to current week
        today = date.today()
    else:
        # Convert latest event to local date to anchor the week
        today = (max_ts + _tz_offset(cfg)).date()
    mon = iso_monday(today)
    sat = mon + timedelta(days=5)
    return mon, sat


def find_ops(names: List[str]) -> List[Operator]:
    found = []
    for nm in names:
        q = Operator.query
        q = q.filter((Operator.full_name.ilike(f"%{nm}%")) | (Operator.username.ilike(f"%{nm}%")))
        ops = q.all()
        for op in ops:
            if op not in found:
                found.append(op)
    return found


def main():
    app = create_app()
    with app.app_context():
        cfg = app.config
        start_date, end_date = pick_recent_week(cfg)
        print(f"Week: {start_date} -> {end_date}")

        names = ['Samuel', 'Lucky', 'Reggie', 'Frans']
        ops = find_ops(names)
        if not ops:
            print("No matching operators found for names:", names)
            return
        op_ids = [op.id for op in ops]

        # Recompute range for these operators
        recompute_range(start_date, end_date, operator_ids=op_ids)

        # Dump per-day info
        for op in ops:
            print("\n== ", (op.full_name or op.username), f"[emp:{op.emp_no}] room:{op.room_number}")
            d = start_date
            while d <= end_date:
                daily = AttendanceDaily.query.filter_by(operator_id=op.id, day=d).one_or_none()
                # pending OT
                ots = OvertimeRequest.query.filter_by(operator_id=op.id, day=d, status='pending').all()
                ot_hours = sum([(o.proposed_hours or o.hours or 0.0) for o in ots])
                if daily or ots:
                    fi = to_local(daily.first_in, cfg) if daily else None
                    lo = to_local(daily.last_out, cfg) if daily else None
                    wh = (daily.worked_seconds or 0)/3600.0 if daily else 0
                    ot1 = (daily.ot1_seconds or 0)/3600.0 if daily else 0
                    ot2 = (daily.ot2_seconds or 0)/3600.0 if daily else 0
                    flags = []
                    if daily and daily.missing_in:
                        flags.append('Missing IN')
                    if daily and daily.missing_out:
                        flags.append('Missing OUT')
                    dow = d.strftime('%a')
                    print(f"  {d} ({dow}) | IN:{fi.strftime('%H:%M') if fi else '—'} OUT:{lo.strftime('%H:%M') if lo else '—'} | Worked:{wh:.2f}h OT1:{ot1:.2f}h OT2:{ot2:.2f}h | PendingOT:{ot_hours:.2f}h | {'; '.join(flags) if flags else ''}")
                d += timedelta(days=1)


if __name__ == '__main__':
    main()
