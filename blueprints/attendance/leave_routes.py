from __future__ import annotations
from datetime import date, datetime
from io import BytesIO
from flask import request, render_template, redirect, url_for, flash, send_file
from flask_login import login_required, current_user

from .routes import attendance_bp
from models import db
from models.attendance import LeaveRequest
from models.operator import Operator
from ..attendance.helpers import parse_date
from utils.leave_pdf import render_leave_pdf
import os
from markupsafe import Markup
from flask_wtf.csrf import generate_csrf
import re
from services.leave_accrual import compute_balances, estimate_request_days


@attendance_bp.route('/attendance/leave')
@login_required
def leave_queue():
	pending = (
		LeaveRequest.query
		.filter(LeaveRequest.status == 'pending')
		.order_by(LeaveRequest.created_at.desc())
		.all()
	)

	download_id = request.args.get('download', type=int)
	return render_template('attendance/leave_queue.html', pending=pending, download_id=download_id)


@attendance_bp.route('/attendance/leave/<int:request_id>', methods=['GET', 'POST'])
@login_required
def leave_review(request_id: int):
	req = LeaveRequest.query.get_or_404(request_id)
	op = req.operator
	balances = compute_balances(op)
	# Estimate requested days (working days in range). Hours per day not used here; we count days for balance.
	requested_days = estimate_request_days(op, req.start_date, req.end_date)
	# Determine available bucket for the type
	available_map = {
		'annual': balances.annual_available,
		'sick': balances.sick_available_cycle,
		'family': balances.family_available_year,
		# unpaid/study do not reduce constrained balances
		'unpaid': float('inf'),
		'study': float('inf'),
	}
	available_for_type = available_map.get(req.leave_type, 0.0)
	is_unlimited = req.leave_type in {'unpaid', 'study'}
	will_be_negative = (not is_unlimited) and (requested_days > available_for_type)

	class Form:
		# lightweight form (we already have CSRF globally)
		def hidden_tag(self):
			# include CSRF token for POST safety
			return Markup(f"<input type='hidden' name='csrf_token' value='{generate_csrf()}'>")
	form = Form()

	if request.method == 'POST':
		decision = request.form.get('decision')
		notes = request.form.get('notes')
		if decision not in {'approved', 'rejected'}:
			flash('Please choose a valid decision.', 'warning')
			return redirect(request.url)
		# Soft warning on insufficient balance
		if decision == 'approved' and will_be_negative:
			flash('Warning: This approval exceeds available leave balance for this type. Proceeding anyway.', 'warning')
		req.status = decision
		req.approved_by_id = current_user.id
		req.approved_at = datetime.utcnow()
		if notes:
			req.notes = (req.notes + '\n' if req.notes else '') + f"Approver: {notes}"
		db.session.commit()
		flash('Leave decision recorded.', 'success')
		return redirect(url_for('attendance.leave_queue', download=req.id if decision == 'approved' else None))

	# Render with a very small WTForms-like shim
	class ReviewForm:
		def hidden_tag(self):
			return Markup(f"<input type='hidden' name='csrf_token' value='{generate_csrf()}'>")
		def request_id(self, value): return ''
		def decision(self, **kwargs):
			return f"<select name='decision' class='{kwargs.get('class','')}'><option value='approved'>Approve</option><option value='rejected'>Reject</option></select>"
		def notes(self, **kwargs):
			return f"<textarea name='notes' class='{kwargs.get('class','')}' rows='{kwargs.get('rows','3')}'></textarea>"
		def submit(self, **kwargs):
			return f"<button class='{kwargs.get('class','btn btn-primary')}'>Submit</button>"
	rf = ReviewForm()
	return render_template(
		'attendance/leave_review.html',
		req=req,
		form=rf,
		balances=balances,
		requested_days=requested_days,
		available_for_type=available_for_type,
		is_unlimited=is_unlimited,
	)


