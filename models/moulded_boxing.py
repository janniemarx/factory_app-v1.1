from datetime import datetime
from models import db
from models.moulded_cornice import MouldedCorniceSession
from models.operator import Operator

# --- Cornices per box for MOULDED (single source of truth) ---
MOULDED_CORNICES_PER_BOX = {
    'M01': 32, 'M02': 34, 'M03': 40, 'M04': 30, 'M05': 20,
    'M06': 44, 'M07': 30, 'M08': 44, 'M09': 44, 'M10': 48,
    'M11': 52, 'M12': 36, 'M13': 22,
}


class MouldedBoxingSession(db.Model):
    """
    One boxing session per moulded production session at a time (but you can have multiple over days).
    We aggregate per-profile saves into MouldedBoxedItem rows.
    """
    __tablename__ = "moulded_boxing_sessions"

    id = db.Column(db.Integer, primary_key=True)
    moulded_session_id = db.Column(db.Integer, db.ForeignKey('moulded_cornice_sessions.id'), nullable=False, index=True)
    operator_id = db.Column(db.Integer, db.ForeignKey('operators.id'), nullable=False, index=True)

    start_time = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    end_time = db.Column(db.DateTime)
    status = db.Column(db.String(20), default='active', nullable=False)  # active, paused, pending_qc, stock_ready

    # Pause tracking
    is_paused = db.Column(db.Boolean, default=False, nullable=False)
    pause_start = db.Column(db.DateTime)
    total_paused_seconds = db.Column(db.Integer, default=0)

    # Aggregates (recomputed when finishing)
    total_boxes = db.Column(db.Integer, default=0)      # sum of item.boxes_packed
    total_leftovers = db.Column(db.Integer, default=0)  # sum of item.leftovers
    time_per_box_min = db.Column(db.Float)              # actual_boxing_minutes() / total_boxes

    # Relationships
    moulded_session = db.relationship(MouldedCorniceSession, backref="boxing_sessions")
    operator = db.relationship(Operator)
    items = db.relationship("MouldedBoxedItem", backref="session", cascade="all, delete-orphan")
    qc = db.relationship("MouldedBoxingQualityControl", backref="session", uselist=False, cascade="all, delete-orphan")

    # --- Analytics helpers ---
    @property
    def drying_minutes(self) -> float:
        """Time from moulded production end to boxing start (0 if missing/negative)."""
        ms = self.moulded_session
        if not ms or not ms.end_time or not self.start_time:
            return 0.0
        secs = (self.start_time - ms.end_time).total_seconds()
        return round(max(secs, 0) / 60.0, 2)

    def actual_boxing_minutes(self) -> float:
        """Boxing elapsed minus paused seconds."""
        if not self.end_time or not self.start_time:
            return 0.0
        total = (self.end_time - self.start_time).total_seconds() - (self.total_paused_seconds or 0)
        return round(max(total, 0) / 60.0, 2)

    def recompute_totals(self):
        self.total_boxes = sum(i.boxes_packed or 0 for i in self.items)
        self.total_leftovers = sum(i.leftovers or 0 for i in self.items)
        minutes = self.actual_boxing_minutes()
        self.time_per_box_min = round(minutes / self.total_boxes, 2) if self.total_boxes else None

    # --- Produced vs Boxed breakdowns ---
    def produced_by_profile(self) -> dict[str, int]:
        """Dict {profile_code: produced_qty} from production_summaries (authoritative)."""
        d: dict[str, int] = {}
        for s in self.moulded_session.production_summaries:
            d[s.profile_code] = d.get(s.profile_code, 0) + (s.quantity or 0)
        return d

    def boxed_by_profile(self) -> dict[str, int]:
        """Dict {profile_code: boxed_qty} computed from items (boxes*per_box + leftovers)."""
        d: dict[str, int] = {}
        for it in self.items:
            per_box = MOULDED_CORNICES_PER_BOX.get(it.profile_code, 0)
            boxed = (it.boxes_packed or 0) * per_box + (it.leftovers or 0)
            d[it.profile_code] = d.get(it.profile_code, 0) + boxed
        return d

    def remaining_by_profile(self) -> dict[str, int]:
        prod = self.produced_by_profile()
        boxed = self.boxed_by_profile()
        keys = set(prod) | set(boxed)
        return {k: max(prod.get(k, 0) - boxed.get(k, 0), 0) for k in keys}

    def damage_by_profile(self) -> dict[str, int]:
        """boxed - produced (positive => over; negative => damage)."""
        prod = self.produced_by_profile()
        boxed = self.boxed_by_profile()
        keys = set(prod) | set(boxed)
        return {k: (boxed.get(k, 0) - prod.get(k, 0)) for k in keys}


class MouldedBoxedItem(db.Model):
    """
    Per-profile save chunk inside a boxing session (you can save multiple times per profile).
    """
    __tablename__ = "moulded_boxed_items"

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey('moulded_boxing_sessions.id'), nullable=False, index=True)
    profile_code = db.Column(db.String(8), nullable=False)  # e.g. 'M01'
    boxes_packed = db.Column(db.Integer, default=0, nullable=False)
    leftovers = db.Column(db.Integer, default=0, nullable=False)  # loose cornices
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    @property
    def cornices_per_box(self) -> int:
        return MOULDED_CORNICES_PER_BOX.get(self.profile_code, 0)

    @property
    def total_cornices(self) -> int:
        return (self.boxes_packed or 0) * self.cornices_per_box + (self.leftovers or 0)


class MouldedBoxingQualityControl(db.Model):
    __tablename__ = "moulded_boxing_quality_controls"

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey('moulded_boxing_sessions.id'), nullable=False, index=True)
    qc_operator_id = db.Column(db.Integer, db.ForeignKey('operators.id'), nullable=False, index=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    boxes_checked = db.Column(db.Integer, nullable=False, default=0)
    good_cornices_count = db.Column(db.Integer, nullable=False, default=0)
    notes = db.Column(db.Text)
    actions_taken = db.Column(db.Text)
    is_stock_ready = db.Column(db.Boolean, default=False, nullable=False)

    qc_operator = db.relationship(Operator)
