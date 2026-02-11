from datetime import datetime, timedelta
from collections import defaultdict

from sqlalchemy import func
from models import db
from models.operator import Operator
from models.moulded_cornice import (
    MouldedCorniceSession,
    MouldedMachine,
)
from models.moulded_boxing import (
    MouldedBoxingSession,
    MouldedBoxedItem,
    MOULDED_CORNICES_PER_BOX,
)

# -----------------------
# Small utilities
# -----------------------

def _safe_minutes(start, end):
    if not start or not end:
        return None
    secs = (end - start).total_seconds()
    if secs <= 0:
        return None
    return round(secs / 60.0, 2)


def _avg(values):
    vals = [v for v in values if v is not None]
    return round(sum(vals) / len(vals), 2) if vals else None


def _profile_breakdown(session: MouldedCorniceSession):
    """
    Returns:
      lines_count: number of configured lines
      per_profile: dict {profile_code: quantity} where quantity = cycles per line
    """
    lines = session.lines or []
    lines_count = len(lines)
    per = defaultdict(int)
    cycles = session.cycles or 0
    for ln in lines:
        if ln and ln.profile_code:
            per[ln.profile_code] += cycles
    return lines_count, dict(per)


def _period_key(dt: datetime, today: datetime.date, which: str) -> bool:
    if not dt:
        return False
    if which == 'today':
        return dt.date() == today
    if which == 'month':
        return dt.year == today.year and dt.month == today.month
    if which == 'year':
        return dt.year == today.year
    if which == 'last_year':
        return dt.year == (today.year - 1)
    return False


def _performance_label(avg_time, benchmark):
    """
    Lower is better. Returns (label, delta).
    label: 'above' if avg < benchmark, 'below' if avg > benchmark, 'at' if equal, None if missing data
    delta: avg - benchmark (negative is good)
    """
    if avg_time is None or benchmark is None:
        return None, None
    delta = round(avg_time - benchmark, 2)
    if delta < 0:
        return "above", delta
    if delta > 0:
        return "below", delta
    return "at", 0.0


def _apply_benchmarks_90d(rows, machines, today):
    """
    For each machine, compute the benchmark as the fastest (minimum) session avg cycle time
    in the LAST 90 DAYS (rolling window), irrespective of the selected period.

    rows: dict keyed by machine_id (already created in _empty_machine_rows)
    machines: list of MouldedMachine objects included in the current view (respects machine filter)
    today: date
    """
    window_start = datetime.combine(today - timedelta(days=90), datetime.min.time())

    # Fetch all completed sessions within last 90 days for the INCLUDED machines
    machine_ids = [m.id for m in machines]
    if not machine_ids:
        return

    bench_q = (
        MouldedCorniceSession.query
        .filter(MouldedCorniceSession.status == 'completed')
        .filter(MouldedCorniceSession.machine_id.in_(machine_ids))
        .filter(MouldedCorniceSession.start_time >= window_start)
        .with_entities(
            MouldedCorniceSession.machine_id,
            MouldedCorniceSession.start_time,
            MouldedCorniceSession.end_time,
            MouldedCorniceSession.cycles,
        )
    )

    # Collect per-session avg times by machine in the last 90 days
    per_machine_times_90 = defaultdict(list)
    for mid, st, et, cyc in bench_q:
        if not st or not et or not cyc or cyc <= 0:
            continue
        mins = _safe_minutes(st, et)
        if mins is None:
            continue
        per_machine_times_90[mid].append(round(mins / cyc, 2))

    # Apply benchmark (min) to the rows
    for mid, bucket in rows.items():
        times = per_machine_times_90.get(mid, [])
        bucket['benchmark_min_time'] = (min(times) if times else None)

    # Performance vs benchmark will be computed in _finalize()
    return


def _empty_machine_rows(machines):
    """
    Single, canonical schema for machine rows (includes wastage fields).
    """
    return (
        {
            m.id: {
                'machine_id': m.id,
                'machine': m.name,
                'sessions': 0,
                'cycles': 0,
                'avg_cycle_time_min': None,
                'benchmark_min_time': None,
                'performance': None,
                'expectation_delta': None,
                'total_cornices': 0,     # produced (made) in the period
                'boxed_cornices': 0,     # actually boxed (attributed to the moulded session)
                'wastage_cornices': 0,   # made - boxed (floored at 0)
                'wastage_pct': None,     # computed in _finalize()
            }
            for m in machines
        },
        {m.id: [] for m in machines}  # per-session avg times for the period
    )


def _finalize(rows, times):
    """
    Compute period-average cycle time, performance vs benchmark, and wastage metrics.
    """
    for mid, bucket in rows.items():
        per_session_times = times[mid]
        bucket['avg_cycle_time_min'] = _avg(per_session_times)
        perf, delta = _performance_label(bucket['avg_cycle_time_min'], bucket['benchmark_min_time'])
        bucket['performance'] = perf
        bucket['expectation_delta'] = delta

        made = bucket['total_cornices'] or 0
        boxed = bucket['boxed_cornices'] or 0
        wasted = max(made - boxed, 0)
        bucket['wastage_cornices'] = wasted
        bucket['wastage_pct'] = (round((wasted / made) * 100.0, 2) if made > 0 else None)

    return list(rows.values())