@attendance_bp.route('/attendance/leave/new', methods=['GET', 'POST'])
@login_required
def leave_new():
	# Simple capture: assume manager selects operator and date range
	if request.method == 'POST':
		operator_id = request.form.get('operator_id', type=int)
		leave_type = (request.form.get('leave_type') or '').lower()
		start_date = parse_date(request.form.get('start_date'))
		end_date = parse_date(request.form.get('end_date'))
		hours_per_day = request.form.get('hours_per_day', type=float)
		notes = request.form.get('notes')
		if not operator_id or not start_date or not end_date or not leave_type:
			flash('Missing required fields.', 'warning')
			return redirect(request.url)
		lr = LeaveRequest(
			operator_id=operator_id,
			leave_type=leave_type,
			start_date=start_date,
			end_date=end_date,
			hours_per_day=hours_per_day,
			status='pending',
			created_by_id=current_user.id,
			notes=notes,
		)
		db.session.add(lr)
		db.session.commit()
		flash('Leave captured and sent for approval.', 'success')
		# Trigger immediate PDF view via leave_queue's download hook
		return redirect(url_for('attendance.leave_queue', download=lr.id))

	# GET: render capture form with a minimal WTForms-like shim expected by the template
	operators = Operator.query.filter_by(active=True).order_by(Operator.full_name.asc()).all()

	# Small helper field to expose name/data/choices attributes
	class Field:
		def __init__(self, name, data=None, choices=None):
			self.name = name
			self.data = data
			self.choices = choices or []  # list of (value, label)

	# Build the light-weight form API used by leave_new.html
	class CaptureForm:
		def __init__(self, ops):
			# Prefill selection from query if provided
			pre_id = request.args.get('operator_id') or ''
			choices = [(str(o.id), f"{(o.full_name or o.username)}{f' ({o.emp_no})' if o.emp_no else ''}") for o in ops]
			self.operator_id = Field('operator_id', data=str(pre_id) if pre_id else '', choices=choices)

		def hidden_tag(self):
			return Markup(f"<input type='hidden' name='csrf_token' value='{generate_csrf()}'>")

		def leave_type(self, **k):
			cls = k.get('class', 'form-select')
			id_ = k.get('id', 'leaveType')
			# Common leave types; values are lower-case to match server processing
			options = [
				('annual', 'Annual leave'),
				('sick', 'Sick leave'),
				('family', 'Family responsibility'),
				('unpaid', 'Unpaid leave'),
				('study', 'Study leave'),
			]
			opts_html = ''.join(f"<option value='{val}'>{label}</option>" for val, label in options)
			return Markup(f"<select name='leave_type' id='{id_}' class='{cls}'>{opts_html}</select>")

		def start_date(self, **k):
			from datetime import date as _d
			cls = k.get('class', 'form-control')
			id_ = k.get('id', 'startDate')
			typ = k.get('type', 'date')
			required = ' required' if k.get('required') else ''
			val = request.args.get('start_date') or _d.today().isoformat()
			return Markup(f"<input name='start_date' id='{id_}' class='{cls}' type='{typ}' value='{val}'{required}>")

		def end_date(self, **k):
			from datetime import date as _d
			cls = k.get('class', 'form-control')
			id_ = k.get('id', 'endDate')
			typ = k.get('type', 'date')
			required = ' required' if k.get('required') else ''
			# Default end = start
			start_q = request.args.get('start_date')
			val = request.args.get('end_date') or (start_q or _d.today().isoformat())
			return Markup(f"<input name='end_date' id='{id_}' class='{cls}' type='{typ}' value='{val}'{required}>")

		def notes(self, **k):
			cls = k.get('class', 'form-control')
			rows = k.get('rows', '3')
			return Markup(f"<textarea name='notes' class='{cls}' rows='{rows}'></textarea>")

		def submit(self, **k):
			cls = k.get('class', 'btn btn-primary')
			return Markup(f"<button class='{cls}'>Capture</button>")

	form = CaptureForm(operators)
	return render_template('attendance/leave_new.html', form=form)


