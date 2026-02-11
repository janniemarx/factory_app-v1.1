# models/extrusion.py
from datetime import datetime
from enum import Enum
from sqlalchemy import Index, UniqueConstraint
from sqlalchemy.dialects.sqlite import JSON as SQLITE_JSON  # JSON on SQLite
from models import db

# ========= constants (unit conversions) =========
BAG_25KG = 25.0
OIL_CAN_5L = 5.0

# ========= enums =========
class MaterialType(str, Enum):
    GPPS = "gpps"
    TALC = "talc"
    FIRE_RETARDANT = "fire_retardant"
    RECYCLING = "recycling"
    OIL = "oil"
    CO2 = "co2"
    ALCOHOL = "alcohol"


class UsageUnit(str, Enum):
    KG = "kg"
    LITRE = "l"
    BAGS_25KG = "bags_25kg"
    CANS_5L = "cans_5l"


class ReadingType(str, Enum):
    ABSOLUTE = "absolute"   # raw counter reading
    DELTA = "delta"         # increment since last log


# ========= master data =========
class Extruder(db.Model):
    __tablename__ = "extruders"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False)  # e.g., EXTR-1 / EXTR-2
    name = db.Column(db.String(100))
    is_active = db.Column(db.Boolean, nullable=False, default=True, server_default="1")

    sessions = db.relationship("ExtrusionSession", back_populates="extruder")


class ExtrudedProfile(db.Model):
    __tablename__ = "extruded_profiles"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False)  # CC12, EX12, ...
    length_m = db.Column(db.Float, nullable=False, default=2.0, server_default="2.0")
    pieces_per_box = db.Column(db.Integer, nullable=False, default=72, server_default="72")
    description = db.Column(db.String(255))

    profile_settings = db.relationship(
        "ExtrusionProfileSettings",
        back_populates="profile",
        order_by="ExtrusionProfileSettings.effective_from.desc()",
        cascade="all, delete-orphan",
    )

    sessions = db.relationship(
        "ExtrusionSession",
        back_populates="profile",
        cascade="all, delete-orphan",
    )


class ExtrusionProfileSettings(db.Model):
    __tablename__ = "extruded_profile_settings"

    id = db.Column(db.Integer, primary_key=True)
    profile_id = db.Column(db.Integer, db.ForeignKey("extruded_profiles.id"), nullable=False)

    # NEW: tie settings to a specific machine/extruder
    extruder_id = db.Column(db.Integer, db.ForeignKey("extruders.id"), nullable=False)

    effective_from = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, nullable=False, default=True, server_default="1")

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    created_by_id = db.Column(db.Integer, db.ForeignKey("operators.id"))

    # Machine-2 style (what you already had)
    rpm = db.Column(db.Integer)
    gpps_kg_h = db.Column(db.Float)
    talc_kg_h = db.Column(db.Float)
    fire_retardant_kg_h = db.Column(db.Float)
    recycling_kg_h = db.Column(db.Float)
    co2_kg_h = db.Column(db.Float)
    alcohol_l_h = db.Column(db.Float)

    # NEW: Machine-1 style (Hz)
    extruder_hz = db.Column(db.Float)     # screw freq
    co2_hz = db.Column(db.Float)          # Metering Pump1 (CO2) Hz
    alcohol_hz = db.Column(db.Float)      # Metering Pump2 (Alcohol) Hz
    oil_hz = db.Column(db.Float)          # Metering Pump3 (Oil) Hz

    # Zones (JSON). We will store *either* the Machine-1 names or Machine-2 names.
    heat_table = db.Column(SQLITE_JSON, nullable=False, default=dict, server_default="{}")
    notes = db.Column(db.String(255))

    profile = db.relationship("ExtrudedProfile", back_populates="profile_settings")
    created_by = db.relationship("Operator")
    extruder = db.relationship("Extruder")

    __table_args__ = (
        Index("ix_profile_settings_profile_extruder", "profile_id", "extruder_id"),
        Index("ix_profile_settings_profile_extruder_effective", "profile_id", "extruder_id", "effective_from"),
    )


