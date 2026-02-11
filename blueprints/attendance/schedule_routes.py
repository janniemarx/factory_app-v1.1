from __future__ import annotations
from datetime import time
from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required
from .routes import attendance_bp
from models import db
from models.attendance import WorkSchedule


@attendance_bp.route('/attendance/schedules')
@attendance_bp.route('/attendance/schedules', endpoint='schedules')
@login_required
def schedules_list():
	schedules = WorkSchedule.query.order_by(WorkSchedule.is_default.desc(), WorkSchedule.name.asc()).all()
	return render_template('attendance/schedules_list.html', schedules=schedules)


@attendance_bp.route('/attendance/schedules/new', methods=['GET', 'POST'])
@login_required
def schedule_new():
	if request.method == 'POST':
		name = request.form.get('name') or 'Default'
		day_start = request.form.get('day_start') or '07:00'
		day_end = request.form.get('day_end') or '16:00'
		lunch = request.form.get('lunch_minutes', type=int) or 60
		weekly = request.form.get('weekly_normal_seconds', type=int) or (40 * 3600)
		round_min = request.form.get('ot_round_minutes', type=int) or 15
		enabled = request.form.get('enabled') in {'on', '1', 'true'}
		ws = WorkSchedule(
			name=name,
			day_start=time.fromisoformat(day_start),
			day_end=time.fromisoformat(day_end),
			lunch_minutes=lunch,
			weekly_normal_seconds=weekly,
			ot_round_minutes=round_min,
			enabled=enabled,
		)
		db.session.add(ws)
		db.session.commit()
		flash('Schedule created.', 'success')
		return redirect(url_for('attendance.schedules_list'))
	return render_template('attendance/schedule_form.html', schedule=None)


@attendance_bp.route('/attendance/schedules/<int:schedule_id>/edit', methods=['GET', 'POST'])
@login_required
def schedule_edit(schedule_id: int):
	s = WorkSchedule.query.get_or_404(schedule_id)
	if request.method == 'POST':
		s.name = request.form.get('name') or s.name
		s.day_start = time.fromisoformat(request.form.get('day_start') or s.day_start.strftime('%H:%M'))
		s.day_end = time.fromisoformat(request.form.get('day_end') or s.day_end.strftime('%H:%M'))
		s.lunch_minutes = request.form.get('lunch_minutes', type=int) or s.lunch_minutes
		s.weekly_normal_seconds = request.form.get('weekly_normal_seconds', type=int) or s.weekly_normal_seconds
		s.ot_round_minutes = request.form.get('ot_round_minutes', type=int) or s.ot_round_minutes
		s.enabled = request.form.get('enabled') in {'on', '1', 'true'}
		db.session.commit()
		flash('Schedule updated.', 'success')
		return redirect(url_for('attendance.schedules_list'))
	return render_template('attendance/schedule_form.html', schedule=s)
