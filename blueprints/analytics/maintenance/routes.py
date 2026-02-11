from flask import Blueprint, render_template
from flask_login import login_required
from datetime import datetime
from .forms import MaintenanceAnalyticsFilterForm
from .helpers import get_maintenance_analytics
from models.operator import Operator

maintenance_analytics_bp = Blueprint(
    'maintenance_analytics', __name__,
    template_folder='../../templates/analytics/maintenance'
)

@maintenance_analytics_bp.route('/analytics', methods=['GET','POST'])
@login_required
def dashboard():
    form = MaintenanceAnalyticsFilterForm()
    techs = Operator.query.order_by(Operator.full_name).all()
    form.technician_id.choices = [(0,'All')] + [(t.id, t.full_name or t.username) for t in techs]
    technician_id = None
    status = None
    date_from = None
    date_to = None
    if form.validate_on_submit():
        technician_id = form.technician_id.data or None
        if technician_id == 0: technician_id = None
        status = form.status.data or None
        date_from = form.date_from.data
        date_to = form.date_to.data
    analytics = get_maintenance_analytics(technician_id, status, date_from, date_to)
    return render_template('analytics/maintenance/dashboard.html', form=form, analytics=analytics, now=datetime.utcnow())
