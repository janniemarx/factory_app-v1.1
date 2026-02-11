from models.pre_expansion import PreExpansion
from models.block import Block, BlockSession
from models import db
from datetime import datetime, date, timedelta

def get_unutilized_pre_expansions():
    """Pre-expansions (for blocks) with no blocks made yet, show curing days."""
    pre_exps = (
        PreExpansion.query
        .filter_by(purpose='Block', status='completed', is_used=False)
        .all()
    )
    data = []
    for pe in pre_exps:
        session = BlockSession.query.filter_by(pre_expansion_id=pe.id).first()
        blocks = Block.query.filter_by(pre_expansion_id=pe.id).count()
        curing_days = (datetime.utcnow().date() - pe.end_time.date()).days if pe.end_time else None
        density = int(pe.density)
        max_cure = 3 if density == 18 else 10
        data.append({
            'batch_no': pe.batch_no,
            'density': pe.density,
            'planned_kg': pe.planned_kg,
            'end_time': pe.end_time,
            'curing_days': curing_days,
            'max_cure': max_cure,
            'blocks': blocks,
            'overdue': curing_days is not None and curing_days > max_cure,
            'curing_status': (
                "Overdue" if curing_days and curing_days > max_cure else
                "Ready" if curing_days and curing_days >= max_cure else
                "Curing"
            ),
        })
    return data

def get_block_stats(period='today'):
    now = datetime.utcnow()
    if period == 'today':
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == 'this_week':
        start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == 'this_month':
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        start = None  # All time

    query = Block.query
    if start:
        query = query.filter(Block.created_at >= start)
    blocks = query.all()
    total_blocks = len(blocks)
    total_weight = sum(b.weight for b in blocks)
    avg_weight = round(total_weight / total_blocks, 2) if total_blocks else 0
    heaviest = max(blocks, key=lambda b: b.weight, default=None)
    lightest = min(blocks, key=lambda b: b.weight, default=None)
    return {
        "total_blocks": total_blocks,
        "total_weight": total_weight,
        "avg_weight": avg_weight,
        "heaviest": heaviest.weight if heaviest else None,
        "lightest": lightest.weight if lightest else None,
        "period": period,
    }

def get_pre_expansion_usage():
    """Show how many blocks were made from each pre-expansion batch."""
    result = []
    pre_exps = (
        PreExpansion.query
        .filter_by(purpose='Block')
        .all()
    )
    for pe in pre_exps:
        block_count = Block.query.filter_by(pre_expansion_id=pe.id).count()
        session = BlockSession.query.filter_by(pre_expansion_id=pe.id).first()
        first_block = Block.query.filter_by(pre_expansion_id=pe.id).order_by(Block.created_at.asc()).first()
        time_to_first_block = (first_block.created_at - pe.end_time).total_seconds() / 3600 if (first_block and pe.end_time) else None
        result.append({
            "batch_no": pe.batch_no,
            "density": pe.density,
            "planned_kg": pe.planned_kg,
            "end_time": pe.end_time,
            "block_count": block_count,
            "session_started": session.started_at if session else None,
            "time_to_first_block_hr": round(time_to_first_block, 2) if time_to_first_block else None
        })
    return result

def get_inactive_sessions(hours=2):
    """Block sessions started but no blocks added in the last X hours."""
    now = datetime.utcnow()
    inactive = []
    sessions = BlockSession.query.filter_by(status='active').all()
    for s in sessions:
        blocks = Block.query.filter_by(block_session_id=s.id).order_by(Block.created_at.desc()).all()
        if blocks:
            last_block_time = blocks[-1].created_at
        else:
            last_block_time = s.started_at
        idle_hours = (now - last_block_time).total_seconds() / 3600
        if idle_hours > hours:
            inactive.append({
                "session_id": s.id,
                "started_at": s.started_at,
                "last_block_time": last_block_time,
                "idle_hours": round(idle_hours, 2),
                "operator": s.operator.full_name if s.operator else None,
                "pre_expansion_batch": s.pre_expansion.batch_no if s.pre_expansion else None
            })
    return inactive

def get_dashboard_stats():
    pre_exp_today = PreExpansion.query.filter(
        PreExpansion.status == 'completed',
        db.func.date(PreExpansion.end_time) == date.today()
    ).count()
    block_sessions_today = BlockSession.query.filter(
        db.func.date(BlockSession.started_at) == date.today()
    ).count()
    unused_pre_exp = PreExpansion.query.filter_by(status='completed', is_used=False, purpose='Block').count()
    total_blocks = Block.query.count()
    blocks_waiting_to_cut = Block.query.filter_by(is_cut=False).count()
    avg_curing_time = _get_avg_curing_time()
    return {
        "pre_exp_today": pre_exp_today,
        "block_sessions_today": block_sessions_today,
        "unused_pre_exp": unused_pre_exp,
        "total_blocks": total_blocks,
        "blocks_waiting_to_cut": blocks_waiting_to_cut,
        "avg_curing_time": avg_curing_time,
    }

def _get_avg_curing_time():
    blocks = Block.query.filter(Block.curing_end != None).all()
    if not blocks:
        return None
    curing_durations = [(b.curing_end - b.created_at).total_seconds() / 3600 for b in blocks if b.created_at and b.curing_end]
    if not curing_durations:
        return None
    avg_hr = sum(curing_durations) / len(curing_durations)
    return round(avg_hr, 2)

def get_blocks_not_cut():
    blocks = Block.query.filter_by(is_cut=False).all()
    result = []
    for block in blocks:
        curing_days = (datetime.utcnow().date() - block.created_at.date()).days if block.created_at else None
        result.append({
            'block_number': block.block_number,
            'created_at': block.created_at,
            'curing_days': curing_days,
            'curing_end': block.curing_end,
            'pre_expansion_batch': block.pre_expansion.batch_no if block.pre_expansion else None,
            'density': block.pre_expansion.density if block.pre_expansion else None,
        })
    return result

def get_top_batches_by_block_count(limit=5):
    """Top batches by number of blocks produced."""
    rows = (
        db.session.query(
            PreExpansion.batch_no,
            db.func.count(Block.id).label("block_count")
        )
        .join(Block, Block.pre_expansion_id == PreExpansion.id)
        .group_by(PreExpansion.id)
        .order_by(db.desc("block_count"))
        .limit(limit)
        .all()
    )
    return [{"batch_no": r[0], "block_count": r[1]} for r in rows]
