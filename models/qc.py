from datetime import datetime
from models import db

class QualityControl(db.Model):
    __tablename__ = "quality_control"

    id = db.Column(db.Integer, primary_key=True)
    cutting_production_id = db.Column(db.Integer, db.ForeignKey('cutting_production_records.id'), nullable=False, unique=True)
    cornices_count_operator = db.Column(db.Integer, nullable=False)    # From operator at cut
    cornices_count_qc = db.Column(db.Integer, nullable=False)          # Counted by QC
    bad_cornices_count = db.Column(db.Integer, nullable=False, default=0)
    good_cornices_count = db.Column(db.Integer, nullable=False)        # After bad separated
    rated_areo_effect = db.Column(db.Integer, nullable=False)   # 1-10
    rated_eps_binding = db.Column(db.Integer, nullable=False)   # 1-10
    rated_wetspots = db.Column(db.Integer, nullable=False)      # 1-10
    rated_dryness = db.Column(db.Integer, nullable=False)       # 1-10
    rated_lines = db.Column(db.Integer, nullable=False)         # 1-10
    qc_done_by = db.Column(db.Integer, db.ForeignKey('operators.id'), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    is_boxing_ready = db.Column(db.Boolean, default=False, nullable=False)

    # Relationships (if you want to easily access)
    cutting_production = db.relationship('CuttingProductionRecord', back_populates='quality_control', uselist=False)
    qc_operator = db.relationship('Operator')


