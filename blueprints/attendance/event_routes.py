from flask_login import login_required
from .routes import attendance_bp


@attendance_bp.route('/attendance/events/manual', methods=['GET', 'POST'])
@attendance_bp.route('/attendance/events/manual', methods=['GET', 'POST'], endpoint='manual_event')
@login_required
def manual_event():
	# TODO: implement manual event form
	return ''
