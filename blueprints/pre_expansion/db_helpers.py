from models.pre_expansion import PreExpansion, DensityCheck, PreExpansionChecklistEvent, PreExpansionChecklist
from models import db
from datetime import datetime, date, timedelta
import math
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError

def safe_commit():
    try:
        db.session.commit()
        return True, None
    except SQLAlchemyError as e:
        db.session.rollback()
        return False, str(e)


def generate_batch_no(pre_exp_date, density, purpose):
    # pre_exp_date is a date (today)
    date_str = pre_exp_date.strftime('%Y%m%d')
    density_str = str(int(density)).replace('.', '')
    same_batches = PreExpansion.query.filter(
        PreExpansion.pre_exp_date == pre_exp_date,
        PreExpansion.density == density,
        PreExpansion.purpose == purpose
    ).count()
    next_batch_num = same_batches + 1
    return f"{date_str}-{density_str}-{purpose} {next_batch_num}"

def create_pre_expansion(form, operator_id, batch_no):
    pre_exp = PreExpansion(
        batch_no=batch_no,
        pre_exp_date=date.today(),                # 👈 set by system
        density=form.density.data,
        planned_kg=form.planned_kg.data,
        purpose=form.purpose.data,
        operator_id=operator_id,
        material_code=form.material_type.data,
        status='active',
        start_time=datetime.utcnow()
    )
    db.session.add(pre_exp)
    success, error = safe_commit()
    return pre_exp if success else None, error

def link_checklist_to_session(checklist_id, pre_exp_id):
    checklist = PreExpansionChecklist.query.get(checklist_id)
    if not checklist:
        return False, "Checklist not found."
    checklist.pre_expansion_id = pre_exp_id
    success, error = safe_commit()
    if not success:
        return False, f"Database error: {error}"
    return True, None

def add_density_check(pre_exp_id, form, operator_id):
    check = DensityCheck(
        pre_expansion_id=pre_exp_id,
        measured_density=form.measured_density.data,
        measured_weight=form.measured_weight.data,
        operator_id=operator_id
    )
    db.session.add(check)
    success, error = safe_commit()
    return check if success else None, error

def get_active_sessions():
    try:
        return PreExpansion.query.filter_by(status='active').order_by(PreExpansion.start_time.desc()).all(), None
    except SQLAlchemyError as e:
        return [], str(e)

def get_completed_sessions():
    try:
        return PreExpansion.query.filter_by(status='completed').order_by(PreExpansion.end_time.desc()).all(), None
    except SQLAlchemyError as e:
        return [], str(e)

def add_checklist(form, operator):
    checklist = PreExpansionChecklist(
        completed_by=operator.full_name or operator.username,
        check1=form.check1.data,
        check2=form.check2.data,
        check3=form.check3.data,
        check4=form.check4.data,
        check5=form.check5.data,
        check6=form.check6.data,
        check7=form.check7.data,
        check8=form.check8.data,
        check9=form.check9.data,
        check10=form.check10.data,
        check11=form.check11.data,
        check12=form.check12.data,
        check13=form.check13.data
    )
    db.session.add(checklist)
    success, error = safe_commit()
    return checklist if success else None, error

def get_dashboard_counts():
    try:
        today = date.today()
        active_count = PreExpansion.query.filter_by(status='active').count()
        completed_today = PreExpansion.query.filter(
            PreExpansion.status == 'completed',
            func.date(PreExpansion.end_time) == today
        ).count()
        two_hours_ago = datetime.utcnow() - timedelta(hours=2)
        overdue_count = PreExpansion.query.filter(
            PreExpansion.status == 'active',
            PreExpansion.start_time < two_hours_ago
        ).count()
        total_completed = PreExpansion.query.filter_by(status='completed').count()
        return {
            "active_count": active_count,
            "completed_today": completed_today,
            "overdue_count": overdue_count,
            "total_completed": total_completed
        }, None
    except SQLAlchemyError as e:
        return {
            "active_count": 0,
            "completed_today": 0,
            "overdue_count": 0,
            "total_completed": 0
        }, str(e)

