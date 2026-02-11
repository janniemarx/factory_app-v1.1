from v2.app import db

class BlockSession(db.Model):
    __tablename__ = 'block_session'
    id = db.Column(db.Integer, primary_key=True)
    pre_expansion_id = db.Column(db.Integer, db.ForeignKey('pre_expansion.id'), nullable=False)
    operator_id = db.Column(db.Integer, db.ForeignKey('operator.id'), nullable=False)
    status = db.Column(db.String(20), default='active')
    started_at = db.Column(db.DateTime, nullable=False)
    ended_at = db.Column(db.DateTime, nullable=True)

class Block(db.Model):
    __tablename__ = 'block'
    id = db.Column(db.Integer, primary_key=True)
    block_session_id = db.Column(db.Integer, db.ForeignKey('block_session.id'), nullable=False)
    block_number = db.Column(db.String(40), nullable=False)
    is_profile16 = db.Column(db.Boolean, default=False)
    weight = db.Column(db.Float, default=0.0)

    def __repr__(self):
        return f"<Block {self.block_number}>"
