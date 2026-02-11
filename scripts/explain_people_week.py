from __future__ import annotations
import argparse
from datetime import datetime, date, timedelta
import sys, os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app import create_app
from models import db
from models.operator import Operator
from models.attendance import AttendanceEvent, AttendanceDaily


def _tz_offset(cfg) -> timedelta:
    s = str(cfg.get('DEVICE_TZ_OFFSET', '+02:00')).strip()
    try:
        sign = 1 if s[0] == '+' else -1
        hh, mm = s[1:].split(':')
        return timedelta(hours=sign * int(hh), minutes=sign * int(mm))
    except Exception:
        return timedelta(hours=2)


def to_local(dt: datetime, cfg) -> datetime | None:
    if not dt:
        return None
    return dt + _tz_offset(cfg)


def iso_monday(d: date) -> date:
    # Monday of ISO week for date d
    return d - timedelta(days=(d.weekday() - 0) % 7)


def pick_recent_week(cfg) -> tuple[date, date]:
    max_ts = db.session.query(db.func.max(AttendanceEvent.timestamp)).scalar()
    if not max_ts:
        today = date.today()
    else:
        today = (max_ts + _tz_offset(cfg)).date()
    mon = iso_monday(today)
    sat = mon + timedelta(days=5)
    return mon, sat


def find_ops(filters: list[str]) -> list[Operator]:
    if not filters:
        return []
    seen = set()
    out = []
    for nm in filters:
        q = Operator.query.filter(
            (Operator.full_name.ilike(f"%{nm}%")) | (Operator.username.ilike(f"%{nm}%"))
        )
        for op in q.all():
            if op.id not in seen:
                out.append(op)
                seen.add(op.id)
    return out


def main():
    ap = argparse.ArgumentParser(description="Explain weekly Normal/OT breakdown for operators by name filter(s)")
    ap.add_argument('--names', required=True, help='Comma-separated fragments to match full_name/username')
    ap.add_argument('--start', help='Start date YYYY-MM-DD (defaults to recent week Monday)')
    ap.add_argument('--end', help='End date YYYY-MM-DD (defaults to Saturday of the same week)')
    ap.add_argument('--scan-weeks', type=int, default=0, help='If >0, list totals for the last N ISO weeks instead of detailed days')
    args = ap.parse_args()

    app = create_app()
    with app.app_context():
        cfg = app.config
        if args.start:
            start_date = date.fromisoformat(args.start)
            if args.end:
                end_date = date.fromisoformat(args.end)
            else:
                # Snap to Saturday of that ISO week if not provided
                mon = iso_monday(start_date)
                end_date = mon + timedelta(days=5)
        else:
            start_date, end_date = pick_recent_week(cfg)

        names = [s.strip() for s in args.names.split(',') if s.strip()]
        ops = find_ops(names)
        if not ops:
            print('No operators found for filters:', names)
            return

        lines = []
        def emit(s: str):
            print(s)
            lines.append(s)

        if args.scan_weeks and args.scan_weeks > 0:
            # Scan last N weeks
            for w in range(args.scan_weeks):
                # Each step go back 7 days from the chosen start_date week
                mon = start_date - timedelta(days=7*w)
                sat = mon + timedelta(days=5)
                emit("")
                emit(f"== Week {mon} -> {sat}")
                for op in ops:
                    q = (db.session.query(AttendanceDaily)
                         .filter(AttendanceDaily.operator_id == op.id,
                                 AttendanceDaily.day >= mon,
                                 AttendanceDaily.day <= sat)
                         .all())
                    n = sum([(r.normal_seconds or 0) for r in q]) / 3600.0
                    o1 = sum([(r.ot1_seconds or 0) for r in q]) / 3600.0
                    o2 = sum([(r.ot2_seconds or 0) for r in q]) / 3600.0
                    emit(f"   - {(op.full_name or op.username)}: Normal={n:.2f}h OT={o1+o2:.2f}h Worked={n+o1+o2:.2f}h")
        else:
            emit(f"Week: {start_date} -> {end_date}")
            for op in ops:
                emit("")
                emit(f"== {(op.full_name or op.username)} [emp:{op.emp_no}] room:{op.room_number} night:{'Y' if op.is_night_shift else 'N'}")
                total_norm = 0
                total_ot1 = 0
                total_ot2 = 0
                d = start_date
                while d <= end_date:
                    daily = AttendanceDaily.query.filter_by(operator_id=op.id, day=d).one_or_none()
                    if daily:
                        fi = to_local(daily.first_in, cfg)
                        lo = to_local(daily.last_out, cfg)
                        norm_h = (daily.normal_seconds or 0) / 3600.0
                        ot1_h = (daily.ot1_seconds or 0) / 3600.0
                        ot2_h = (daily.ot2_seconds or 0) / 3600.0
                        total_norm += norm_h
                        total_ot1 += ot1_h
                        total_ot2 += ot2_h
                        flags = []
                        if daily.segment_count == 0:
                            flags.append('No punches')
                        if daily.missing_in:
                            flags.append('Missing IN')
                        if daily.missing_out:
                            flags.append('Missing OUT')
                        dow = d.strftime('%a')
                        emit(f"  {d} ({dow}) | IN:{fi.strftime('%H:%M') if fi else '—'} OUT:{lo.strftime('%H:%M') if lo else '—'} | Normal:{norm_h:.2f}h OT1:{ot1_h:.2f}h OT2:{ot2_h:.2f}h | {'; '.join(flags) if flags else ''}")
                    else:
                        emit(f"  {d} ({d.strftime('%a')}) | No daily record")
                    d += timedelta(days=1)

                emit(f"  -- Totals: Normal={total_norm:.2f}h, OT={total_ot1+total_ot2:.2f}h (OT1={total_ot1:.2f}h, OT2={total_ot2:.2f}h), Worked={total_norm+total_ot1+total_ot2:.2f}h")

        # Write to diagnostics file
        try:
            import pathlib, time
            outdir = pathlib.Path(ROOT) / 'diagnostics'
            outdir.mkdir(parents=True, exist_ok=True)
            ts = time.strftime('%Y%m%d-%H%M%S')
            p_cur = outdir / f"explain-{ts}.txt"
            p_last = outdir / "last_explain.txt"
            content = "\n".join(lines) + "\n"
            p_cur.write_text(content, encoding='utf-8')
            p_last.write_text(content, encoding='utf-8')
            print(f"\nSaved: {p_cur}")
        except Exception as e:
            print("Failed to write diagnostics:", e)


if __name__ == '__main__':
    main()