def _pre_expansion_has_output(pre_exp: PreExpansion) -> bool:
    """True if this pre-expansion has produced blocks or moulded sessions."""
    try:
        if pre_exp.purpose == 'Block':
            from models.block import Block
            return db.session.query(Block.id).filter_by(pre_expansion_id=pre_exp.id).count() > 0
        elif pre_exp.purpose == 'Moulded':
            from models.moulded_cornice import MouldedCorniceSession
            return db.session.query(MouldedCorniceSession.id).filter_by(pre_expansion_id=pre_exp.id).count() > 0
        else:
            # Fallback: check both
            from models.block import Block
            from models.moulded_cornice import MouldedCorniceSession
            b = db.session.query(Block.id).filter_by(pre_expansion_id=pre_exp.id).count()
            m = db.session.query(MouldedCorniceSession.id).filter_by(pre_expansion_id=pre_exp.id).count()
            return (b + m) > 0
    except Exception:
        return False


def _is_pastel_captureable(pre_exp: PreExpansion) -> bool:
    """Completed AND has output."""
    return pre_exp.status == 'completed' and _pre_expansion_has_output(pre_exp)

def _log_checklist_event(*, checklist: PreExpansionChecklist, pre_exp: PreExpansion | None,
                         operator, stage: str, ip_address: str | None,
                         checks: dict[str, bool]):
    evt = PreExpansionChecklistEvent(
        checklist_id=checklist.id,
        pre_expansion_id=(pre_exp.id if pre_exp else None),
        stage=stage,
        submitted_by_id=operator.id,
        submitted_by_name=(operator.full_name or operator.username or f"op:{operator.id}"),
        ip_address=ip_address,
        check1=checks.get('check1'),
        check2=checks.get('check2'),
        check3=checks.get('check3'),
        check4=checks.get('check4'),
        check5=checks.get('check5'),
        check6=checks.get('check6'),
        check7=checks.get('check7'),
        check8=checks.get('check8'),
        check9=checks.get('check9'),
        check10=checks.get('check10'),
        check11=checks.get('check11'),
        check12=checks.get('check12'),
        check13=checks.get('check13'),
    )
    db.session.add(evt)
    return safe_commit()

def add_checklist(form, operator, ip_address=None):
    checklist = PreExpansionChecklist(
        completed_by=operator.full_name or operator.username,
        check1=form.check1.data,
        check2=form.check2.data,
        check3=form.check3.data,
        check4=form.check4.data,
        check5=form.check5.data,
        check6=form.check6.data,
        check7=form.check7.data,
        check8=form.check8.data,
        check9=form.check9.data,
        check10=form.check10.data,
        check11=form.check11.data,
        check12=form.check12.data,
        check13=form.check13.data
    )
    db.session.add(checklist)
    ok, err = safe_commit()
    if not ok:
        return None, err

    # Log audit event (pre)
    checks = {f'check{i}': getattr(form, f'check{i}').data for i in range(1, 14)}
    _ok, _err = _log_checklist_event(
        checklist=checklist, pre_exp=None, operator=operator,
        stage='pre', ip_address=ip_address, checks=checks
    )
    if not _ok:
        return checklist, _err  # checklist is saved; event failed (surface error if you want)
    return checklist, None


def link_checklist_to_session(checklist_id, pre_exp_id):
    checklist = PreExpansionChecklist.query.get(checklist_id)
    if not checklist:
        return False, "Checklist not found."
    checklist.pre_expansion_id = pre_exp_id
    # backfill any prior events created before session existed
    (PreExpansionChecklistEvent.query
        .filter_by(checklist_id=checklist_id, pre_expansion_id=None)
        .update({'pre_expansion_id': pre_exp_id}))
    success, error = safe_commit()
    if not success:
        return False, f"Database error: {error}"
    return True, None


