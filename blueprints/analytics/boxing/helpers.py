from models.boxing import BoxingSession
from models.cutting import Profile
from models.moulded_boxing import MouldedBoxingSession, MOULDED_CORNICES_PER_BOX
from collections import defaultdict
from sqlalchemy import extract
from datetime import datetime
import os
import json

# --- Simple file-based benchmark store ---
BENCHMARK_PATH = 'boxing_benchmark.json'

def load_benchmark():
    if os.path.exists(BENCHMARK_PATH):
        with open(BENCHMARK_PATH, 'r') as f:
            return json.load(f)
    return {'benchmark_boxes_per_shift': 0, 'set_on': None}

def save_benchmark(benchmark, set_on=None):
    with open(BENCHMARK_PATH, 'w') as f:
        json.dump({'benchmark_boxes_per_shift': benchmark, 'set_on': set_on}, f)

def _safe_minutes(start, end):
    if not start or not end:
        return 0.0
    return max((end - start).total_seconds(), 0) / 60.0

def get_factory_averages_for_month():
    """
    Combined Cutting + Moulded averages (month-to-date).
    Expected boxes/shift uses combined boxes_per_minute * 480.
    """
    now = datetime.now()

    # CUTTING (existing)
    cutting_q = BoxingSession.query.filter(
        extract('year', BoxingSession.start_time) == now.year,
        extract('month', BoxingSession.start_time) == now.month
    )
    cutting_sessions = cutting_q.all()

    # MOULDED (new)
    moulded_q = MouldedBoxingSession.query.filter(
        extract('year', MouldedBoxingSession.start_time) == now.year,
        extract('month', MouldedBoxingSession.start_time) == now.month
    )
    moulded_sessions = moulded_q.all()

    if not cutting_sessions and not moulded_sessions:
        return {
            'avg_time_per_box': 0,
            'benchmark_boxes_per_shift': 0,
            'benchmark_set_on': None,
            'avg_boxes_per_operator': 0,
            'expected_boxes_per_shift': 0,
            'actual_boxes_today': 0,
            'avg_cornices_per_box': 0,
        }

    # Aggregate across both sources
    all_time_per_box_values = []
    boxes_by_operator = defaultdict(int)
    total_boxes = 0
    total_minutes = 0
    cornices_per_box_list = []
    today = now.date()
    boxes_today = 0

    # --- CUTTING loop (prefer unpaused minutes)
    for s in cutting_sessions:
        if not s.boxes_packed or not s.start_time or not s.end_time:
            continue

        profile = s.cutting_production.profile if (s.cutting_production and s.cutting_production.profile) else None
        cpb = profile.cornices_per_box if profile else 4
        cornices_per_box_list.append(cpb)

        total_boxes += (s.boxes_packed or 0)
        minutes = (s.actual_boxing_time_minutes()
                   if hasattr(s, "actual_boxing_time_minutes")
                   else _safe_minutes(s.start_time, s.end_time))
        total_minutes += minutes

        time_per_box = (s.time_per_box_min
                        or getattr(s, "time_per_box_calc", None)
                        or (minutes / max(s.boxes_packed, 1)))
        all_time_per_box_values.append(time_per_box)

        boxes_by_operator[s.operator_id] += (s.boxes_packed or 0)
        if s.start_time.date() == today:
            boxes_today += (s.boxes_packed or 0)

    # --- MOULDED loop (use session aggregates)
    for ms in moulded_sessions:
        session_boxes = ms.total_boxes or sum((i.boxes_packed or 0) for i in ms.items)
        if not session_boxes or not ms.start_time or not ms.end_time:
            continue

        # cpb: average by profile mix in this session (for display avg)
        per_profile = [MOULDED_CORNICES_PER_BOX.get(it.profile_code, 0) for it in ms.items]
        if per_profile:
            cornices_per_box_list.append(sum(per_profile) / len(per_profile))

        minutes = (ms.actual_boxing_minutes()
                   if hasattr(ms, "actual_boxing_minutes")
                   else _safe_minutes(ms.start_time, ms.end_time))
        total_minutes += minutes
        total_boxes += session_boxes

        time_per_box = ms.time_per_box_min or (minutes / max(session_boxes, 1))
        all_time_per_box_values.append(time_per_box)

        boxes_by_operator[ms.operator_id] += session_boxes
        if ms.start_time.date() == today:
            boxes_today += session_boxes

    boxes_per_minute = (total_boxes / total_minutes) if total_minutes else 0
    expected_boxes_per_shift = round(boxes_per_minute * 480, 2) if boxes_per_minute else 0
    avg_boxes_per_operator = round(sum(boxes_by_operator.values()) / (len(boxes_by_operator) or 1), 2)
    avg_cornices_per_box = round(sum(cornices_per_box_list) / len(cornices_per_box_list), 2) if cornices_per_box_list else 4
    avg_time_per_box = round(sum(all_time_per_box_values) / len(all_time_per_box_values), 2) if all_time_per_box_values else 0

    # Benchmark update (persisted record)
    benchmark_info = load_benchmark()
    prev_benchmark = benchmark_info.get('benchmark_boxes_per_shift', 0)
    prev_set_on = benchmark_info.get('set_on', None)
    benchmark_boxes_per_shift = prev_benchmark
    benchmark_set_on = prev_set_on
    if expected_boxes_per_shift > prev_benchmark:
        benchmark_boxes_per_shift = expected_boxes_per_shift
        benchmark_set_on = now.strftime("%Y-%m-%d")
        save_benchmark(benchmark_boxes_per_shift, benchmark_set_on)

    return {
        'avg_time_per_box': avg_time_per_box,
        'benchmark_boxes_per_shift': benchmark_boxes_per_shift,
        'benchmark_set_on': benchmark_set_on,
        'avg_boxes_per_operator': avg_boxes_per_operator,
        'expected_boxes_per_shift': expected_boxes_per_shift,
        'actual_boxes_today': boxes_today,
        'avg_cornices_per_box': avg_cornices_per_box,
    }

