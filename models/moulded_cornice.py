from models import db
from datetime import datetime

# -- Profile weights in grams --
CORNICE_PROFILE_WEIGHTS = {
    'M01': 91.1,
    'M02': 92.2,
    'M03': 77.2,
    'M04': 89.5,
    'M05': 120.4,
    'M06': 83.1,
    'M07': 88.1,
    'M08': 70.8,
    'M09': 64.2,
    'M10': 60.7,
    'M11': 68.0,
    'M12': 53.8,
    'M13': 108.0
}


class MouldedCorniceSession(db.Model):
    __tablename__ = 'moulded_cornice_sessions'
    id = db.Column(db.Integer, primary_key=True)
    pre_expansion_id = db.Column(db.Integer, db.ForeignKey('pre_expansions.id'), nullable=False)
    operator_id = db.Column(db.Integer, db.ForeignKey('operators.id'), nullable=False)
    machine_id = db.Column(db.Integer, db.ForeignKey('moulded_machines.id'), index=True, nullable=True)  # <-- ADD THIS
    mould_number = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(20), default='setup')
    start_time = db.Column(db.DateTime)
    end_time = db.Column(db.DateTime)
    cycles = db.Column(db.Integer, default=0)
    actual_produced_kg = db.Column(db.Float)
    planned_kg = db.Column(db.Float)
    loss_kg = db.Column(db.Float)

    pre_expansion = db.relationship('PreExpansion')
    operator = db.relationship('Operator')
    machine = db.relationship('MouldedMachine', backref='sessions')

    lines = db.relationship('MouldedCorniceLine', backref='session', cascade="all, delete-orphan")
    production_summaries = db.relationship('MouldedCorniceProductionSummary', backref='session', cascade="all, delete-orphan")

    def total_weight_kg(self):
        return self.actual_produced_kg or 0

    def total_cornices_per_profile(self):
        # Returns dict {profile: total produced}
        result = {}
        for line in self.lines:
            profile = line.profile_code
            count = (self.cycles or 0)
            result[profile] = result.get(profile, 0) + count
        return result

    def total_weight_per_profile(self):
        # Returns dict {profile: total weight in grams}
        totals = {}
        for profile, count in self.total_cornices_per_profile().items():
            weight = CORNICE_PROFILE_WEIGHTS.get(profile, 0)
            totals[profile] = round(weight * count, 2)
        return totals

    def total_weight_kg(self):
        # Returns total produced kg
        return round(sum(self.total_weight_per_profile().values()) / 1000, 3)


class MouldedCorniceLine(db.Model):
    __tablename__ = 'moulded_cornice_lines'
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey('moulded_cornice_sessions.id'), nullable=False)
    line_number = db.Column(db.Integer, nullable=False)
    profile_code = db.Column(db.String(8), nullable=False)

class MouldedCorniceProductionSummary(db.Model):
    __tablename__ = 'moulded_cornice_production_summaries'
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey('moulded_cornice_sessions.id'), nullable=False)
    profile_code = db.Column(db.String(8), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    total_weight_kg = db.Column(db.Float, nullable=False)

class MouldedMachine(db.Model):
    __tablename__ = 'moulded_machines'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), nullable=False, unique=True)    # e.g. "Machine 1"
    code = db.Column(db.String(32), nullable=False, unique=True)    # e.g. "MC1"
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Backref from MouldedCorniceSession: 'machine'
    def __repr__(self):
        return f"<MouldedMachine {self.name}>"