def add_finish_session(pre_exp, request_form, operator=None, ip_address=None):
    try:
        # New flow: capture raw weight AFTER pre-expansion, then compute actual used
        raw_after = request_form.get('raw_after_kg', type=float)
        raw_before_val = pre_exp.planned_kg
        raw_before = float(raw_before_val) if raw_before_val is not None else None

        if raw_before is not None:
            if (not math.isfinite(raw_before)) or raw_before < 0:
                return False, "Raw material before must be a valid non-negative number."

        if raw_after is not None:
            if not math.isfinite(float(raw_after)):
                return False, "Raw material after must be a valid number."
            raw_after_f = float(raw_after)
            if raw_after_f < 0:
                return False, "Raw material after cannot be negative."
            if raw_before is None:
                return False, "Raw material before is missing; cannot finish session."

            # AFTER must be strictly less than BEFORE (you must use material).
            if raw_after_f >= raw_before - 1e-6:
                return False, "Raw material after must be less than raw material before."

            used = raw_before - raw_after_f
            if used <= 1e-6:
                return False, "Raw material used must be greater than 0."
            pre_exp.raw_after_kg = raw_after_f
            pre_exp.total_kg_used = round(float(used), 2)
        else:
            # Backward compatibility (older UI): allow posting total_kg_used directly
            used = request_form.get('total_kg_used', type=float)
            if used is None:
                return False, "Raw material used is required."
            if not math.isfinite(float(used)):
                return False, "Raw material used must be a valid number."
            used_f = float(used)
            if used_f <= 0:
                return False, "Raw material used must be greater than 0."
            if raw_before is not None and used_f > raw_before + 1e-6:
                return False, "Raw material used cannot be greater than raw material before."
            pre_exp.total_kg_used = round(used_f, 2)
            # If we know raw_before, backfill raw_after for consistency.
            if raw_before is not None:
                pre_exp.raw_after_kg = round(max(raw_before - used_f, 0.0), 2)
        pre_exp.end_time = datetime.utcnow()
        pre_exp.status = 'completed'

        check11 = bool(request_form.get('check11'))
        check12 = bool(request_form.get('check12'))
        check13 = bool(request_form.get('check13'))

        checklist = pre_exp.checklist  # now a single object or None

        if not checklist:
            # If for some reason there is no checklist yet, create a shell one
            from models.pre_expansion import PreExpansionChecklist
            checklist = PreExpansionChecklist(
                completed_by=(operator.full_name or operator.username) if operator else 'system',
                pre_expansion=pre_exp,
                # default everything to False
                **{f'check{i}': False for i in range(1, 14)}
            )
            db.session.add(checklist)

        # write the after-operation checks
        checklist.check11 = check11
        checklist.check12 = check12
        checklist.check13 = check13

        ok, err = safe_commit()
        if not ok:
            return False, err

        # Audit event (post)
        if operator:
            checks_snapshot = {f'check{i}': getattr(checklist, f'check{i}') for i in range(1, 14)}
            _ok, _err = _log_checklist_event(
                checklist=checklist, pre_exp=pre_exp, operator=operator,
                stage='post', ip_address=ip_address, checks=checks_snapshot
            )
            if not _ok:
                return False, _err

        return True, None
    except Exception as e:
        db.session.rollback()
        return False, str(e)




def add_checklist_from_values(checks: dict, operator, pre_exp: PreExpansion | None, ip_address=None):
    # pre_expansion_id is UNIQUE, so we must upsert here (double-submits happen).
    checklist = None
    if pre_exp is not None:
        checklist = getattr(pre_exp, 'checklist', None)
        if checklist is None:
            checklist = PreExpansionChecklist.query.filter_by(pre_expansion_id=pre_exp.id).first()

    if checklist is None:
        checklist = PreExpansionChecklist(
            completed_by=operator.full_name or operator.username,
            pre_expansion_id=(pre_exp.id if pre_exp else None),
            **{f'check{i}': bool(checks.get(f'check{i}', False)) for i in range(1, 14)}
        )
        db.session.add(checklist)
    else:
        checklist.completed_by = operator.full_name or operator.username
        checklist.completed_at = datetime.utcnow()
        for i in range(1, 14):
            setattr(checklist, f'check{i}', bool(checks.get(f'check{i}', False)))

    ok, err = safe_commit()
    if not ok:
        return None, err

    # Log audit “pre” event with snapshot
    _ok, _err = _log_checklist_event(
        checklist=checklist,
        pre_exp=pre_exp,
        operator=operator,
        stage='pre',
        ip_address=ip_address,
        checks=checks
    )
    if not _ok:
        return checklist, _err
    return checklist, None
