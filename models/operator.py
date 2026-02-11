# models/operator.py
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from models import db


class Operator(UserMixin, db.Model):
    __tablename__ = "operators"

    id = db.Column(db.Integer, primary_key=True)

    # Auth / profile
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    full_name = db.Column(db.String(100), nullable=True)
    active = db.Column(db.Boolean, default=True)
    is_manager = db.Column(db.Boolean, default=False, nullable=False)

    # Device / HR fields
    emp_no = db.Column(db.String(64), unique=True, index=True, nullable=True)
    room_number = db.Column(db.Integer, nullable=True)
    is_night_shift = db.Column(db.Boolean, default=False, nullable=False)
    birthday = db.Column(db.Date, nullable=True)

    # Payroll basics
    currency = db.Column(db.String(8), nullable=False, default='ZAR')
    hourly_rate = db.Column(db.Float, nullable=False, default=0.0)  # base hourly rate
    employment_start_date = db.Column(db.Date, nullable=True)
    work_days_per_week = db.Column(db.Integer, nullable=False, default=5)

    # Leave entitlements (per-employee overrides; defaults reflect common ZA practice)
    annual_entitlement_days = db.Column(db.Float, nullable=False, default=15.0)  # 15 working days/year (5-day week)
    sick_entitlement_days = db.Column(db.Float, nullable=False, default=30.0)    # 30 days per 36-month cycle (5-day week * 6 weeks)
    family_resp_days_per_year = db.Column(db.Float, nullable=False, default=3.0) # 3 days/year
    special_study_days_per_year = db.Column(db.Float, nullable=False, default=0.0)

    # Opening balances at go-live (days)
    opening_annual_days = db.Column(db.Float, nullable=False, default=0.0)
    opening_sick_days = db.Column(db.Float, nullable=False, default=0.0)
    opening_family_days = db.Column(db.Float, nullable=False, default=0.0)
    opening_special_days = db.Column(db.Float, nullable=False, default=0.0)
    opening_balance_asof = db.Column(db.Date, nullable=True)

    # --- Attendance & HR relationships ---

    # Raw events / dailies
    attendance_events = db.relationship(
        "AttendanceEvent",
        back_populates="operator",
        cascade="all, delete-orphan",
    )
    attendance_days = db.relationship(
        "AttendanceDaily",
        back_populates="operator",
        cascade="all, delete-orphan",
    )

    # Overtime (employee owner)
    overtime_requests = db.relationship(
        "OvertimeRequest",
        back_populates="operator",
        foreign_keys="OvertimeRequest.operator_id",
        cascade="all, delete-orphan",
    )
    # What this manager approved or created
    approved_overtime = db.relationship(
        "OvertimeRequest",
        foreign_keys="OvertimeRequest.approved_by_id",
        viewonly=True,
    )
    created_overtime = db.relationship(
        "OvertimeRequest",
        foreign_keys="OvertimeRequest.created_by_id",
        viewonly=True,
    )

    # Leave (employee owner)
    leave_requests = db.relationship(
        "LeaveRequest",
        back_populates="operator",
        foreign_keys="LeaveRequest.operator_id",
        cascade="all, delete-orphan",
    )
    approved_leaves = db.relationship(
        "LeaveRequest",
        foreign_keys="LeaveRequest.approved_by_id",
        viewonly=True,
    )
    created_leaves = db.relationship(
        "LeaveRequest",
        foreign_keys="LeaveRequest.created_by_id",
        viewonly=True,
    )
    night_week_plans = db.relationship(
        "NightWeekPlan",
        back_populates="operator",
        cascade="all, delete-orphan",
    )


    # ---- auth helpers ----
    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def __repr__(self) -> str:
        return f"<Operator id={self.id} username={self.username!r} emp_no={self.emp_no!r}>"
