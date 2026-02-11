

from models import db
from datetime import datetime, date

from models import db
from datetime import datetime, date

class PreExpansion(db.Model):
    __tablename__ = 'pre_expansions'
    id = db.Column(db.Integer, primary_key=True)
    batch_no = db.Column(db.String(50), nullable=False)
    pre_exp_date = db.Column(db.Date, nullable=False, default=date.today)

    density = db.Column(db.Float, nullable=False)
    planned_kg = db.Column(db.Float, nullable=False)
    # Raw material weight after pre-expansion (captured when finishing session)
    raw_after_kg = db.Column(db.Float, nullable=True)
    total_kg_used = db.Column(db.Float, nullable=True)
    purpose = db.Column(db.String(20), nullable=False)

    operator_id = db.Column(db.Integer, db.ForeignKey('operators.id'))
    operator = db.relationship('Operator', backref='pre_expansions')

    status = db.Column(db.String(20), default='active')
    start_time = db.Column(db.DateTime, default=datetime.utcnow)
    end_time = db.Column(db.DateTime, nullable=True)

    density_checks = db.relationship('DensityCheck', backref='pre_expansion',
                                     cascade="all, delete-orphan", lazy=True)

    is_used = db.Column(db.Boolean, default=False)
    material_code = db.Column(db.String(20), nullable=True)
    is_pastel_captured = db.Column(db.Boolean, default=False)

    checklist = db.relationship(
        'PreExpansionChecklist',
        back_populates='pre_expansion',
        uselist=False,
        cascade='all, delete-orphan'
    )

    # NEW: leftover tracking
    leftover_kg = db.Column(db.Float, nullable=True)                 # how much was left after blocks
    leftover_disposition = db.Column(db.String(20), index=True)      # 'moulded' | 'pr16' | None
    leftover_target_pre_expansion_id = db.Column(                    # when moved to moulded: the new batch id
        db.Integer,
        db.ForeignKey('pre_expansions.id'),
        nullable=True
    )
    # optional convenience link; self-referential
    leftover_target = db.relationship('PreExpansion', remote_side=[id], uselist=False)

    def duration_minutes(self):
        if self.end_time:
            return int((self.end_time - self.start_time).total_seconds() / 60)
        return None



class DensityCheck(db.Model):
    __tablename__ = 'density_checks'
    id = db.Column(db.Integer, primary_key=True)
    pre_expansion_id = db.Column(db.Integer, db.ForeignKey('pre_expansions.id'), nullable=False)
    check_time = db.Column(db.DateTime, default=datetime.utcnow)
    measured_density = db.Column(db.Float, nullable=False)
    measured_weight = db.Column(db.Float, nullable=False)
    operator_id = db.Column(db.Integer, db.ForeignKey('operators.id'), nullable=False)  # FK to Operator table

    operator = db.relationship('Operator', backref='density_checks')

class PreExpansionChecklist(db.Model):
    __tablename__ = 'pre_expansion_checklists'
    id = db.Column(db.Integer, primary_key=True)
    completed_by = db.Column(db.String(100), nullable=False)
    completed_at = db.Column(db.DateTime, default=datetime.utcnow)
    # Individual checkboxes (Boolean)
    check1 = db.Column(db.Boolean, nullable=False)
    check2 = db.Column(db.Boolean, nullable=False)
    check3 = db.Column(db.Boolean, nullable=False)
    check4 = db.Column(db.Boolean, nullable=False)
    check5 = db.Column(db.Boolean, nullable=False)
    check6 = db.Column(db.Boolean, nullable=False)
    check7 = db.Column(db.Boolean, nullable=False)
    check8 = db.Column(db.Boolean, nullable=False)
    check9 = db.Column(db.Boolean, nullable=False)
    check10 = db.Column(db.Boolean, nullable=False)
    check11 = db.Column(db.Boolean, nullable=False)
    check12 = db.Column(db.Boolean, nullable=False)
    check13 = db.Column(db.Boolean, nullable=False)
    # Optional: Linked to pre-expansion session
    pre_expansion_id = db.Column(db.Integer, db.ForeignKey('pre_expansions.id'), nullable=True, unique=True)
    # Optional: Relationship to session
    pre_expansion = db.relationship('PreExpansion', back_populates='checklist')

class PreExpansionChecklistEvent(db.Model):
    __tablename__ = 'pre_expansion_checklist_events'

    id = db.Column(db.Integer, primary_key=True)

    # Link to master checklist + session
    checklist_id = db.Column(db.Integer, db.ForeignKey('pre_expansion_checklists.id'), nullable=False)
    pre_expansion_id = db.Column(db.Integer, db.ForeignKey('pre_expansions.id'), nullable=True)

    # "pre" or "post"
    stage = db.Column(db.String(10), nullable=False)

    # Who, when, where
    submitted_by_id = db.Column(db.Integer, db.ForeignKey('operators.id'), nullable=False)
    submitted_by_name = db.Column(db.String(100), nullable=False)
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    ip_address = db.Column(db.String(45), nullable=True)  # IPv4/IPv6

    # Snapshot of all checks at time of submission (booleans)
    check1  = db.Column(db.Boolean, nullable=True)
    check2  = db.Column(db.Boolean, nullable=True)
    check3  = db.Column(db.Boolean, nullable=True)
    check4  = db.Column(db.Boolean, nullable=True)
    check5  = db.Column(db.Boolean, nullable=True)
    check6  = db.Column(db.Boolean, nullable=True)
    check7  = db.Column(db.Boolean, nullable=True)
    check8  = db.Column(db.Boolean, nullable=True)
    check9  = db.Column(db.Boolean, nullable=True)
    check10 = db.Column(db.Boolean, nullable=True)
    check11 = db.Column(db.Boolean, nullable=True)
    check12 = db.Column(db.Boolean, nullable=True)
    check13 = db.Column(db.Boolean, nullable=True)

    # Relationships (optional convenience)
    checklist = db.relationship('PreExpansionChecklist', backref='events')