# ========= live data =========
class ExtrusionSession(db.Model):
    """
    A session can span multiple days with pauses (tracked via run segments).
    We keep a settings snapshot (at start) so audits are stable.
    """
    __tablename__ = "extrusion_sessions"

    id = db.Column(db.Integer, primary_key=True)

    extruder_id = db.Column(db.Integer, db.ForeignKey("extruders.id"), nullable=False)
    profile_id = db.Column(db.Integer, db.ForeignKey("extruded_profiles.id"), nullable=False)
    operator_id = db.Column(db.Integer, db.ForeignKey("operators.id"))

    status = db.Column(db.String(20), nullable=False, default="running", server_default="running")
    started_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    ended_at = db.Column(db.DateTime)
    is_boxing_ready = db.Column(db.Boolean, nullable=False, default=False, server_default="0")

    # Pause windows; exact runtime from run segments
    is_paused = db.Column(db.Boolean, nullable=False, default=False, server_default="0")
    pause_start = db.Column(db.DateTime)

    # Snapshot of settings confirmed at session start
    setpoints_snapshot = db.Column(SQLITE_JSON, nullable=False, default=dict, server_default="{}")
    heat_table_snapshot = db.Column(SQLITE_JSON, nullable=False, default=dict, server_default="{}")

    # Optional rollups (can be recomputed)
    pieces_produced = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    theoretical_boxes = db.Column(db.Integer, nullable=False, default=0, server_default="0")

    # Boxing outcome to estimate damage (for extruded profiles that go to boxing)
    actual_boxes_boxed = db.Column(db.Integer, nullable=False, default=0, server_default="0")

    notes = db.Column(db.String(255))

    extruder = db.relationship("Extruder", back_populates="sessions")
    profile = db.relationship("ExtrudedProfile", back_populates="sessions")
    operator = db.relationship("Operator")

    checklist = db.relationship(
        "ExtrusionPrestartChecklist",
        uselist=False,
        back_populates="session",
        cascade="all, delete-orphan",
    )
    run_segments = db.relationship(
        "ExtrusionRunSegment",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="ExtrusionRunSegment.started_at.asc()",
    )
    rate_plans = db.relationship(
        "ExtrusionRatePlan",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="ExtrusionRatePlan.effective_from.asc()",
    )
    material_usages = db.relationship(
        "ExtrusionMaterialUsage",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="ExtrusionMaterialUsage.timestamp.asc()",
    )
    cycle_logs = db.relationship(
        "ExtrusionCycleLog",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="ExtrusionCycleLog.timestamp.asc()",
    )

    __table_args__ = (
        Index("ix_extrusion_sessions_machine_status", "extruder_id", "status"),
        Index("ix_extrusion_sessions_started_at", "started_at"),
    )

    @property
    def actual_pieces_boxed(self) -> int:
        per_box = int(self.profile.pieces_per_box or 1)
        return int(self.actual_boxes_boxed or 0) * per_box

    @property
    def estimated_damage_pieces(self) -> int:
        # damage = produced - actual boxed pieces
        dmg = int(self.pieces_produced or 0) - int(self.actual_pieces_boxed or 0)
        return max(0, dmg)


class ExtrusionRunSegment(db.Model):
    __tablename__ = "extrusion_run_segments"
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("extrusion_sessions.id"), nullable=False)
    started_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    ended_at = db.Column(db.DateTime)  # null if still running

    session = db.relationship("ExtrusionSession", back_populates="run_segments")

    __table_args__ = (
        Index("ix_extrusion_run_segments_session", "session_id"),
    )


class ExtrusionRatePlan(db.Model):
    __tablename__ = "extrusion_rate_plans"

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("extrusion_sessions.id"), nullable=False)
    effective_from = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    rpm = db.Column(db.Integer)

    gpps_kg_h = db.Column(db.Float)
    talc_kg_h = db.Column(db.Float)
    fire_retardant_kg_h = db.Column(db.Float)
    recycling_kg_h = db.Column(db.Float)
    co2_kg_h = db.Column(db.Float)
    alcohol_l_h = db.Column(db.Float)

    session = db.relationship("ExtrusionSession", back_populates="rate_plans")

    __table_args__ = (
        UniqueConstraint("session_id", "effective_from", name="uq_rateplan_session_effective"),
        Index("ix_rate_plans_session_effective", "session_id", "effective_from"),
    )


class ExtrusionMaterialUsage(db.Model):
    __tablename__ = "extrusion_material_usages"

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("extrusion_sessions.id"), nullable=False)
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    material = db.Column(db.Enum(MaterialType), nullable=False)
    unit = db.Column(db.Enum(UsageUnit), nullable=False)
    quantity = db.Column(db.Float, nullable=False, default=0.0, server_default="0.0")  # number of bags, kg, L, etc.
    note = db.Column(db.String(255))

    session = db.relationship("ExtrusionSession", back_populates="material_usages")

    __table_args__ = (
        Index("ix_material_usages_session_material_time", "session_id", "material", "timestamp"),
    )

    @property
    def as_kg(self) -> float:
        if self.material in (MaterialType.OIL, MaterialType.ALCOHOL) and \
           self.unit in (UsageUnit.LITRE, UsageUnit.CANS_5L):
            return 0.0
        if self.unit == UsageUnit.KG:
            return float(self.quantity or 0.0)
        if self.unit == UsageUnit.BAGS_25KG:
            return float(self.quantity or 0.0) * BAG_25KG
        return 0.0

    @property
    def as_litres(self) -> float:
        if self.unit == UsageUnit.LITRE:
            return float(self.quantity or 0.0)
        if self.unit == UsageUnit.CANS_5L:
            return float(self.quantity or 0.0) * OIL_CAN_5L
        return 0.0


class ExtrusionCycleLog(db.Model):
    __tablename__ = "extrusion_cycle_logs"

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("extrusion_sessions.id"), nullable=False)
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    reading_type = db.Column(db.Enum(ReadingType), nullable=False, default=ReadingType.ABSOLUTE)
    reading_value = db.Column(db.Integer, nullable=False, default=0, server_default="0")

    note = db.Column(db.String(255))

    session = db.relationship("ExtrusionSession", back_populates="cycle_logs")

    __table_args__ = (
        Index("ix_cycle_logs_session_time", "session_id", "timestamp"),
    )


class ExtrusionPrestartChecklist(db.Model):
    __tablename__ = "extrusion_prestart_checklists"

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("extrusion_sessions.id"), nullable=False, unique=True)

    completed_by_id = db.Column(db.Integer, db.ForeignKey("operators.id"))
    completed_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    answers = db.Column(SQLITE_JSON, nullable=False, default=dict, server_default="{}")
    approved = db.Column(db.Boolean, nullable=False, default=True, server_default="1")
    notes = db.Column(db.String(255))

    session = db.relationship("ExtrusionSession", back_populates="checklist")
    completed_by = db.relationship("Operator")