# -----------------------
# Boxing helpers
# -----------------------

def _boxed_cornices_by_moulded_session(session_ids: list[int]) -> dict[int, dict[str, int]]:
    """
    Returns {moulded_session_id: {profile_code: boxed_cornices}} for all given sessions.
    Cornices = boxes*per_box + leftovers.
    """
    if not session_ids:
        return {}

    rows = (
        db.session.query(
            MouldedBoxingSession.moulded_session_id.label("msid"),
            MouldedBoxedItem.profile_code,
            func.coalesce(func.sum(MouldedBoxedItem.boxes_packed), 0),
            func.coalesce(func.sum(MouldedBoxedItem.leftovers), 0),
        )
        .join(MouldedBoxedItem, MouldedBoxedItem.session_id == MouldedBoxingSession.id)
        .filter(MouldedBoxingSession.moulded_session_id.in_(session_ids))
        .group_by(MouldedBoxingSession.moulded_session_id, MouldedBoxedItem.profile_code)
        .all()
    )

    out: dict[int, dict[str, int]] = {}
    for msid, code, boxes, leftovers in rows:
        per_box = MOULDED_CORNICES_PER_BOX.get(code, 0)
        cornices = int(boxes or 0) * per_box + int(leftovers or 0)
        out.setdefault(msid, {})
        out[msid][code] = out[msid].get(code, 0) + cornices
    return out


# -----------------------
# External helpers
# -----------------------

def get_operators_list():
    return Operator.query.order_by(Operator.full_name).all()


