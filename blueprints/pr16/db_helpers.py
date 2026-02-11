from models import db
from models import CuttingProductionRecord
from models.cutting import Profile
from models.pr16_session import (
    PR16Session, PR16ResourceUsage, PR16WrappingProduction, PR16TrimmingLog,
    PR16QualityCheck
)
from sqlalchemy.exc import SQLAlchemyError
from datetime import datetime, timedelta
import math

PAPER_ROLL_M = 300.0
GLUE_DRUM_KG = 50.0
PR16_DENSITY = 18  # enforce PR16 from 18 density blocks


def safe_commit():
    try:
        db.session.commit()
        return True, None
    except SQLAlchemyError as e:
        db.session.rollback()
        return False, str(e)


def _paper_per_cornice_m(profile_code: str = 'PR16') -> float:
    prof = Profile.query.filter_by(code=profile_code).first()
    return float(prof.length_per_cornice if prof and prof.length_per_cornice else 2.5)


def get_pr16_blocks_ready():
    """Return blocks that were cut as PR16 (and not boxable yet), not already used by a PR16 session,
    and whose pre-expansion density is 18."""
    from models.block import Block
    from models.pre_expansion import PreExpansion

    q = (
        db.session.query(Block)
        .join(CuttingProductionRecord, CuttingProductionRecord.block_id == Block.id)
        .outerjoin(PreExpansion, PreExpansion.id == Block.pre_expansion_id)
        .filter(CuttingProductionRecord.profile_code == 'PR16')
        .filter(CuttingProductionRecord.is_boxable == False)
        .filter(~Block.id.in_(db.session.query(PR16Session.block_id)))
    )
    # Enforce 18 density
    q = q.filter(PreExpansion.density == PR16_DENSITY)
    return q.all()


def add_paper_usage(session_id: int, meters: float, when: datetime | None = None):
    try:
        usage = PR16ResourceUsage(
            session_id=session_id,
            resource_type="paper",
            amount=float(meters),
            timestamp=when or datetime.utcnow()
        )
        db.session.add(usage)
        return safe_commit()
    except Exception as e:
        db.session.rollback()
        return False, str(e)


def start_pr16_session(block_id, operator_id, glue_kg, paper_m, start_partial_fraction: float = 0.0):
    try:
        session = PR16Session(
            block_id=block_id,
            operator_id=operator_id,
            started_at=datetime.utcnow(),
            status='active',
            is_paused=False,
            total_wrapping_paused_seconds=0
        )
        db.session.add(session)
        db.session.flush()

        total_paper_m = float(paper_m or 0.0) + (float(start_partial_fraction or 0.0) * PAPER_ROLL_M)

        if glue_kg and glue_kg > 0:
            db.session.add(PR16ResourceUsage(session_id=session.id, resource_type="glue", amount=glue_kg))

        if total_paper_m and total_paper_m > 0:
            db.session.add(PR16ResourceUsage(session_id=session.id, resource_type="paper", amount=total_paper_m))

        success, error = safe_commit()
        return (session if success else None), error
    except Exception as e:
        db.session.rollback()
        return None, str(e)


def add_resource_usage(session_id, glue_kg, paper_m):
    try:
        now = datetime.utcnow()
        rows = []
        if glue_kg and glue_kg > 0:
            rows.append(PR16ResourceUsage(session_id=session_id, resource_type="glue", amount=glue_kg, timestamp=now))
        if paper_m and paper_m > 0:
            rows.append(PR16ResourceUsage(session_id=session_id, resource_type="paper", amount=paper_m, timestamp=now))
        if rows:
            db.session.add_all(rows)
        return safe_commit()
    except Exception as e:
        db.session.rollback()
        return False, str(e)


def pause_wrapping(session: PR16Session):
    if session.status != 'active' or session.is_paused:
        return True, None
    session.is_paused = True
    session.pause_start = datetime.utcnow()
    return safe_commit()


def resume_wrapping(session: PR16Session):
    if session.status != 'active' or not session.is_paused:
        return True, None
    now = datetime.utcnow()
    if session.pause_start:
        session.total_wrapping_paused_seconds = int(session.total_wrapping_paused_seconds or 0) + int((now - session.pause_start).total_seconds())
    session.pause_start = None
    session.is_paused = False
    return safe_commit()


