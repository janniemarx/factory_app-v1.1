from models import db
from datetime import datetime

class PR16Session(db.Model):
    __tablename__ = "pr16_sessions"
    id = db.Column(db.Integer, primary_key=True)

    # Linkage
    operator_id = db.Column(db.Integer, db.ForeignKey('operators.id'), nullable=False)
    operator = db.relationship('Operator')

    # Timeline
    started_at = db.Column(db.DateTime, default=datetime.utcnow)
    wrapping_end = db.Column(db.DateTime)
    drying_start = db.Column(db.DateTime)
    drying_end = db.Column(db.DateTime)
    trimming_start = db.Column(db.DateTime)
    trimming_end = db.Column(db.DateTime)
    completed_at = db.Column(db.DateTime)

    # Status: active → in_drying → trimming → awaiting_qc → qc_passed / qc_failed
    status = db.Column(db.String(20), default="active")

    # NEW: pause support (wrapping stage)
    is_paused = db.Column(db.Boolean, default=False)
    pause_start = db.Column(db.DateTime)
    total_wrapping_paused_seconds = db.Column(db.Integer, default=0)

    # --- NEW: Trimming pause fields ---
    is_trim_paused = db.Column(db.Boolean, default=False)
    trim_pause_start = db.Column(db.DateTime)
    total_trimming_paused_seconds = db.Column(db.Integer, default=0)

    # Totals
    wrapped_cornices = db.Column(db.Integer, default=0)
    trimmed_cornices = db.Column(db.Integer, default=0)
    boxed_cornices = db.Column(db.Integer, default=0)

    # Damages
    wrapping_damage = db.Column(db.Integer, default=0)
    trimming_damage = db.Column(db.Integer, default=0)
    total_damage = db.Column(db.Integer, default=0)

    # Resources
    glue_used_kg = db.Column(db.Float, default=0.0)
    paper_used_m = db.Column(db.Float, default=0.0)
    glue_drums_used = db.Column(db.Integer, default=0)   # 50kg drums
    paper_rolls_used = db.Column(db.Integer, default=0)  # 300m rolls

    # Paper analytics
    expected_paper_m = db.Column(db.Float, default=0.0)
    paper_loss_m = db.Column(db.Float, default=0.0)

    # Durations (minutes)
    wrapping_duration_min = db.Column(db.Float)
    drying_duration_min = db.Column(db.Float)
    trimming_duration_min = db.Column(db.Float)

    # Relationships
    resource_usages = db.relationship("PR16ResourceUsage", back_populates="session", cascade="all, delete-orphan")
    wrapping_logs = db.relationship("PR16WrappingLog", back_populates="session", cascade="all, delete-orphan")
    trimming_logs = db.relationship("PR16TrimmingLog", back_populates="session", cascade="all, delete-orphan")
    wrapping_productions = db.relationship('PR16WrappingProduction', back_populates='session', cascade="all, delete-orphan")
    qc = db.relationship('PR16QualityCheck', uselist=False, back_populates='session')
    block_id = db.Column(db.Integer, db.ForeignKey('blocks.id'), nullable=False)
    block = db.relationship('Block', lazy='joined')

class PR16ResourceUsage(db.Model):
    __tablename__ = "pr16_resource_usages"
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("pr16_sessions.id"), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    resource_type = db.Column(db.String(20))  # "glue" or "paper"
    amount = db.Column(db.Float)
    session = db.relationship("PR16Session", back_populates="resource_usages")


class PR16WrappingLog(db.Model):
    __tablename__ = "pr16_wrapping_logs"
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("pr16_sessions.id"), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    cornices_wrapped = db.Column(db.Integer)
    glue_used = db.Column(db.Float)
    paper_used = db.Column(db.Float)
    session = db.relationship("PR16Session", back_populates="wrapping_logs")


class PR16TrimmingLog(db.Model):
    __tablename__ = "pr16_trimming_logs"
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("pr16_sessions.id"), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    trimming_start = db.Column(db.DateTime, nullable=True)
    trimming_end = db.Column(db.DateTime, nullable=True)
    cornices_trimmed = db.Column(db.Integer)
    session = db.relationship("PR16Session", back_populates="trimming_logs")


class PR16WrappingProduction(db.Model):
    __tablename__ = 'pr16_wrapping_production'
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey('pr16_sessions.id'), nullable=False)
    cornices_wrapped = db.Column(db.Integer, nullable=False)
    logged_at = db.Column(db.DateTime, default=datetime.utcnow)
    notes = db.Column(db.String(255), nullable=True)
    session = db.relationship('PR16Session', back_populates='wrapping_productions')


# models/pr16_session.py  (append fields on PR16QualityCheck)
class PR16QualityCheck(db.Model):
    __tablename__ = 'pr16_quality_checks'
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey('pr16_sessions.id'), nullable=False)
    qc_operator_id = db.Column(db.Integer, db.ForeignKey('operators.id'), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    # NEW: counts & quality ratings moved to QC app
    cornices_count_operator = db.Column(db.Integer, nullable=False, default=0)  # usually trimmed qty
    cornices_count_qc       = db.Column(db.Integer, nullable=False, default=0)
    bad_cornices_count      = db.Column(db.Integer, nullable=False, default=0)
    good_cornices_count     = db.Column(db.Integer, nullable=False, default=0)


    # final flags
    passed            = db.Column(db.Boolean, default=False, nullable=False)
    is_boxing_ready   = db.Column(db.Boolean, default=False, nullable=False)
    notes             = db.Column(db.String(255))

    session = db.relationship('PR16Session', back_populates='qc')
    qc_operator = db.relationship('Operator')

