from datetime import datetime
from models import db

class PR16Stash(db.Model):
    __tablename__ = "pr16_stash"

    id = db.Column(db.Integer, primary_key=True)
    density = db.Column(db.Float, nullable=False, index=True)          # e.g. 18.0, 23.0
    material_code = db.Column(db.String(20), nullable=False, index=True) # e.g. '501'
    kg_remaining = db.Column(db.Float, nullable=False, default=0.0)    # >0 means still available

    # optional traceability
    source_pre_expansion_id = db.Column(db.Integer, db.ForeignKey("pre_expansions.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    source_pre_expansion = db.relationship("PreExpansion")

    def __repr__(self) -> str:
        return f"<PR16Stash {self.material_code} {self.density}g/l {self.kg_remaining}kg>"
