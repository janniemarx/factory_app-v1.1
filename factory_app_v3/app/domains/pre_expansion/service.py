from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import func

from app.extensions import db
from app.shared.db_utils import safe_commit

from models.pre_expansion import PreExpansion, DensityCheck, PreExpansionChecklist, PreExpansionChecklistEvent


@dataclass(frozen=True)
class DashboardCounts:
    active_count: int
    completed_today: int
    overdue_count: int
    total_completed: int


def generate_batch_no(pre_exp_date: date, density: float | int, purpose: str) -> str:
    date_str = pre_exp_date.strftime("%Y%m%d")
    density_str = str(int(density)).replace(".", "")
    same_batches = (
        PreExpansion.query.filter(
            PreExpansion.pre_exp_date == pre_exp_date,
            PreExpansion.density == density,
            PreExpansion.purpose == purpose,
        ).count()
    )
    next_batch_num = same_batches + 1
    return f"{date_str}-{density_str}-{purpose} {next_batch_num}"


def create_session(*, material_code: str, density: int, planned_kg: float, purpose: str, operator_id: int) -> tuple[PreExpansion | None, str | None]:
    batch_no = generate_batch_no(date.today(), density, purpose)
    pre_exp = PreExpansion(
        batch_no=batch_no,
        pre_exp_date=date.today(),
        density=density,
        planned_kg=planned_kg,
        purpose=purpose,
        operator_id=operator_id,
        material_code=material_code,
        status="active",
        start_time=datetime.utcnow(),
    )
    db.session.add(pre_exp)
    ok, err = safe_commit()
    return (pre_exp if ok else None), err


def add_density_check(*, pre_expansion_id: int, measured_density: float, measured_weight: float, operator_id: int) -> tuple[DensityCheck | None, str | None]:
    check = DensityCheck(
        pre_expansion_id=pre_expansion_id,
        measured_density=measured_density,
        measured_weight=measured_weight,
        operator_id=operator_id,
    )
    db.session.add(check)
    ok, err = safe_commit()
    return (check if ok else None), err


def get_active_sessions() -> tuple[list[PreExpansion], str | None]:
    try:
        return (
            PreExpansion.query.filter_by(status="active")
            .order_by(PreExpansion.start_time.desc())
            .all(),
            None,
        )
    except Exception as e:
        return [], str(e)


def get_completed_sessions() -> tuple[list[PreExpansion], str | None]:
    try:
        return (
            PreExpansion.query.filter_by(status="completed")
            .order_by(PreExpansion.end_time.desc())
            .all(),
            None,
        )
    except Exception as e:
        return [], str(e)


def get_dashboard_counts() -> tuple[DashboardCounts, str | None]:
    try:
        today = date.today()
        active_count = PreExpansion.query.filter_by(status="active").count()
        completed_today = (
            PreExpansion.query.filter(
                PreExpansion.status == "completed",
                func.date(PreExpansion.end_time) == today,
            ).count()
        )
        two_hours_ago = datetime.utcnow() - timedelta(hours=2)
        overdue_count = (
            PreExpansion.query.filter(
                PreExpansion.status == "active",
                PreExpansion.start_time < two_hours_ago,
            ).count()
        )
        total_completed = PreExpansion.query.filter_by(status="completed").count()
        return (
            DashboardCounts(
                active_count=active_count,
                completed_today=completed_today,
                overdue_count=overdue_count,
                total_completed=total_completed,
            ),
            None,
        )
    except Exception as e:
        return DashboardCounts(0, 0, 0, 0), str(e)


