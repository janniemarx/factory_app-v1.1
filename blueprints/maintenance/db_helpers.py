from __future__ import annotations
from datetime import datetime
from typing import Optional, Tuple

from sqlalchemy.exc import SQLAlchemyError
from models import db
from models.maintenance import (
    MaintenanceJob, MaintenanceWorkSession, MaintenanceWorkSegment,
    MaintenanceStepLog, MaintenanceReview
)

# --------------------------- Utils ---------------------------

def _now() -> datetime:
    return datetime.utcnow()

def safe_commit() -> Tuple[bool, Optional[str]]:
    try:
        db.session.commit()
        return True, None
    except SQLAlchemyError as e:
        db.session.rollback()
        return False, str(e)

# --------------------------- Jobs ---------------------------

def create_job(*, title: str, description: str | None, reported_by_id: int | None,
               location: str | None, asset_code: str | None,
               priority: str = "normal", category: str = "general") -> Tuple[Optional[MaintenanceJob], Optional[str]]:
    job = MaintenanceJob(
        title=title.strip(),
        description=(description or "").strip() or None,
        location=(location or "").strip() or None,
        asset_code=(asset_code or "").strip() or None,
        reported_by_id=reported_by_id,
        created_at=_now(),
        updated_at=_now(),
        priority=priority,
        category=category,
        status="open",
        total_work_seconds=0,
    )
    db.session.add(job)
    ok, err = safe_commit()
    return (job if ok else None), err

def get_job(job_id: int) -> Optional[MaintenanceJob]:
    return MaintenanceJob.query.get(job_id)

def list_jobs(status: str | None = None, assigned_to_id: int | None = None):
    q = MaintenanceJob.query
    if status:
        q = q.filter(MaintenanceJob.status == status)
    if assigned_to_id:
        q = q.filter(MaintenanceJob.assigned_to_id == assigned_to_id)
    return q.order_by(MaintenanceJob.created_at.desc()).all()

def accept_job(job: MaintenanceJob, technician_id: int) -> Tuple[bool, Optional[str], Optional[MaintenanceWorkSession]]:
    if job.status not in ("open", "rework_requested"):
        return False, "Job cannot be accepted in its current state.", None
    if job.assigned_to_id and job.assigned_to_id != technician_id:
        return False, "Job is already assigned to another technician.", None

    job.assigned_to_id = technician_id
    job.assigned_at = _now()
    job.status = "assigned"
    job.updated_at = _now()

    # Start a work session immediately upon accept
    sess = MaintenanceWorkSession(
        job_id=job.id,
        technician_id=technician_id,
        status="in_progress",
        started_at=_now(),
        is_paused=False,
        total_work_seconds=0,
    )
    db.session.add(sess)
    db.session.flush()  # get session id

    # Open first segment
    db.session.add(MaintenanceWorkSegment(session_id=sess.id, started_at=_now()))

    ok, err = safe_commit()
    return ok, err, (sess if ok else None)

# --------------------------- Session lifecycle ---------------------------

def _recompute_session_totals(session: MaintenanceWorkSession) -> None:
    total = 0
    now = _now()
    for seg in session.segments:
        start = seg.started_at
        end = seg.ended_at or now
        if start and end and end > start:
            total += int((end - start).total_seconds())
    session.total_work_seconds = int(total)

def _recompute_job_total(job: MaintenanceJob) -> None:
    total = 0
    for s in job.sessions:
        total += int(s.total_work_seconds or 0)
    job.total_work_seconds = int(total)
    job.updated_at = _now()

def pause_session(session: MaintenanceWorkSession) -> Tuple[bool, Optional[str]]:
    if session.status != "in_progress" or session.is_paused:
        return True, None
    open_seg = (MaintenanceWorkSegment.query
                .filter_by(session_id=session.id, ended_at=None)
                .order_by(MaintenanceWorkSegment.started_at.desc())
                .first())
    if open_seg:
        open_seg.ended_at = _now()
    session.is_paused = True
    session.pause_start = _now()
    _recompute_session_totals(session)
    _recompute_job_total(session.job)
    return safe_commit()

def resume_session(session: MaintenanceWorkSession) -> Tuple[bool, Optional[str]]:
    if session.status != "in_progress" or not session.is_paused:
        return True, None
    session.is_paused = False
    session.pause_start = None
    db.session.add(MaintenanceWorkSegment(session_id=session.id, started_at=_now()))
    _recompute_session_totals(session)
    return safe_commit()

def add_step(session: MaintenanceWorkSession, description: str, added_by_id: int | None) -> Tuple[Optional[MaintenanceStepLog], Optional[str]]:
    step = MaintenanceStepLog(
        session_id=session.id,
        timestamp=_now(),
        description=description.strip(),
        added_by_id=added_by_id
    )
    db.session.add(step)
    ok, err = safe_commit()
    return (step if ok else None), err

def complete_session(session: MaintenanceWorkSession, closing_summary: str | None) -> Tuple[bool, Optional[str]]:
    if session.status != "in_progress":
        return False, "Only in-progress sessions can be completed."
    # close any open segment
    open_seg = (MaintenanceWorkSegment.query
                .filter_by(session_id=session.id, ended_at=None)
                .order_by(MaintenanceWorkSegment.started_at.desc())
                .first())
    if open_seg:
        open_seg.ended_at = _now()

    session.ended_at = _now()
    session.status = "completed"
    session.is_paused = False
    session.pause_start = None
    session.closing_summary = (closing_summary or "").strip() or None

    _recompute_session_totals(session)
    _recompute_job_total(session.job)

    # If all sessions completed for this job, set status to ready for review
    job = session.job
    any_active = any(s.status == "in_progress" for s in job.sessions)
    if not any_active and job.status in ("assigned", "in_progress", "rework_requested"):
        job.status = "in_review"
    return safe_commit()

# --------------------------- Manager review ---------------------------

def submit_job_for_review(job: MaintenanceJob) -> Tuple[bool, Optional[str]]:
    if job.status not in ("assigned", "in_progress", "rework_requested"):
        # allow manual push even from open (edge) but prevent after close
        if job.status == "closed":
            return False, "Closed jobs cannot be re-submitted."
    job.status = "in_review"
    job.updated_at = _now()
    return safe_commit()

def review_job(job: MaintenanceJob, *, reviewed_by_id: int, decision: str, notes: str | None) -> Tuple[bool, Optional[str], Optional[MaintenanceReview]]:
    if job.status != "in_review":
        return False, "Job is not awaiting review.", None

    decision = decision.lower().strip()
    if decision not in ("approved", "rework_requested"):
        return False, "Invalid decision.", None

    rev = MaintenanceReview(
        job_id=job.id,
        reviewed_by_id=reviewed_by_id,
        reviewed_at=_now(),
        decision=decision,
        notes=(notes or "").strip() or None
    )
    db.session.add(rev)

    job.status = "closed" if decision == "approved" else "rework_requested"
    job.updated_at = _now()

    ok, err = safe_commit()
    return ok, err, (rev if ok else None)
