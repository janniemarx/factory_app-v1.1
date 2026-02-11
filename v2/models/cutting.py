from v2.app import db

class WireCuttingSession(db.Model):
    __tablename__ = 'wire_cutting_session'
    id = db.Column(db.Integer, primary_key=True)
    block_id = db.Column(db.Integer, db.ForeignKey('block.id'), nullable=False)
    machine_id = db.Column(db.Integer, db.ForeignKey('machine.id'), nullable=False)
    operator_id = db.Column(db.Integer, db.ForeignKey('operator.id'), nullable=False)
    profile_code = db.Column(db.String(20), nullable=False)
    status = db.Column(db.String(20), default='active')
    start_time = db.Column(db.DateTime, nullable=False)
    end_time = db.Column(db.DateTime, nullable=True)
    profiles_cut = db.Column(db.Integer, default=0)

    def __repr__(self):
        return f"<CuttingSession {self.id} {self.profile_code}>"
