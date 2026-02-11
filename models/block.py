from models import db
from datetime import datetime, timedelta

class BlockSession(db.Model):
    __tablename__ = 'block_sessions'
    id = db.Column(db.Integer, primary_key=True)
    pre_expansion_id = db.Column(db.Integer, db.ForeignKey('pre_expansions.id'), nullable=False)
    operator_id = db.Column(db.Integer, db.ForeignKey('operators.id'), nullable=False)
    started_at = db.Column(db.DateTime, default=datetime.utcnow)
    ended_at = db.Column(db.DateTime)
    status = db.Column(db.String(20), default='active')  # 'active', 'completed'
    blocks = db.relationship('Block', backref='block_session', cascade="all, delete-orphan", lazy=True)

    pre_expansion = db.relationship('PreExpansion')
    operator = db.relationship('Operator')

class Block(db.Model):
    __tablename__ = 'blocks'
    id = db.Column(db.Integer, primary_key=True)
    block_session_id = db.Column(db.Integer, db.ForeignKey('block_sessions.id'), nullable=False)
    pre_expansion_id = db.Column(db.Integer, db.ForeignKey('pre_expansions.id'), nullable=False)
    operator_id = db.Column(db.Integer, db.ForeignKey('operators.id'), nullable=False)
    block_number = db.Column(db.String(20), nullable=False, unique=True)
    weight = db.Column(db.Float, nullable=False)
    heating1_time = db.Column(db.Integer, nullable=False)
    heating2_time = db.Column(db.Integer, nullable=False)
    heating3_time = db.Column(db.Integer, nullable=False)
    cooling_time = db.Column(db.Integer, nullable=False)
    is_profile16 = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_cut = db.Column(db.Boolean, default=False, nullable=False)
    cut_time = db.Column(db.DateTime)
    curing_end = db.Column(db.DateTime, nullable=True)

    pre_expansion = db.relationship('PreExpansion')
    operator = db.relationship('Operator')

    # NEW: detailed provenance rows (one block can consume from multiple sources)
    material_consumptions = db.relationship(
        'BlockMaterialConsumption',
        backref='block',
        cascade='all, delete-orphan',
        lazy=True
    )

    @property
    def density(self):
        return self.pre_expansion.density if self.pre_expansion else None

    def set_curing_end(self):
        if not self.pre_expansion:
            return
        if self.pre_expansion.density == 18:
            self.curing_end = self.created_at + timedelta(days=3)
        elif self.pre_expansion.density == 23:
            self.curing_end = self.created_at + timedelta(days=10)
        else:
            self.curing_end = self.created_at

    # Convenience: kg taken from sources OTHER than the session's batch (i.e., PR16 stash)
    @property
    def kg_from_other_sources(self) -> float:
        if not self.material_consumptions:
            return 0.0
        total = 0.0
        for c in self.material_consumptions:
            if c.source_pre_expansion_id != self.pre_expansion_id:
                total += c.kg_from_source or 0.0
        return round(total, 3)

class BlockMaterialConsumption(db.Model):
    """
    Per-block breakdown of bead consumption by source pre-expansion batch.
    Example rows for one block:
      - 12.3 kg from PR16 stash (source_pre_expansion_id = original batch A)
      - 52.7 kg from current session batch (source_pre_expansion_id = session.pre_expansion_id)
    """
    __tablename__ = 'block_material_consumptions'
    id = db.Column(db.Integer, primary_key=True)
    block_id = db.Column(db.Integer, db.ForeignKey('blocks.id', ondelete='CASCADE'), nullable=False, index=True)
    source_pre_expansion_id = db.Column(db.Integer, db.ForeignKey('pre_expansions.id'), nullable=False, index=True)
    kg_from_source = db.Column(db.Float, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    # Handy relationship to inspect source rows
    source_pre_expansion = db.relationship('PreExpansion')