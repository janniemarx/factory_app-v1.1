from models import db
from datetime import datetime

class BoxingSession(db.Model):
    __tablename__ = 'boxing_sessions'

    id = db.Column(db.Integer, primary_key=True)

    # --- Source (cutting OR extrusion) ---
    source_type = db.Column(db.String(20), nullable=False, default='cutting')  # 'cutting' | 'extrusion'
    cutting_production_id = db.Column(db.Integer, db.ForeignKey('cutting_production_records.id'), nullable=True)
    extrusion_session_id  = db.Column(db.Integer, db.ForeignKey('extrusion_sessions.id'), nullable=True)

    # --- Operator / timing ---
    operator_id = db.Column(db.Integer, db.ForeignKey('operators.id'), nullable=False)
    start_time = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    end_time = db.Column(db.DateTime)
    is_paused = db.Column(db.Boolean, default=False, nullable=False)
    pause_start = db.Column(db.DateTime)
    total_paused_seconds = db.Column(db.Integer, default=0)

    # --- Production entries ---
    boxes_packed = db.Column(db.Integer, nullable=False, default=0)
    leftovers = db.Column(db.Integer, nullable=False, default=0)  # leftover loose cornices after boxing
    cycle_start = db.Column(db.Integer, nullable=True, default=0)  # machine counter before boxing (should be 0)
    cycle_end = db.Column(db.Integer, nullable=True)               # machine counter after boxing

    status = db.Column(db.String(20), default='active', nullable=False)  # active, paused, completed, pending_qc, stock_ready

    # --- Analytics (calc at session completion) ---
    producing_cycles = db.Column(db.Float)         # boxes_packed / 4
    actual_producing_cycles = db.Column(db.Float)  # (cycle_end - cycle_start) - producing_cycles
    time_per_box_min = db.Column(db.Float)         # (end_time - start_time) / boxes_packed, in minutes

    # --- Relationships ---
    cutting_production = db.relationship("CuttingProductionRecord", backref="boxing_sessions")
    extrusion_session  = db.relationship("ExtrusionSession", backref="boxing_sessions")
    operator = db.relationship("Operator", backref="boxing_sessions")
    qc = db.relationship("BoxingQualityControl", uselist=False, back_populates="boxing_session")

    # --- Helpers / derived fields ---
    def actual_boxing_time_minutes(self):
        """Total boxing time in minutes (excluding paused duration)."""
        if not self.end_time or not self.start_time:
            return 0
        total = (self.end_time - self.start_time).total_seconds() - (self.total_paused_seconds or 0)
        return round(total / 60, 2)

    @property
    def producing_cycles_calc(self):
        return (self.boxes_packed or 0) / 4

    @property
    def actual_producing_cycles_calc(self):
        if self.cycle_start is not None and self.cycle_end is not None:
            return (self.cycle_end - self.cycle_start) - self.producing_cycles_calc
        return None

    @property
    def time_per_box_calc(self):
        if self.end_time and self.start_time and self.boxes_packed:
            total_min = (self.end_time - self.start_time).total_seconds() / 60
            return round(total_min / max(self.boxes_packed, 1), 2)
        return None

    @property
    def profile_code(self):
        """Profile code for this session, regardless of source."""
        if self.source_type == 'cutting' and self.cutting_production:
            return getattr(self.cutting_production, 'profile_code', None)
        if self.source_type == 'extrusion' and self.extrusion_session and self.extrusion_session.profile:
            return self.extrusion_session.profile.code
        return None

    @property
    def cornices_per_box(self):
        """Cornices per box for this session, regardless of source (fallback 4)."""
        if self.source_type == 'cutting' and self.cutting_production:
            prof = getattr(self.cutting_production, 'profile', None)
            if prof and getattr(prof, 'cornices_per_box', None):
                return int(prof.cornices_per_box)
        if self.source_type == 'extrusion' and self.extrusion_session and self.extrusion_session.profile:
            return int(self.extrusion_session.profile.pieces_per_box or 4)
        return 4




class BoxingQualityControl(db.Model):
    __tablename__ = 'boxing_quality_controls'

    id = db.Column(db.Integer, primary_key=True)
    boxing_session_id = db.Column(db.Integer, db.ForeignKey('boxing_sessions.id'), nullable=False)
    qc_operator_id = db.Column(db.Integer, db.ForeignKey('operators.id'), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    boxes_checked = db.Column(db.Integer, nullable=False)
    good_cornices_count = db.Column(db.Integer, nullable=False, default=0)  # NEW FIELD
    notes = db.Column(db.Text, nullable=True)
    actions_taken = db.Column(db.Text, nullable=True)
    is_stock_ready = db.Column(db.Boolean, default=False)

    # Relationships
    boxing_session = db.relationship("BoxingSession", back_populates="qc")
    qc_operator = db.relationship("Operator")

    @property
    def total_cornices(self):
        # Calculate from session
        session = self.boxing_session
        profile = session.cutting_production.profile if session and session.cutting_production else None
        cornices_per_box = profile.cornices_per_box if profile else 4  # fallback
        return (session.boxes_packed or 0) * cornices_per_box + (session.leftovers or 0)

    @property
    def damage(self):
        # good_cornices_count - total_cornices boxed = damage in boxing
        return (self.good_cornices_count or 0) - self.total_cornices


class LeftoverCornice(db.Model):
    __tablename__ = 'leftover_cornices'
    id = db.Column(db.Integer, primary_key=True)
    profile_code = db.Column(db.String(20), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    boxing_session_id = db.Column(db.Integer, db.ForeignKey('boxing_sessions.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    used = db.Column(db.Boolean, default=False, nullable=False)
    used_in_session_id = db.Column(db.Integer, db.ForeignKey('boxing_sessions.id'), nullable=True)
    used_at = db.Column(db.DateTime, nullable=True)

    origin_session = db.relationship('BoxingSession', foreign_keys=[boxing_session_id])
    used_in_session = db.relationship('BoxingSession', foreign_keys=[used_in_session_id])