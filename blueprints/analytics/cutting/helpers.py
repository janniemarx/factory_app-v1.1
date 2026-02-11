from datetime import datetime, timedelta
from models.cutting import WireCuttingSession, Machine
from models.operator import Operator

# ---------- Internal helpers ----------

def _active_minutes(session: WireCuttingSession):
    total = 0.0
    used_segments = False
    if getattr(session, "segments", None):
        for seg in session.segments:
            if seg.start_time and seg.end_time:
                total += (seg.end_time - seg.start_time).total_seconds() / 60.0
                used_segments = True
    if used_segments:
        return total
    if session.start_time and session.end_time:
        return (session.end_time - session.start_time).total_seconds() / 60.0
    return None


def _lengths_for_session(s: WireCuttingSession):
    """
    Returns (produced_m, waste_m, total_m) using recorded values if present,
    otherwise derives from profile specs and profiles_cut.
    """
    lpc = s.profile.length_per_cornice if s.profile else None
    cpb = s.profile.cornices_per_block if s.profile else None

    produced = s.produced_length_m
    if produced is None and lpc is not None and s.profiles_cut is not None:
        produced = (s.profiles_cut or 0) * (lpc or 0.0)

    waste = s.wastage_m
    if waste is None and lpc is not None and cpb is not None and produced is not None:
        theoretical = (cpb or 0) * (lpc or 0.0)
        derived = max(theoretical - produced, 0.0)
        waste = derived

    produced = float(produced) if produced is not None else 0.0
    waste = float(waste) if waste is not None else 0.0
    total = produced + waste
    return produced, waste, total


def _session_wastage_percent(s: WireCuttingSession):
    produced, waste, total = _lengths_for_session(s)
    return round(100.0 * waste / total, 2) if total > 0 else None


def _weighted_wastage_percent(sessions):
    numer = 0.0  # sum of waste
    denom = 0.0  # sum of total length
    for s in sessions:
        _, waste, total = _lengths_for_session(s)
        if total > 0:
            numer += waste
            denom += total
    return round(100.0 * numer / denom, 2) if denom > 0 else None


# ---------- Public API ----------

def get_cutting_analytics(machine_id=None, operator_id=None, profile_code=None, date_from=None, date_to=None):
    # Build filtered query
    query = WireCuttingSession.query
    if machine_id and int(machine_id) > 0:
        query = query.filter(WireCuttingSession.machine_id == int(machine_id))
    if operator_id and int(operator_id) > 0:
        query = query.filter(WireCuttingSession.operator_id == int(operator_id))
    if profile_code:
        query = query.filter(WireCuttingSession.profile_code == profile_code)

    if date_from:
        try:
            dt_from = datetime.strptime(date_from, "%Y-%m-%d")
            query = query.filter(WireCuttingSession.start_time >= dt_from)
        except Exception:
            pass
    if date_to:
        try:
            dt_to = datetime.strptime(date_to, "%Y-%m-%d") + timedelta(days=1)
            query = query.filter(WireCuttingSession.start_time < dt_to)
        except Exception:
            pass

    sessions = query.order_by(WireCuttingSession.start_time.desc()).all()

    # Only machines present in the filtered sessions
    machine_ids = {s.machine_id for s in sessions if s.machine_id is not None}
    machines = (Machine.query.filter(Machine.id.in_(machine_ids)).order_by(Machine.name).all()
                if machine_ids else [])

    # Per-machine stats (filtered set)
    machine_stats = []
    for m in machines:
        msessions = [s for s in sessions if s.machine_id == m.id]
        times = []
        for s in msessions:
            t = _active_minutes(s)
            if t is not None:
                times.append(t)
        avg_time = round(sum(times) / len(times), 2) if times else None
        fastest = round(min(times), 2) if times else None
        avg_waste = _weighted_wastage_percent(msessions)
        machine_stats.append({
            "id": m.id,
            "name": m.name,
            "blocks_cut": len(msessions),
            "avg_cut_time_min": avg_time,
            "fastest_cut_time_min": fastest,
            "avg_wastage_percent": avg_waste,
        })

    # Factory aggregates (filtered set)
    all_times = []
    for s in sessions:
        t = _active_minutes(s)
        if t is not None:
            all_times.append(t)

    avg_wastage_percent = _weighted_wastage_percent(sessions)
    individual_wastages = []
    for s in sessions:
        w = _session_wastage_percent(s)
        if w is not None:
            individual_wastages.append(w)
    lowest_wastage_percent = min(individual_wastages) if individual_wastages else None

    now = datetime.now()
    today = now.date()
    month = now.month
    year = now.year
    blocks_cut_total = len(sessions)
    blocks_cut_today = sum(1 for s in sessions if s.start_time and s.start_time.date() == today)
    blocks_cut_month = sum(1 for s in sessions if s.start_time and s.start_time.month == month and s.start_time.year == year)

    factory_averages = {
        "avg_cut_time_min": round(sum(all_times) / len(all_times), 2) if all_times else None,
        "fastest_cut_time_min": round(min(all_times), 2) if all_times else None,
        "avg_wastage_percent": avg_wastage_percent,
        "lowest_wastage_percent": lowest_wastage_percent,
        "blocks_cut_total": blocks_cut_total,      # total in filtered set
        "blocks_cut_today": blocks_cut_today,
        "blocks_cut_month": blocks_cut_month,
    }

    # Session table rows
    sessions_data = []
    for s in sessions:
        active_minutes = _active_minutes(s)
        w = _session_wastage_percent(s)  # uses derived lengths if needed
        sessions_data.append({
            "id": s.id,
            "machine_name": s.machine.name if s.machine else "",
            "profile_code": s.profile_code,
            "block_number": s.block.block_number if getattr(s, "block", None) else "",
            "operator": s.operator.full_name if s.operator else "",
            "profiles_cut": s.profiles_cut,
            "wastage_percent": w,  # computed
            "actual_cut_time": round(active_minutes, 2) if active_minutes is not None else None,
            "status": s.status,
        })

    return {
        "factory_averages": factory_averages,
        "machine_stats": machine_stats,
        "sessions": sessions_data,
    }


def get_machines():
    return Machine.query.order_by(Machine.name).all()


def get_operators():
    return Operator.query.order_by(Operator.full_name).all()