def add_checklist(*, operator, ip_address: str | None, checks: dict[str, bool], pre_expansion_id: int | None = None) -> tuple[PreExpansionChecklist | None, str | None]:
    # pre_expansion_id is UNIQUE: update existing checklist if it already exists.
    checklist = None
    if pre_expansion_id is not None:
        checklist = PreExpansionChecklist.query.filter_by(pre_expansion_id=pre_expansion_id).first()

    if checklist is None:
        checklist = PreExpansionChecklist(
            completed_by=(operator.full_name or operator.username),
            pre_expansion_id=pre_expansion_id,
            **{f"check{i}": bool(checks.get(f"check{i}", False)) for i in range(1, 14)},
        )
        db.session.add(checklist)
    else:
        checklist.completed_by = (operator.full_name or operator.username)
        checklist.completed_at = datetime.utcnow()
        for i in range(1, 14):
            setattr(checklist, f"check{i}", bool(checks.get(f"check{i}", False)))

    ok, err = safe_commit()
    if not ok:
        return None, err

    # Audit event (pre)
    evt = PreExpansionChecklistEvent(
        checklist_id=checklist.id,
        pre_expansion_id=pre_expansion_id,
        stage="pre",
        submitted_by_id=operator.id,
        submitted_by_name=(operator.full_name or operator.username or f"op:{operator.id}"),
        ip_address=ip_address,
        **{f"check{i}": checks.get(f"check{i}") for i in range(1, 14)},
    )
    db.session.add(evt)
    ok2, err2 = safe_commit()
    return checklist, (err2 if not ok2 else None)


def link_checklist_to_session(*, checklist_id: int, pre_expansion_id: int) -> tuple[bool, str | None]:
    checklist = PreExpansionChecklist.query.get(checklist_id)
    if not checklist:
        return False, "Checklist not found."

    checklist.pre_expansion_id = pre_expansion_id
    # backfill any prior events created before session existed
    (PreExpansionChecklistEvent.query
        .filter_by(checklist_id=checklist_id, pre_expansion_id=None)
        .update({"pre_expansion_id": pre_expansion_id}))

    ok, err = safe_commit()
    return ok, err


def finish_session(*, pre_exp: PreExpansion, total_kg_used: float | None, operator=None, ip_address: str | None = None,
                  post_checks: dict[str, bool] | None = None) -> tuple[bool, str | None]:
    """Finish a pre-expansion session, ensure checklist exists, and write post-operation audit event."""
    try:
        pre_exp.total_kg_used = total_kg_used
        pre_exp.end_time = datetime.utcnow()
        pre_exp.status = "completed"

        checklist = pre_exp.checklist
        if not checklist:
            checklist = PreExpansionChecklist(
                completed_by=(operator.full_name or operator.username) if operator else "system",
                pre_expansion=pre_exp,
                **{f"check{i}": False for i in range(1, 14)},
            )
            db.session.add(checklist)

        post_checks = post_checks or {}
        for i in range(11, 14):
            setattr(checklist, f"check{i}", bool(post_checks.get(f"check{i}", False)))

        ok, err = safe_commit()
        if not ok:
            return False, err

        if operator:
            evt = PreExpansionChecklistEvent(
                checklist_id=checklist.id,
                pre_expansion_id=pre_exp.id,
                stage="post",
                submitted_by_id=operator.id,
                submitted_by_name=(operator.full_name or operator.username or f"op:{operator.id}"),
                ip_address=ip_address,
                **{f"check{i}": getattr(checklist, f"check{i}", None) for i in range(1, 14)},
            )
            db.session.add(evt)
            ok2, err2 = safe_commit()
            return ok2, err2

        return True, None
    except Exception as e:
        db.session.rollback()
        return False, str(e)


def is_pastel_captureable(pre_exp: PreExpansion) -> bool:
    # Keep identical behavior to legacy helper
    try:
        if pre_exp.status != "completed":
            return False
        if pre_exp.purpose == "Block":
            from models.block import Block

            return db.session.query(Block.id).filter_by(pre_expansion_id=pre_exp.id).count() > 0
        if pre_exp.purpose == "Moulded":
            from models.moulded_cornice import MouldedCorniceSession

            return db.session.query(MouldedCorniceSession.id).filter_by(pre_expansion_id=pre_exp.id).count() > 0

        # fallback: check both
        from models.block import Block
        from models.moulded_cornice import MouldedCorniceSession

        b = db.session.query(Block.id).filter_by(pre_expansion_id=pre_exp.id).count()
        m = db.session.query(MouldedCorniceSession.id).filter_by(pre_expansion_id=pre_exp.id).count()
        return (b + m) > 0
    except Exception:
        return False
