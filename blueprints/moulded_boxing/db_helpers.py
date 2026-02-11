from datetime import datetime
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import func
from models import db
from models.moulded_cornice import MouldedCorniceSession
from models.moulded_boxing import (
    MouldedBoxingSession,
    MouldedBoxedItem,
    MouldedBoxingQualityControl,
    MOULDED_CORNICES_PER_BOX,
)

def safe_commit():
    try:
        db.session.commit()
        return True, None
    except SQLAlchemyError as e:
        db.session.rollback()
        return False, str(e)

# ---------- Produced / Boxed helpers ----------

def produced_target_by_profile(moulded_session: MouldedCorniceSession) -> dict[str, int]:
    """Authoritative produced totals from production_summaries."""
    return {ps.profile_code: int(ps.quantity or 0) for ps in moulded_session.production_summaries}

def boxed_so_far_by_profile(moulded_session_id: int) -> dict[str, int]:
    """
    Sum boxed cornices across ALL boxing sessions for the given moulded session.
    """
    rows = (
        db.session.query(
            MouldedBoxedItem.profile_code,
            func.coalesce(func.sum(MouldedBoxedItem.boxes_packed), 0).label("boxes"),
            func.coalesce(func.sum(MouldedBoxedItem.leftovers), 0).label("leftovers"),
        )
        .join(MouldedBoxingSession, MouldedBoxedItem.session_id == MouldedBoxingSession.id)
        .filter(MouldedBoxingSession.moulded_session_id == moulded_session_id)
        .group_by(MouldedBoxedItem.profile_code)
        .all()
    )
    out = {}
    for code, boxes, leftovers in rows:
        per_box = MOULDED_CORNICES_PER_BOX.get(code, 0)
        out[code] = int(boxes or 0) * per_box + int(leftovers or 0)
    return out

def list_completed_unboxed_sessions():
    """
    Moulded sessions that are completed AND still have remaining quantity to box.
    """
    sessions = (
        MouldedCorniceSession.query
        .filter(MouldedCorniceSession.status == 'completed')
        .order_by(MouldedCorniceSession.end_time.desc())
        .all()
    )
    result = []
    for s in sessions:
        produced = produced_target_by_profile(s)
        boxed = boxed_so_far_by_profile(s.id)
        if any((produced.get(p, 0) - boxed.get(p, 0)) > 0 for p in produced):
            result.append(s)
    return result

# ---------- Session lifecycle ----------

def create_or_get_active_boxing_session(moulded_session_id: int, operator_id: int):
    """
    Return an active/paused boxing session for this moulded session or create a new one.
    """
    sess = (
        MouldedBoxingSession.query
        .filter(MouldedBoxingSession.moulded_session_id == moulded_session_id)
        .filter(MouldedBoxingSession.status.in_(["active", "paused"]))
        .order_by(MouldedBoxingSession.start_time.desc())
        .first()
    )
    if sess:
        return sess, None

    sess = MouldedBoxingSession(
        moulded_session_id=moulded_session_id,
        operator_id=operator_id,
        start_time=datetime.utcnow(),
        status='active',
    )
    db.session.add(sess)
    ok, err = safe_commit()
    return (sess if ok else None), err

def pause_session(session: MouldedBoxingSession):
    if session.is_paused:
        return True, None
    session.is_paused = True
    session.pause_start = datetime.utcnow()
    session.status = 'paused'
    return safe_commit()

def resume_session(session: MouldedBoxingSession):
    if not session.is_paused:
        return True, None
    delta = (datetime.utcnow() - session.pause_start).total_seconds()
    session.total_paused_seconds += int(max(delta, 0))
    session.is_paused = False
    session.pause_start = None
    session.status = 'active'
    return safe_commit()

def add_item_save(boxing_session_id: int, profile_code: str, boxes: int, leftovers: int):
    """
    Append a partial save (does not overwrite). We aggregate on read.
    """
    item = MouldedBoxedItem(
        session_id=boxing_session_id,
        profile_code=profile_code,
        boxes_packed=int(boxes or 0),
        leftovers=int(leftovers or 0),
    )
    db.session.add(item)
    return safe_commit()

def finish_boxing_if_complete(session: MouldedBoxingSession):
    """
    If all profiles from the moulded production are fully boxed, finish (pending_qc).
    """
    produced = produced_target_by_profile(session.moulded_session)
    boxed = boxed_so_far_by_profile(session.moulded_session_id)
    remaining = sum(max(produced.get(k, 0) - boxed.get(k, 0), 0) for k in produced)

    if remaining <= 0:
        session.end_time = datetime.utcnow()
        session.status = 'pending_qc'
        session.recompute_totals()
        return safe_commit()
    return True, None

def force_finish_boxing(session: MouldedBoxingSession):
    """Manual finish button."""
    session.end_time = datetime.utcnow()
    session.status = 'pending_qc'
    session.recompute_totals()
    return safe_commit()

def perform_qc(session: MouldedBoxingSession, qc_operator_id: int,
               boxes_checked: int, good_cornices_count: int,
               notes: str, actions: str):
    qc = MouldedBoxingQualityControl(
        session_id=session.id,
        qc_operator_id=qc_operator_id,
        boxes_checked=int(boxes_checked or 0),
        good_cornices_count=int(good_cornices_count or 0),
        notes=notes or None,
        actions_taken=actions or None,
        is_stock_ready=True,
        timestamp=datetime.utcnow(),
    )
    session.status = 'stock_ready'
    db.session.add(qc)
    return safe_commit()

def list_boxing_sessions():
    return (
        MouldedBoxingSession.query
        .order_by(MouldedBoxingSession.start_time.desc())
        .all()
    )