def log_wrapping(session_id, qty):
    try:
        wrap = PR16WrappingProduction(session_id=session_id, cornices_wrapped=qty, logged_at=datetime.utcnow())
        db.session.add(wrap)
        db.session.flush()
        total_wrapped = db.session.query(db.func.coalesce(db.func.sum(PR16WrappingProduction.cornices_wrapped), 0))\
            .filter_by(session_id=session_id).scalar()
        session = PR16Session.query.get(session_id)
        session.wrapped_cornices = int(total_wrapped or 0)
        return safe_commit()
    except Exception as e:
        db.session.rollback()
        return False, str(e)


def _compute_resource_totals(session: PR16Session):
    glue = db.session.query(db.func.coalesce(db.func.sum(PR16ResourceUsage.amount), 0.0)) \
        .filter_by(session_id=session.id, resource_type='glue').scalar() or 0.0

    paper_sum = db.session.query(db.func.coalesce(db.func.sum(PR16ResourceUsage.amount), 0.0)) \
        .filter_by(session_id=session.id, resource_type='paper').scalar() or 0.0
    paper = max(float(paper_sum), 0.0)  # clamp to avoid negative
    return float(glue), float(paper)


def _cutting_cornices(session: PR16Session) -> int:
    rec = CuttingProductionRecord.query.filter_by(block_id=session.block_id, profile_code='PR16') \
        .order_by(CuttingProductionRecord.id.desc()).first()
    return int(rec.cornices_produced if rec and rec.cornices_produced else 0)


def _compute_durations_minutes(session: PR16Session):
    def _mins(a, b):
        if a and b:
            return round((b - a).total_seconds() / 60.0, 2)
        return None

    wrap_min_raw = _mins(session.started_at, session.wrapping_end)
    if wrap_min_raw is not None:
        paused_min = round((session.total_wrapping_paused_seconds or 0) / 60.0, 2)
        wrap_min = max(wrap_min_raw - paused_min, 0.0)
    else:
        wrap_min = None

    dry_min = _mins(session.drying_start, session.drying_end)

    # NEW: trimming subtracts paused time
    trim_min_raw = _mins(session.trimming_start, session.trimming_end)
    if trim_min_raw is not None:
        paused_trim_min = round((session.total_trimming_paused_seconds or 0) / 60.0, 2)
        trim_min = max(trim_min_raw - paused_trim_min, 0.0)
    else:
        trim_min = None

    return wrap_min, dry_min, trim_min

def recompute_session_metrics(session: PR16Session):
    glue_kg, paper_m = _compute_resource_totals(session)
    paper_pc = _paper_per_cornice_m('PR16')

    wrapped = int(session.wrapped_cornices or 0)
    trimmed = int(session.trimmed_cornices or 0)
    cut_qty = _cutting_cornices(session)

    wrapping_damage = max(cut_qty - wrapped, 0)
    trimming_damage = max(wrapped - trimmed, 0)
    total_damage = wrapping_damage + trimming_damage

    expected_paper_m = float(trimmed * paper_pc)
    paper_loss_m = max(paper_m - expected_paper_m, 0.0)

    wrap_min, dry_min, trim_min = _compute_durations_minutes(session)

    session.glue_used_kg = round(glue_kg, 3)
    session.paper_used_m = round(paper_m, 3)
    session.glue_drums_used = int(math.ceil(glue_kg / GLUE_DRUM_KG)) if glue_kg else 0
    session.paper_rolls_used = int(math.ceil(paper_m / PAPER_ROLL_M)) if paper_m else 0

    session.wrapping_damage = wrapping_damage
    session.trimming_damage = trimming_damage
    session.total_damage = total_damage

    session.expected_paper_m = round(expected_paper_m, 3)
    session.paper_loss_m = round(paper_loss_m, 3)

    session.wrapping_duration_min = wrap_min
    session.drying_duration_min = dry_min
    session.trimming_duration_min = trim_min

    return safe_commit()


