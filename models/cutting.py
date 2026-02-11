# models/cutting.py

from models import db
from datetime import datetime

# ----------- 1. Cornice Profile Master Table -----------
class Profile(db.Model):
    __tablename__ = 'profiles'

    code = db.Column(db.String(10), primary_key=True)   # E.g. 'PR01'
    density = db.Column(db.Integer, nullable=False)     # 18 or 23
    cornices_per_block = db.Column(db.Integer, nullable=False)
    cornices_per_box = db.Column(db.Integer, nullable=False)
    length_per_cornice = db.Column(db.Float, default=2.5)  # meters

    def __repr__(self):
        return f"<Profile {self.code} (density={self.density})>"

# ----------- 2. Machine Master Table -----------
class Machine(db.Model):
    __tablename__ = 'machines'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False, unique=True)  # "Wire Cutter 1"

    def __repr__(self):
        return f"<Machine {self.name}>"

# ----------- 3. Wire Cutting Session -----------
class WireCuttingSession(db.Model):
    __tablename__ = 'wire_cutting_sessions'

    id = db.Column(db.Integer, primary_key=True)
    block_id = db.Column(db.Integer, db.ForeignKey('blocks.id'), nullable=False)
    operator_id = db.Column(db.Integer, db.ForeignKey('operators.id'), nullable=False)
    machine_id = db.Column(db.Integer, db.ForeignKey('machines.id'), nullable=False)
    profile_code = db.Column(db.String(10), db.ForeignKey('profiles.code'), nullable=False)

    profiles_cut = db.Column(db.Integer, nullable=True)        # Number of cornices/profiles cut
    wastage_m = db.Column(db.Float, nullable=True)             # Wastage in meters for this session
    produced_length_m = db.Column(db.Float, nullable=True)     # Total produced length in meters
    box_count = db.Column(db.Integer, nullable=True)            # Optional: How many boxes packed in this session
    is_paused = db.Column(db.Boolean, default=False, nullable=False)
    segments = db.relationship('WireCuttingSessionSegment', back_populates='session', cascade="all, delete-orphan")

    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    notes = db.Column(db.String(255))

    # *** Add this new line for status ***
    status = db.Column(db.String(20), default='active', nullable=False)  # NEW
    start_time = db.Column(db.DateTime, default=datetime.utcnow)  # <-- ADD THIS
    end_time = db.Column(db.DateTime, nullable=True)  # <-- ADD THIS

    # --- Relationships ---
    block = db.relationship('Block')
    operator = db.relationship('Operator')
    machine = db.relationship('Machine')
    profile = db.relationship('Profile')

    def __repr__(self):
        return (f"<WireCuttingSession block={self.block_id} profile={self.profile_code} "
                f"cut={self.profiles_cut} wastage={self.wastage_m}m status={self.status}>")

    @property
    def total_profile_length(self):
        # Total length of all produced profiles (cornices_cut * 2.5m)
        if self.profile and self.profiles_cut:
            return round(self.profiles_cut * self.profile.length_per_cornice, 2)
        return 0.0

    @property
    def wastage_percent(self):
        """% Wastage (wastage / (produced + wastage)), always safe even if values are None or zero."""
        produced = self.produced_length_m if self.produced_length_m is not None else 0
        wastage = self.wastage_m if self.wastage_m is not None else 0
        total = produced + wastage
        if total > 0:
            return round(100 * wastage / total, 2)
        return 0.0

class MachineProfileAssignment(db.Model):
    __tablename__ = 'machine_profile_assignments'
    id = db.Column(db.Integer, primary_key=True)
    machine_id = db.Column(db.Integer, db.ForeignKey('machines.id'), nullable=False)
    profile_code = db.Column(db.String(10), db.ForeignKey('profiles.code'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    cut = db.Column(db.Boolean, default=False, nullable=False)   # <--- NEW FIELD

    machine = db.relationship('Machine')
    profile = db.relationship('Profile')


class WireCuttingSessionSegment(db.Model):
    __tablename__ = 'wire_cutting_session_segments'
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey('wire_cutting_sessions.id'), nullable=False)
    start_time = db.Column(db.DateTime, nullable=False)
    end_time = db.Column(db.DateTime)

    session = db.relationship('WireCuttingSession', back_populates='segments')
