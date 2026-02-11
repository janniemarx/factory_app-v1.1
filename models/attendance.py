# models/attendance.py
from datetime import datetime, time, date
from sqlalchemy import Index, UniqueConstraint
from models import db

# ----------- Raw events (immutable) -----------
# models/attendance.py
from datetime import datetime, time, date
from sqlalchemy import Index, UniqueConstraint
from models import db

class AttendanceEvent(db.Model):
    __tablename__ = "attendance_events"

    id = db.Column(db.Integer, primary_key=True)
    operator_id = db.Column(db.Integer, db.ForeignKey("operators.id"), nullable=True)

    emp_no   = db.Column(db.String(64), nullable=True)
    emp_name = db.Column(db.String(128), nullable=True)  # NEW: denormalized name from device/operator

    timestamp   = db.Column(db.DateTime, nullable=False)          # stored UTC-naive in app
    event_type  = db.Column(db.String(16), nullable=False)        # 'check_in' / 'check_out'
    room_number = db.Column(db.Integer, nullable=True)

    source    = db.Column(db.String(32), nullable=False, default="hikvision")
    source_uid = db.Column(db.String(64), nullable=True)
    ingested_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    operator = db.relationship("Operator", back_populates="attendance_events")

    __table_args__ = (
        UniqueConstraint("source", "emp_no", "timestamp", "event_type", name="uq_att_event_natural"),
        Index("ix_att_events_ts", "timestamp"),
        Index("ix_att_events_operator_ts", "operator_id", "timestamp"),
    )


# ----------- Per-day rollup -----------
class AttendanceDaily(db.Model):
    __tablename__ = "attendance_daily"

    id = db.Column(db.Integer, primary_key=True)
    operator_id = db.Column(db.Integer, db.ForeignKey("operators.id"), nullable=False)
    emp_no = db.Column(db.String(64), nullable=True)

    day = db.Column(db.Date, nullable=False)
    first_in = db.Column(db.DateTime, nullable=True)
    last_out = db.Column(db.DateTime, nullable=True)

    worked_seconds = db.Column(db.Integer, nullable=False, default=0)
    segment_count = db.Column(db.Integer, nullable=False, default=0)
    missing_in = db.Column(db.Boolean, nullable=False, default=False)
    missing_out = db.Column(db.Boolean, nullable=False, default=False)

    # Pay buckets per policy
    normal_seconds = db.Column(db.Integer, nullable=False, default=0)  # up to 8h/day & 40h/week
    ot1_seconds = db.Column(db.Integer, nullable=False, default=0)     # weekday outside 07:00–16:00
    ot2_seconds = db.Column(db.Integer, nullable=False, default=0)     # weekends & ZA holidays

    notes = db.Column(db.Text, nullable=True)
    computed_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    operator = db.relationship("Operator", back_populates="attendance_days")

    __table_args__ = (
        UniqueConstraint("operator_id", "day", name="uq_att_daily_operator_day"),
        Index("ix_att_daily_day", "day"),
        Index("ix_att_daily_operator_day", "operator_id", "day"),
    )

    @property
    def worked_hours(self) -> float:
        return round((self.worked_seconds or 0) / 3600.0, 2)

    @property
    def normal_hours(self) -> float:
        return round((self.normal_seconds or 0) / 3600.0, 2)

    @property
    def ot1_hours(self) -> float:
        return round((self.ot1_seconds or 0) / 3600.0, 2)

    @property
    def ot2_hours(self) -> float:
        return round((self.ot2_seconds or 0) / 3600.0, 2)


# ----------- Overtime (manager-driven; can be auto-suggested) -----------
class OvertimeRequest(db.Model):
    """
    Manager-facing record. Operators do NOT request.

    - System may pre-create with source='auto' + proposed_hours based on AttendanceDaily.
    - Manager edits and approves, setting `hours` (approved hours) and `status='approved'`.
    """
    __tablename__ = "overtime_requests"

    id = db.Column(db.Integer, primary_key=True)

    operator_id = db.Column(db.Integer, db.ForeignKey("operators.id"), nullable=False)
    day = db.Column(db.Date, nullable=False)
    ot_type = db.Column(db.String(8), nullable=False)  # 'ot1' or 'ot2'

    # Proposed vs approved
    proposed_hours = db.Column(db.Float, nullable=False, default=0.0)  # auto-computed suggestion
    hours = db.Column(db.Float, nullable=False, default=0.0)           # final APPROVED hours for payroll

    reason = db.Column(db.Text, nullable=True)

    status = db.Column(db.String(16), nullable=False, default="pending")  # pending/approved/rejected
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    created_by_id = db.Column(db.Integer, db.ForeignKey("operators.id"), nullable=True)  # manager; null if auto
    approved_by_id = db.Column(db.Integer, db.ForeignKey("operators.id"), nullable=True)
    approved_at = db.Column(db.DateTime, nullable=True)
    notes = db.Column(db.Text, nullable=True)

    # Traceability to daily calc & source
    daily_id = db.Column(db.Integer, db.ForeignKey("attendance_daily.id"), nullable=True)
    source = db.Column(db.String(16), nullable=False, default="manual")  # manual/auto

    operator = db.relationship("Operator", foreign_keys=[operator_id], back_populates="overtime_requests")
    approved_by = db.relationship("Operator", foreign_keys=[approved_by_id])
    created_by = db.relationship("Operator", foreign_keys=[created_by_id])
    daily = db.relationship("AttendanceDaily")

    __table_args__ = (
        UniqueConstraint("operator_id", "day", "ot_type", name="uq_ot_operator_day_type"),
        Index("ix_ot_status_day", "status", "day"),
        Index("ix_ot_operator_day", "operator_id", "day"),
    )