def get_boxing_analytics(operator_id=None, date_from=None, date_to=None, period="all"):
    """
    Combined analytics for Cutting (BoxingSession) + Moulded (MouldedBoxingSession),
    normalized to your existing table schema.
    """
    # ---- CUTTING base query
    cq = BoxingSession.query
    if operator_id and int(operator_id) > 0:
        cq = cq.filter(BoxingSession.operator_id == int(operator_id))
    if date_from:
        cq = cq.filter(BoxingSession.start_time >= date_from)
    if date_to:
        cq = cq.filter(BoxingSession.end_time <= date_to)
    cutting_sessions = cq.order_by(BoxingSession.start_time.asc()).all()

    # ---- MOULDED base query
    mq = MouldedBoxingSession.query
    if operator_id and int(operator_id) > 0:
        mq = mq.filter(MouldedBoxingSession.operator_id == int(operator_id))
    if date_from:
        mq = mq.filter(MouldedBoxingSession.start_time >= date_from)
    if date_to:
        mq = mq.filter(MouldedBoxingSession.end_time <= date_to)
    moulded_sessions = mq.order_by(MouldedBoxingSession.start_time.asc()).all()

    if not cutting_sessions and not moulded_sessions:
        return {
            'sessions': [],
            'avg_time_per_box': 0,
            'benchmark_time': 0,
            'avg_boxes_per_group': 0,
            'group_totals': {},
            'group_labels': [],
            'all_time_per_box': [],
            'period': period,
            'profile_stats': {},
            'factory_averages': get_factory_averages_for_month(),
        }

    sessions_data = []
    all_time_per_box = []
    fastest_time = None
    group_totals = {}
    group_labels = []

    # Per-profile stats (combined)
    profile_times = defaultdict(list)
    profile_fastest = {}
    profile_codes = set()

    def group_key(dt):
        if not dt:
            return "All"
        if period == 'day':
            return dt.strftime('%Y-%m-%d')
        elif period == 'month':
            return dt.strftime('%Y-%m')
        else:
            return "All"

    # -------- CUTTING rows
    for s in cutting_sessions:
        if not s.boxes_packed or not s.end_time or not s.start_time:
            continue

        profile_code = s.cutting_production.profile_code if s.cutting_production else "Unknown"
        profile = s.cutting_production.profile if (s.cutting_production and s.cutting_production.profile) else None
        cornices_per_box = profile.cornices_per_box if profile else 4
        cornices_packed = (s.boxes_packed or 0) * cornices_per_box + (s.leftovers or 0)

        minutes = (s.actual_boxing_time_minutes()
                   if hasattr(s, "actual_boxing_time_minutes")
                   else _safe_minutes(s.start_time, s.end_time))
        time_per_box = (s.time_per_box_min
                        or getattr(s, "time_per_box_calc", None)
                        or (minutes / max(s.boxes_packed, 1)))
        all_time_per_box.append(time_per_box)
        profile_times[profile_code].append(time_per_box)
        if profile_code not in profile_fastest or (time_per_box and time_per_box < profile_fastest[profile_code]):
            profile_fastest[profile_code] = time_per_box
        if fastest_time is None or (time_per_box and time_per_box < fastest_time):
            fastest_time = time_per_box

        # Damage = total boxed cornices - good (positive == damage)
        damage = 0
        if s.qc:
            total_boxed_cornices = (s.boxes_packed or 0) * cornices_per_box + (s.leftovers or 0)
            good = (s.qc.good_cornices_count or 0)
            damage = max(0, total_boxed_cornices - good)

        key = group_key(s.start_time)
        group_totals.setdefault(key, 0)
        group_totals[key] += (s.boxes_packed or 0)
        if key not in group_labels:
            group_labels.append(key)

        expected_machine_cycles = cornices_packed / 4 if cornices_packed else 0
        actual_machine_cycles = (s.cycle_end - s.cycle_start) if (s.cycle_end is not None and s.cycle_start is not None) else None
        damage_rate = (damage / cornices_packed * 100) if cornices_packed else 0

        sessions_data.append({
            'id': s.id,
            'id_display': f"C-{s.id}",
            'source': 'cutting',
            'profile_code': profile_code,
            'block_number': s.cutting_production.block_number if s.cutting_production else None,
            'operator': getattr(s.operator, "full_name", "-"),
            'boxes_packed': s.boxes_packed,
            'cornices_packed': cornices_packed,
            'time_per_box': round(time_per_box, 2) if time_per_box else 0,
            'producing_cycles': s.producing_cycles,
            'actual_producing_cycles': s.actual_producing_cycles,
            'expected_machine_cycles': round(expected_machine_cycles, 2),
            'actual_machine_cycles': actual_machine_cycles,
            'damage': int(damage),
            'damage_rate': round(damage_rate, 2),
            'date': s.start_time.date() if s.start_time else None,
            'start_time': s.start_time,
            'end_time': s.end_time,
            'status': s.status,
            'profile_avg_time': None,
            'profile_benchmark': None,
        })

    # -------- MOULDED rows (expanded per profile)
    for ms in moulded_sessions:
        boxed_map = ms.boxed_by_profile() if hasattr(ms, "boxed_by_profile") else {}
        produced_map = ms.produced_by_profile() if hasattr(ms, "produced_by_profile") else {}
        if not boxed_map:
            continue

        minutes = (ms.actual_boxing_minutes()
                   if hasattr(ms, "actual_boxing_minutes")
                   else _safe_minutes(ms.start_time, ms.end_time))
        session_boxes = ms.total_boxes or sum((i.boxes_packed or 0) for i in ms.items)
        time_per_box = (ms.time_per_box_min if ms.time_per_box_min is not None
                        else (minutes / max(session_boxes, 1))) if session_boxes else None
        if time_per_box is not None:
            all_time_per_box.append(time_per_box)
            if (fastest_time is None) or (time_per_box < fastest_time):
                fastest_time = time_per_box

        for profile_code, boxed_cornices in boxed_map.items():
            profile_codes.add(profile_code)
            profile_times[profile_code].append(time_per_box or 0)

            cpb = MOULDED_CORNICES_PER_BOX.get(profile_code, 0)
            boxes_packed = int(boxed_cornices // cpb) if cpb else 0

            produced_qty = produced_map.get(profile_code, 0)
            # Damage = produced - boxed (positive == loss)
            est_damage = max(0, produced_qty - boxed_cornices) if produced_qty else 0

            key = group_key(ms.start_time)
            group_totals.setdefault(key, 0)
            group_totals[key] += boxes_packed
            if key not in group_labels:
                group_labels.append(key)

            sessions_data.append({
                'id': ms.id,
                'id_display': f"M-{ms.id}",
                'source': 'moulded',
                'profile_code': profile_code,
                'block_number': None,
                'operator': getattr(ms.operator, "full_name", "-") if getattr(ms, "operator", None) else "-",
                'boxes_packed': boxes_packed,
                'cornices_packed': boxed_cornices,
                'time_per_box': round(time_per_box, 2) if time_per_box else 0,
                'producing_cycles': None,
                'actual_producing_cycles': None,
                'expected_machine_cycles': round((boxed_cornices / 4), 2) if boxed_cornices else 0,
                'actual_machine_cycles': None,
                'damage': int(est_damage),
                'damage_rate': round((est_damage / boxed_cornices * 100), 2) if boxed_cornices else 0,
                'date': ms.start_time.date() if ms.start_time else None,
                'start_time': ms.start_time,
                'end_time': ms.end_time,
                'status': ms.status,
                'profile_avg_time': None,
                'profile_benchmark': None,
            })

    # Per-profile averages/benchmarks across both sources
    profile_stats = {}
    for code, times in profile_times.items():
        times = [t for t in times if t]
        if not times:
            continue
        profile_stats[code] = {
            'profile_code': code,
            'avg_time': round(sum(times) / len(times), 2),
            'benchmark': min(times)
        }

    for s in sessions_data:
        code = s['profile_code']
        s['profile_avg_time'] = profile_stats.get(code, {}).get('avg_time', 0)
        s['profile_benchmark'] = profile_stats.get(code, {}).get('benchmark', 0)

    avg_time_per_box = round(sum(all_time_per_box) / len(all_time_per_box), 2) if all_time_per_box else 0
    avg_boxes_per_group = round(sum(group_totals.values()) / (len(group_totals) or 1), 2) if group_totals else 0

    # Sort sessions (oldest first)
    sessions_data.sort(key=lambda r: (r['start_time'] or datetime.min))

    return {
        'sessions': sessions_data,
        'avg_time_per_box': avg_time_per_box,
        'benchmark_time': fastest_time or 0,
        'avg_boxes_per_group': avg_boxes_per_group,
        'group_totals': group_totals,
        'group_labels': group_labels,
        'all_time_per_box': all_time_per_box,
        'period': period,
        'profile_stats': profile_stats,
        'factory_averages': get_factory_averages_for_month(),
    }
