from flask import Blueprint, render_template

from utils.authz import manager_required

reports_bp = Blueprint('reports', __name__, template_folder='../../templates/reports')

@reports_bp.route('/production_report')
@manager_required
def production_report():
    # Just a placeholder for now
    return render_template('reports/production_report.html')

@reports_bp.route('/profile_performance')
@manager_required
def profile_performance():
    return render_template('reports/profile_performance.html')

@reports_bp.route('/efficiency_report')
@manager_required
def efficiency_report():
    return render_template('reports/efficiency_report.html')

@reports_bp.route('/lead_time_report')
@manager_required
def lead_time_report():
    return render_template('reports/lead_time_report.html')