# ----------- Leave (manager-captured; default approved) -----------
class LeaveRequest(db.Model):
    """
    Manager captures leave; operators do NOT request.
    By default we mark as 'approved' when captured, but you can set 'pending'
    if you want a second sign-off step in the UI.
    """
    __tablename__ = "leave_requests"

    id = db.Column(db.Integer, primary_key=True)

    operator_id = db.Column(db.Integer, db.ForeignKey("operators.id"), nullable=False)
    leave_type = db.Column(db.String(20), nullable=False)  # 'annual','sick','unpaid','family',...

    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    hours_per_day = db.Column(db.Float, nullable=True)  # if None, use schedule default (8h)

    status = db.Column(db.String(16), nullable=False, default="approved")  # approved/pending/rejected
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    created_by_id = db.Column(db.Integer, db.ForeignKey("operators.id"), nullable=False)  # manager capturing
    approved_by_id = db.Column(db.Integer, db.ForeignKey("operators.id"), nullable=True)
    approved_at = db.Column(db.DateTime, nullable=True)
    notes = db.Column(db.Text, nullable=True)

    operator = db.relationship("Operator", foreign_keys=[operator_id], back_populates="leave_requests")
    created_by = db.relationship("Operator", foreign_keys=[created_by_id])
    approved_by = db.relationship("Operator", foreign_keys=[approved_by_id])


    payroll_captured_at = db.Column(db.DateTime, nullable=True)
    payroll_captured_by_id = db.Column(db.Integer, db.ForeignKey("operators.id"), nullable=True)
    payroll_captured_by = db.relationship("Operator", foreign_keys=[payroll_captured_by_id])


    __table_args__ = (
        Index("ix_leave_operator_start", "operator_id", "start_date"),
        Index("ix_leave_status", "status"),
    )


# ----------- Schedules & policy -----------
class WorkSchedule(db.Model):
    __tablename__ = "work_schedules"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    is_default = db.Column(db.Boolean, nullable=False, default=False)

    room_number = db.Column(db.Integer, nullable=True)   # optional: per-room override
    operator_id = db.Column(db.Integer, db.ForeignKey("operators.id"), nullable=True)  # optional: per-employee

    day_start = db.Column(db.Time, nullable=False, default=time(7, 0, 0))   # 07:00
    day_end = db.Column(db.Time, nullable=False, default=time(16, 0, 0))    # 16:00
    lunch_minutes = db.Column(db.Integer, nullable=False, default=60)       # unpaid lunch

    weekly_normal_seconds = db.Column(db.Integer, nullable=False, default=40 * 3600)  # 40h/week

    ot_round_minutes = db.Column(db.Integer, nullable=False, default=15)     # round down to N minutes
    round_15_to_zero = db.Column(db.Boolean, nullable=False, default=True)   # 15m -> 0

    enabled = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("ix_sched_default", "is_default"),
        Index("ix_sched_room_enabled", "room_number", "enabled"),
    )


# ----------- Sync runs (observability) -----------
class AttendanceSyncRun(db.Model):
    __tablename__ = "attendance_sync_runs"

    id = db.Column(db.Integer, primary_key=True)
    started_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    ended_at = db.Column(db.DateTime, nullable=True)
    status = db.Column(db.String(8), nullable=False, default="ok")  # ok/error

    from_date = db.Column(db.Date, nullable=False)
    to_date = db.Column(db.Date, nullable=False)

    fetched_events = db.Column(db.Integer, nullable=False, default=0)
    inserted_events = db.Column(db.Integer, nullable=False, default=0)
    errors = db.Column(db.Text, nullable=True)

    __table_args__ = (
        Index("ix_sync_from_to", "from_date", "to_date"),
    )

# --- Night plan (weekly, anchored to Monday) ---
class NightWeekPlan(db.Model):
    __tablename__ = "night_week_plans"

    id = db.Column(db.Integer, primary_key=True)
    operator_id = db.Column(db.Integer, db.ForeignKey("operators.id"), nullable=False)

    # Monday of the ISO week this plan applies to
    week_monday = db.Column(db.Date, nullable=False)

    # Booleans for each evening of this week (18:00 that day → 06:00 next day)
    mon = db.Column(db.Boolean, nullable=False, default=False)
    tue = db.Column(db.Boolean, nullable=False, default=False)
    wed = db.Column(db.Boolean, nullable=False, default=False)
    thu = db.Column(db.Boolean, nullable=False, default=False)
    fri = db.Column(db.Boolean, nullable=False, default=False)
    sat = db.Column(db.Boolean, nullable=False, default=False)
    sun = db.Column(db.Boolean, nullable=False, default=False)

    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow,
                           onupdate=datetime.utcnow)

    operator = db.relationship("Operator", back_populates="night_week_plans")

    __table_args__ = (
        db.UniqueConstraint("operator_id", "week_monday", name="uq_night_plan_operator_week"),
        db.Index("ix_night_plan_operator_week", "operator_id", "week_monday"),
    )