def get_moulded_analytics(
    mould_number=None,
    operator_id=None,
    date_from=None,
    date_to=None,
    machine_id=None,
    period='today'
):
    """
    Returns:
      In single-period mode (period in {'today','month','year'}):
        {
          'factory_summary': {...},
          'machine_stats': [ ... rows with benchmark/performance + wastage ... ],
          'period': 'today' | 'month' | 'year',
          'machine_filter': {id,name} | None,
          'sessions': [ ... ]   # each row may include boxed/wastage if available
        }

      In 'all' mode:
        {
          'factory_summary': {...},
          'period': 'all',
          'machine_filter': {id,name} | None,
          'sessions': [ ... ],
          'machine_stats_all': {
             'today': [...],
             'month': [...],
             'year': [...],
             'last_year': [...],
             'compare_year_vs_last': [...]
          }
        }

      Benchmark:
        benchmark_min_time is computed as the FASTEST (lowest) session avg cycle time
        in the LAST 90 DAYS for the machine (rolling window), regardless of the chosen period.
    """
    # ---- Base query for the SESSIONS list (respects all filters) ----
    q = MouldedCorniceSession.query

    if mould_number and int(mould_number) > 0:
        q = q.filter(MouldedCorniceSession.mould_number == int(mould_number))
    if operator_id and int(operator_id) > 0:
        q = q.filter(MouldedCorniceSession.operator_id == int(operator_id))
    if machine_id and int(machine_id) > 0:
        q = q.filter(MouldedCorniceSession.machine_id == int(machine_id))

    if date_from:
        start_dt = datetime.combine(date_from, datetime.min.time())
        q = q.filter(MouldedCorniceSession.start_time >= start_dt)
    if date_to:
        end_dt = datetime.combine(date_to, datetime.max.time())
        q = q.filter(MouldedCorniceSession.start_time <= end_dt)

    sessions = q.order_by(MouldedCorniceSession.start_time.desc()).all()

    today = datetime.now().date()

    # Build the machine list for aggregation (respects the machine filter)
    if machine_id and int(machine_id) > 0:
        m = MouldedMachine.query.get(int(machine_id))
        machines = [m] if m else []
        machine_filter = {'id': int(machine_id), 'name': (m.name if m else 'Unknown')}
    else:
        machines = MouldedMachine.query.order_by(MouldedMachine.id.asc()).all()
        machine_filter = None

    # -------- Per-period aggregation scaffolding --------
    buckets = {}
    times = {}
    for key in ('today', 'month', 'year', 'last_year'):
        buckets[key], times[key] = _empty_machine_rows(machines)

    # Pre-compute last-90-days benchmark for included machines (fills benchmark_min_time)
    for key in ('today', 'month', 'year', 'last_year'):
        _apply_benchmarks_90d(buckets[key], machines, today)

    # -------- Walk filtered sessions to fill MADE totals + timing --------
    # Also collect moulded session IDs per period to attribute BOXED cornices later.
    session_ids_by_period = {k: set() for k in ('today', 'month', 'year', 'last_year')}

    session_rows = []
    all_cycle_times = []
    cycles_today = cornices_today = cycles_month = cornices_month = 0

    for s in sessions:
        cycles = s.cycles or 0
        lines_count, per_profile = _profile_breakdown(s)
        duration_min = _safe_minutes(s.start_time, s.end_time) if s.status == 'completed' else None
        avg_time_per_cycle = round(duration_min / cycles, 2) if duration_min and cycles > 0 else None
        total_cornices = cycles * lines_count

        if avg_time_per_cycle is not None:
            all_cycle_times.append(avg_time_per_cycle)

        # Attribute MADE totals and timing to the session's start_time period
        if s.start_time:
            for key in ('today', 'month', 'year', 'last_year'):
                if _period_key(s.start_time, today, key) and (s.machine_id in buckets[key]):
                    b = buckets[key][s.machine_id]
                    b['sessions'] += 1
                    b['cycles'] += cycles
                    b['total_cornices'] += total_cornices
                    if avg_time_per_cycle is not None:
                        times[key][s.machine_id].append(avg_time_per_cycle)
                    session_ids_by_period[key].add(s.id)

            if _period_key(s.start_time, today, 'today'):
                cornices_today += total_cornices
                cycles_today += cycles
            if _period_key(s.start_time, today, 'month'):
                cornices_month += total_cornices
                cycles_month += cycles

        # Basic sessions table row; will annotate with boxed/wastage later
        session_rows.append({
            'id': s.id,
            'batch_no': (s.pre_expansion.batch_no if s.pre_expansion else '-'),
            'mould': s.mould_number,
            'machine': s.machine.name if s.machine else '-',
            'operator': (s.operator.full_name if s.operator else '-'),
            'status': s.status,
            'cycles': cycles,
            'lines_count': lines_count,
            'total_cornices': total_cornices,
            'avg_time_per_cycle_min': avg_time_per_cycle,
            'session_time_min': duration_min,
            'start_time': s.start_time,
            'end_time': s.end_time,
            'per_profile': per_profile,
        })

    # ---- BOXED roll-up (attribute to the moulded session’s period) ----
    # Also annotate session_rows with boxed/wastage where available.
    row_index = {r['id']: r for r in session_rows}

    for key in ('today', 'month', 'year', 'last_year'):
        if not session_ids_by_period[key]:
            continue

        boxed_map = _boxed_cornices_by_moulded_session(list(session_ids_by_period[key]))

        # Add to machine buckets and sessions table
        for s in sessions:
            if s.id not in boxed_map or s.id not in session_ids_by_period[key]:
                continue

            total_boxed_for_session = sum(boxed_map[s.id].values())

            # Add to machine bucket for this period
            if s.machine_id in buckets[key]:
                buckets[key][s.machine_id]['boxed_cornices'] += total_boxed_for_session

            # Annotate sessions table row
            r = row_index.get(s.id)
            if r:
                made = r['total_cornices'] or 0
                boxed = total_boxed_for_session or 0
                wasted = max(made - boxed, 0)
                r['boxed_cornices'] = boxed
                r['wastage_cornices'] = wasted
                r['wastage_pct'] = (round((wasted / made) * 100.0, 2) if made > 0 else None)

    # -------- Factory summary --------
    factory_summary = {
        'avg_time_per_cycle_min': _avg(all_cycle_times),
        'total_cycles_today': cycles_today,
        'total_cycles_month': cycles_month,
        'total_cornices_today': cornices_today,
        'total_cornices_month': cornices_month,
    }

    # Finalize blocks (compute avg + performance vs 90d benchmark + wastage)
    block_today  = _finalize(buckets['today'],  times['today'])
    block_month  = _finalize(buckets['month'],  times['month'])
    block_year   = _finalize(buckets['year'],   times['year'])
    block_lastyr = _finalize(buckets['last_year'], times['last_year'])

    # Build year vs last year comparison (totals + avg-time deltas)
    compare = []
    last_map = {r['machine_id']: r for r in block_lastyr}
    for r in block_year:
        prev = last_map.get(r['machine_id'], {
            'cycles': 0,
            'total_cornices': 0,
            'avg_cycle_time_min': None,
        })
        compare.append({
            'machine_id': r['machine_id'],
            'machine': r['machine'],
            'cycles_year': r['cycles'],
            'cycles_last_year': prev['cycles'],
            'cycles_delta': r['cycles'] - prev['cycles'],

            'cornices_year': r['total_cornices'],
            'cornices_last_year': prev['total_cornices'],
            'cornices_delta': r['total_cornices'] - prev['total_cornices'],

            'avg_time_year': r['avg_cycle_time_min'],
            'avg_time_last_year': prev['avg_cycle_time_min'],
            'avg_time_delta': (
                None if (r['avg_cycle_time_min'] is None or prev['avg_cycle_time_min'] is None)
                else round(r['avg_cycle_time_min'] - prev['avg_cycle_time_min'], 2)
            ),
        })

    # Single-period vs All-periods response
    if period != 'all':
        block_map = {'today': block_today, 'month': block_month, 'year': block_year}
        return {
            'factory_summary': factory_summary,
            'machine_stats': block_map.get(period, block_today),
            'period': period,
            'machine_filter': machine_filter,
            'sessions': session_rows
        }

    return {
        'factory_summary': factory_summary,
        'period': 'all',
        'machine_filter': machine_filter,
        'sessions': session_rows,
        'machine_stats_all': {
            'today': block_today,
            'month': block_month,
            'year': block_year,
            'last_year': block_lastyr,
            'compare_year_vs_last': compare
        }
    }
