from v2.app import db

class PreExpansion(db.Model):
    __tablename__ = 'pre_expansion'
    id = db.Column(db.Integer, primary_key=True)
    batch_no = db.Column(db.String(40), unique=True, nullable=False)
    density = db.Column(db.Integer, nullable=False)
    purpose = db.Column(db.String(20), nullable=False)  # 'Block' or 'Moulded'
    planned_kg = db.Column(db.Float, default=0.0)
    total_kg_used = db.Column(db.Float, default=0.0)
    status = db.Column(db.String(20), default='completed')  # 'active'/'completed'
    is_used = db.Column(db.Boolean, default=False)

    def __repr__(self):
        return f"<PreExpansion {self.batch_no} {self.density}g/l>"