def complete_wrapping(session: PR16Session, end_partial_fraction: float):
    """Finish wrapping ONLY if all cut cornices are wrapped. Subtract leftover partial roll,
       then move to drying."""
    if session.status != 'active':
        return False, "Wrapping is not active."

    # Enforce pause off before closing
    if session.is_paused:
        ok, err = resume_wrapping(session)
        if not ok:
            return False, err

    # Validate totals
    cut_qty = _cutting_cornices(session)
    wrapped = int(session.wrapped_cornices or 0)
    if wrapped < cut_qty:
        return False, f"Cannot complete: {cut_qty - wrapped} cornices still unwrapped."

    # Log leftover negative paper if any
    if end_partial_fraction and end_partial_fraction > 0:
        neg_m = - float(end_partial_fraction) * PAPER_ROLL_M
        ok, err = add_paper_usage(session.id, neg_m)
        if not ok:
            return False, err

    # Transition to drying
    now = datetime.utcnow()
    session.wrapping_end = now
    session.drying_start = now
    session.status = 'in_drying'

    ok, err = safe_commit()
    if not ok:
        return False, err

    # Recompute metrics after wrapping is closed
    return recompute_session_metrics(session)


def complete_drying(session: PR16Session):
    session.status = 'trimming'
    session.drying_end = datetime.utcnow()
    session.trimming_start = session.drying_end
    return safe_commit()


def log_trimming(session_id, trimming_start, trimming_end, cornices_trimmed):
    try:
        trim = PR16TrimmingLog(
            session_id=session_id,
            trimming_start=trimming_start or datetime.utcnow(),
            trimming_end=trimming_end or datetime.utcnow(),
            cornices_trimmed=cornices_trimmed
        )
        db.session.add(trim)
        db.session.flush()

        session = PR16Session.query.get(session_id)
        total_trimmed = db.session.query(db.func.coalesce(db.func.sum(PR16TrimmingLog.cornices_trimmed), 0)) \
            .filter_by(session_id=session_id).scalar()
        session.trimmed_cornices = int(total_trimmed or 0)
        session.trimming_end = trim.trimming_end
        session.status = 'awaiting_qc'
        session.completed_at = datetime.utcnow()

        ok, err = safe_commit()
        if not ok:
            return False, err

        ok2, err2 = recompute_session_metrics(session)
        if not ok2:
            return False, err2

        rec = CuttingProductionRecord.query.filter_by(block_id=session.block_id, profile_code='PR16') \
            .order_by(CuttingProductionRecord.id.desc()).first()
        if rec:
            rec.is_boxable = False
            rec.qc_status = 'pr16_qc_pending'
            return safe_commit()
        return True, None
    except Exception as e:
        db.session.rollback()
        return False, str(e)


def mark_qc(session_id: int, qc_operator_id: int, passed: bool, notes: str = None):
    try:
        session = PR16Session.query.get(session_id)
        if not session:
            return False, 'PR16 session not found.'

        qc = PR16QualityCheck(session_id=session_id, qc_operator_id=qc_operator_id, passed=bool(passed), notes=notes)
        db.session.add(qc)

        rec = CuttingProductionRecord.query.filter_by(block_id=session.block_id, profile_code='PR16') \
            .order_by(CuttingProductionRecord.id.desc()).first()
        if rec:
            rec.is_boxable = bool(passed)
            rec.qc_status = 'passed' if passed else 'failed'

        session.status = 'qc_passed' if passed else 'qc_failed'
        ok, err = safe_commit()
        if not ok:
            return False, err

        return recompute_session_metrics(session)
    except Exception as e:
        db.session.rollback()
        return False, str(e)


def cancel_session(session: PR16Session):
    try:
        db.session.delete(session)
        return safe_commit()
    except Exception as e:
        db.session.rollback()
        return False, str(e)

def pause_trimming(session: PR16Session):
    if session.status != 'trimming' or session.is_trim_paused:
        return True, None
    session.is_trim_paused = True
    session.trim_pause_start = datetime.utcnow()
    return safe_commit()

def resume_trimming(session: PR16Session):
    if session.status != 'trimming' or not session.is_trim_paused:
        return True, None
    now = datetime.utcnow()
    if session.trim_pause_start:
        session.total_trimming_paused_seconds = int(session.total_trimming_paused_seconds or 0) + \
            int((now - session.trim_pause_start).total_seconds())
    session.trim_pause_start = None
    session.is_trim_paused = False
    return safe_commit()