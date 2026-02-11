from flask import render_template
from flask_login import login_required
from .routes import attendance_bp


@attendance_bp.route('/attendance')
@login_required
def dashboard():
	return render_template('attendance/overtime_report.html', rows=[], filters_applied=False, start_date=None, end_date=None, room_choices=[('None','All rooms')], room_value='None')