@attendance_bp.route('/attendance/payroll/leave')
@login_required
def payroll_leave_queue():
	sd = parse_date(request.args.get('start_date'))
	ed = parse_date(request.args.get('end_date'))
	q = LeaveRequest.query.filter(LeaveRequest.status == 'approved')
	if sd:
		q = q.filter(LeaveRequest.start_date >= sd)
	if ed:
		q = q.filter(LeaveRequest.end_date <= ed)
	rows = q.order_by(LeaveRequest.approved_at.desc().nullslast(), LeaveRequest.created_at.desc()).all()
	return render_template('attendance/payroll_leave_queue.html', rows=rows, sd=sd, ed=ed)


@attendance_bp.route('/attendance/payroll/leave/<int:request_id>', methods=['GET', 'POST'])
@login_required
def payroll_leave_review(request_id: int):
	lr = LeaveRequest.query.get_or_404(request_id)
	class Form:
		def hidden_tag(self):
			return Markup(f"<input type='hidden' name='csrf_token' value='{generate_csrf()}'>")
		def request_id(self, value): return ''
		def notes(self, **kwargs):
			return f"<textarea name='notes' class='{kwargs.get('class','')}' rows='{kwargs.get('rows','3')}'></textarea>"
		def submit(self, **kwargs):
			return f"<button class='{kwargs.get('class','btn btn-primary')}'>Mark Captured</button>"
	form = Form()
	if request.method == 'POST':
		notes = request.form.get('notes')
		if notes:
			lr.notes = (lr.notes + '\n' if lr.notes else '') + f"Payroll: {notes}"
		lr.payroll_captured_at = datetime.utcnow()
		lr.payroll_captured_by_id = current_user.id
		db.session.commit()
		flash('Marked as captured for payroll.', 'success')
		return redirect(url_for('attendance.payroll_leave_queue'))
	return render_template('attendance/payroll_leave_review.html', lr=lr, form=form)


@attendance_bp.route('/attendance/leave/balances')
@login_required
def leave_balances():
	name_like = (request.args.get('name_like') or '').strip()
	room_number = request.args.get('room_number', type=int)
	q = Operator.query.filter(Operator.active.is_(True))
	if room_number is not None:
		q = q.filter(Operator.room_number == room_number)
	if name_like:
		like = f"%{name_like}%"
		q = q.filter((Operator.full_name.ilike(like)) | (Operator.username.ilike(like)) | (Operator.emp_no.ilike(like)))
	ops = q.order_by(Operator.full_name.asc().nullslast(), Operator.username.asc()).all()

	rows = []
	for op in ops:
		b = compute_balances(op)
		rows.append((op, b))
	# Minimal filter form shims for template
	class FilterForm:
		def hidden_tag(self): return ''
	return render_template('attendance/leave_balances.html', rows=rows, name_like=name_like, room_number=room_number, form=FilterForm())


@attendance_bp.route('/attendance/leave/<int:request_id>/print')
@login_required
def leave_print(request_id: int):
	lr = LeaveRequest.query.get_or_404(request_id)
	operator = lr.operator
	template_path = os.path.join('static', 'files', '62 - Application for leave.pdf')
	full_template = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), template_path)
	# The above climbs from blueprints/attendance to project root; build abs path
	full_template = os.path.abspath(full_template)

	pdf = render_leave_pdf(
		template_path=full_template,
		employee_name=(operator.full_name or operator.username) if operator else '—',
		application_date=(lr.approved_at or lr.created_at).date(),
		leave_type=lr.leave_type,
		start_date=lr.start_date,
		end_date=lr.end_date,
		hours_per_day=lr.hours_per_day,
		comments=lr.notes or None,
	)
	# Build a friendly download filename: <EmployeeName>_<CapturedDate>_leave.pdf
	name_raw = (operator.full_name or operator.username or operator.emp_no or 'employee') if operator else 'employee'
	name_clean = re.sub(r'[^A-Za-z0-9._-]+', '_', name_raw).strip('_')
	name_clean = re.sub(r'_+', '_', name_clean)
	date_str = (lr.created_at or datetime.utcnow()).strftime('%Y-%m-%d')
	filename = f"{name_clean}_{date_str}_leave.pdf"
	return send_file(pdf, as_attachment=True, download_name=filename, mimetype='application/pdf')
