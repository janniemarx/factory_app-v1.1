# models/maintenance.py
from datetime import datetime
from sqlalchemy import Index
from models import db

# ---------- Core Job ----------
class MaintenanceJob(db.Model):
    """
    A maintenance job/request created by a manager (or any reporter).
    One job can have multiple work sessions over multiple days.
    Flow:
      open -> assigned -> in_progress/paused -> awaiting_review -> closed/rejected
    """
    __tablename__ = "maintenance_jobs"

    id = db.Column(db.Integer, primary_key=True)

    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)

    # Optional “where”/asset hints (keep generic to avoid cross-app coupling)
    location = db.Column(db.String(120))         # e.g. "Extruder 1", "Cutting saw"
    asset_code = db.Column(db.String(50))        # free text tag if you use codes

    # Who reported / created the job
    reported_by_id = db.Column(db.Integer, db.ForeignKey("operators.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Assignment & tracking
    assigned_to_id = db.Column(db.Integer, db.ForeignKey("operators.id"), nullable=True)
    assigned_at = db.Column(db.DateTime)

    priority = db.Column(db.String(10), nullable=False, default="normal")  # low, normal, high, urgent
    category = db.Column(db.String(20), nullable=False, default="general") # mechanical, electrical, general, safety

    status = db.Column(
        db.String(20),
        nullable=False,
        default="open"
    )
    # allowed: open, assigned, in_progress, paused, awaiting_review, closed, rejected

    # Rollups (denormalized convenience — recomputed on close / review)
    total_work_seconds = db.Column(db.Integer, nullable=False, default=0)

    # Relationships
    reported_by   = db.relationship("Operator", foreign_keys=[reported_by_id])
    assigned_to   = db.relationship("Operator", foreign_keys=[assigned_to_id])
    sessions      = db.relationship("MaintenanceWorkSession", back_populates="job", cascade="all, delete-orphan")
    reviews       = db.relationship("MaintenanceReview", back_populates="job", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_maint_jobs_status", "status"),
        Index("ix_maint_jobs_priority", "priority"),
        Index("ix_maint_jobs_assigned", "assigned_to_id", "status"),
        Index("ix_maint_jobs_created_at", "created_at"),
    )

    # ---- helpers ----
    @property
    def total_work_minutes(self) -> float:
        return round((self.total_work_seconds or 0) / 60.0, 2)

    @property
    def is_actionable(self) -> bool:
        return self.status in ("open", "assigned", "in_progress", "paused", "awaiting_review")

    def recompute_totals(self):
        secs = 0
        for s in self.sessions:
            secs += s.total_work_seconds
        self.total_work_seconds = int(secs)


# ---------- Work Session (owned by a single technician) ----------
class MaintenanceWorkSession(db.Model):
    """
    Created when a technician accepts a job. Can span multiple days by pausing/resuming.
    Active time is the sum of its run segments.
    """
    __tablename__ = "maintenance_work_sessions"

    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.Integer, db.ForeignKey("maintenance_jobs.id"), nullable=False)

    technician_id = db.Column(db.Integer, db.ForeignKey("operators.id"), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="in_progress")  # in_progress, paused, awaiting_review, closed

    started_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    ended_at   = db.Column(db.DateTime)

    is_paused   = db.Column(db.Boolean, nullable=False, default=False)
    pause_start = db.Column(db.DateTime)

    # cached active seconds for quick list screens
    total_work_seconds = db.Column(db.Integer, nullable=False, default=0)

    # final summary by technician
    closing_summary = db.Column(db.Text)

    job        = db.relationship("MaintenanceJob", back_populates="sessions")
    technician = db.relationship("Operator")
    segments   = db.relationship("MaintenanceWorkSegment", back_populates="session",
                                 cascade="all, delete-orphan", order_by="MaintenanceWorkSegment.started_at.asc()")
    steps      = db.relationship("MaintenanceStepLog", back_populates="session",
                                 cascade="all, delete-orphan", order_by="MaintenanceStepLog.timestamp.asc()")

    __table_args__ = (
        Index("ix_maint_sessions_job", "job_id"),
        Index("ix_maint_sessions_tech_status", "technician_id", "status"),
        Index("ix_maint_sessions_started", "started_at"),
    )

    # ---- helpers ----
    def recompute_total(self):
        secs = 0
        from datetime import datetime as _dt
        now = _dt.utcnow()
        for seg in self.segments:
            start = seg.started_at
            end = seg.ended_at or now
            if start and end and end > start:
                secs += int((end - start).total_seconds())
        self.total_work_seconds = int(secs)

    @property
    def total_work_minutes(self) -> float:
        return round((self.total_work_seconds or 0) / 60.0, 2)


class MaintenanceWorkSegment(db.Model):
    """
    An uninterrupted block of active work.
    New segment on accept/resume. Close segment on pause/close.
    """
    __tablename__ = "maintenance_work_segments"

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("maintenance_work_sessions.id"), nullable=False)
    started_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    ended_at   = db.Column(db.DateTime)

    session = db.relationship("MaintenanceWorkSession", back_populates="segments")

    __table_args__ = (
        Index("ix_maint_segments_session", "session_id"),
        Index("ix_maint_segments_started", "started_at"),
    )


# ---------- Step-by-step notes (technician log) ----------
class MaintenanceStepLog(db.Model):
    __tablename__ = "maintenance_step_logs"

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("maintenance_work_sessions.id"), nullable=False)
    timestamp  = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    description = db.Column(db.Text, nullable=False)

    added_by_id = db.Column(db.Integer, db.ForeignKey("operators.id"), nullable=True)

    session   = db.relationship("MaintenanceWorkSession", back_populates="steps")
    added_by  = db.relationship("Operator")

    __table_args__ = (
        Index("ix_maint_steps_session_time", "session_id", "timestamp"),
    )


# ---------- Manager review/sign-off ----------
class MaintenanceReview(db.Model):
    __tablename__ = "maintenance_reviews"

    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.Integer, db.ForeignKey("maintenance_jobs.id"), nullable=False)

    reviewed_by_id = db.Column(db.Integer, db.ForeignKey("operators.id"), nullable=False)
    reviewed_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    decision = db.Column(db.String(20), nullable=False, default="approved")  # approved, needs_changes, rejected
    notes = db.Column(db.Text)

    job = db.relationship("MaintenanceJob", back_populates="reviews")
    reviewed_by = db.relationship("Operator")

    __table_args__ = (
        Index("ix_maint_reviews_job", "job_id"),
        Index("ix_maint_reviews_when", "reviewed_at"),
    )
