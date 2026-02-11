# models/production.py
from models import db
from datetime import datetime

class CuttingProductionRecord(db.Model):
    __tablename__ = 'cutting_production_records'
    id = db.Column(db.Integer, primary_key=True)
    profile_code = db.Column(db.String(10), db.ForeignKey('profiles.code'), nullable=False)
    block_id = db.Column(db.Integer, db.ForeignKey('blocks.id'), nullable=False)
    block_number = db.Column(db.String(20), nullable=False)
    pre_exp_batch_no = db.Column(db.String(50), nullable=False)
    cornices_produced = db.Column(db.Integer, nullable=False)
    wastage = db.Column(db.Integer, nullable=False)
    date_boxed = db.Column(db.DateTime, nullable=True)
    boxes_made = db.Column(db.Integer, nullable=True)
    waste_boxing = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    total_cornices_damaged = db.Column(db.Integer, default=0)

    # DURATION FIELDS (all in minutes)
    pre_expansion_time_min   = db.Column(db.Integer, nullable=True)
    block_making_time_min    = db.Column(db.Integer, nullable=True)
    cutting_time_min         = db.Column(db.Integer, nullable=True)
    boxing_time_min          = db.Column(db.Integer, nullable=True)
    qc_time_min              = db.Column(db.Integer, nullable=True)
    total_production_time_min= db.Column(db.Integer, nullable=True)
    actual_production_time_min = db.Column(db.Integer, nullable=True)

    # PR16 Workflow
    is_boxable = db.Column(db.Boolean, default=False, nullable=False)
    qc_status = db.Column(db.String(20), default='pending')  # 'pending', 'skipped', 'completed'

    # Relationships
    quality_control = db.relationship('QualityControl', back_populates='cutting_production', uselist=False)
    block = db.relationship('Block')
    profile = db.relationship('Profile', backref='cutting_production_records', lazy='joined')

    @property
    def session(self):
        """
        Returns the most recent completed WireCuttingSession for this block/profile.
        Used to fetch the correct 'cut date' (end_time).
        """
        from models.cutting import WireCuttingSession
        return (
            WireCuttingSession.query
            .filter_by(
                block_id=self.block_id,
                profile_code=self.profile_code,
                status='completed'
            )
            .order_by(WireCuttingSession.end_time.desc())
            .first()
        )

    def __repr__(self):
        return (
            f"<CuttingProductionRecord {self.profile_code} Block {self.block_number} "
            f"Produced {self.cornices_produced} Wastage {self.wastage}>"
        )
