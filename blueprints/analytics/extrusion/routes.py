from flask import Blueprint, render_template, request
from utils.authz import manager_required
from datetime import datetime, timedelta
from .forms import ExtrusionAnalyticsFilterForm
from .helpers import get_extrusion_analytics
from models.extrusion import ExtrusionSession
from models import db

extrusion_analytics_bp = Blueprint(
    'extrusion_analytics', __name__,
    template_folder='../../templates/analytics/extrusion'
)

@extrusion_analytics_bp.route('/analytics', methods=['GET', 'POST'])
@manager_required
def dashboard():
    from models.extrusion import Extruder, ExtrudedProfile
    form = ExtrusionAnalyticsFilterForm()
    extruders = Extruder.query.order_by(Extruder.name).all()
    profiles = ExtrudedProfile.query.order_by(ExtrudedProfile.code).all()
    form.extruder_id.choices = [(0, '--All Extruders--')] + [(e.id, e.name) for e in extruders]
    form.profile_id.choices = [(0, '--All Profiles--')] + [(p.id, p.code) for p in profiles]
    extruder_id = None
    profile_id = None
    date_from = None
    date_to = None
    if form.validate_on_submit():
        extruder_id = form.extruder_id.data or None
        if extruder_id == 0: extruder_id = None
        profile_id = form.profile_id.data or None
        if profile_id == 0: profile_id = None
        date_from = form.date_from.data
        date_to = form.date_to.data
    analytics = get_extrusion_analytics(extruder_id, profile_id, date_from, date_to)
    return render_template('analytics/extrusion/dashboard.html', form=form, analytics=analytics, now=datetime.utcnow())
