from datetime import date, datetime, timedelta
from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from sqlalchemy import and_, not_, exists
from .routes import attendance_bp
from .helpers import parse_date, room_filter_choices
from .db_helpers import add_manual_event, recompute_day, recompute_range, propose_overtime_for_range
from .helpers import iso_monday
from models import db
from models.attendance import AttendanceDaily, LeaveRequest
from models.operator import Operator
from markupsafe import Markup
from services.leave_accrual import compute_balances, estimate_request_days


@attendance_bp.route('/attendance/exceptions')
@login_required
def exceptions_list():
	# Filters
	sd = parse_date(request.args.get('start_date'))
	ed = parse_date(request.args.get('end_date'))
	op_filter = request.args.get('operator_id', type=int)
	room = request.args.get('room_number')
	try:
		room = int(room) if room not in (None, '', 'None') else None
	except Exception:
		room = None
	name_like = request.args.get('name_like')

	# Proactively recompute for the filtered scope to surface no-punch weekdays as exceptions
	# (days with no device events otherwise have no AttendanceDaily rows and won't appear).
	try:
		if sd and ed:
			op_ids: list[int] = []
			ops_q = None
			if op_filter:
				ops_q = Operator.query.filter(Operator.id == op_filter)
			elif room is not None:
				ops_q = Operator.query.filter(Operator.room_number == room)
			elif name_like:
				like = f"%{name_like}%"
				ops_q = Operator.query.filter((Operator.full_name.ilike(like)) | (Operator.username.ilike(like)))
			# Only recompute when a scope is provided to avoid heavy all-operator passes
			if ops_q is not None:
				op_ids = [op.id for op in ops_q.all()]
				if op_ids:
					recompute_range(sd, ed, operator_ids=op_ids)
	except Exception:
		# best-effort; ignore errors and continue with existing rows
		pass
	q = AttendanceDaily.query
	if sd:
		q = q.filter(AttendanceDaily.day >= sd)
	if ed:
		q = q.filter(AttendanceDaily.day <= ed)
	if op_filter:
		q = q.filter(AttendanceDaily.operator_id == op_filter)
	if room is not None:
		q = q.join(Operator).filter(Operator.room_number == room)
	if name_like:
		like = f"%{name_like}%"
		q = q.join(Operator).filter((Operator.full_name.ilike(like)) | (Operator.username.ilike(like)))
	# Exception heuristics: include
	# - Missing IN/OUT
	# - Zero segments
	# - Missing first_in/last_out
	# These will keep weekdays with no punches visible so that leave can be captured.
	q = q.filter(
		(AttendanceDaily.missing_in.is_(True)) |
		(AttendanceDaily.missing_out.is_(True)) |
		(AttendanceDaily.segment_count == 0) |
		(AttendanceDaily.first_in.is_(None)) |
		(AttendanceDaily.last_out.is_(None))
	)
	# Exclude dates explicitly marked as NO_FRI_NIGHT or NO_NIGHT in notes
	q = q.filter((AttendanceDaily.notes.is_(None)) | (not_(AttendanceDaily.notes.ilike('%NO_FRI_NIGHT%'))))
	q = q.filter((AttendanceDaily.notes.is_(None)) | (not_(AttendanceDaily.notes.ilike('%NO_NIGHT%'))))
	
	# Get all potential exceptions first
	all_exceptions = q.all()

	# Manually filter:
	# - Exclude weekends with no punches (common schedule) unless leave is present (we still exclude as it’s not an exception to fix)
	# - Exclude days fully covered by approved leave (already handled)
	items = []
	for exc in all_exceptions:
		is_weekend = exc.day.weekday() >= 5
		no_punches = (exc.segment_count or 0) == 0 and (exc.first_in is None) and (exc.last_out is None)
		has_leave = LeaveRequest.query.filter(
			LeaveRequest.operator_id == exc.operator_id,
			LeaveRequest.status == 'approved',
			LeaveRequest.start_date <= exc.day,
			LeaveRequest.end_date >= exc.day
		).first()

		# Exclude weekends (Sat/Sun) where nothing happened and there is no leave to capture
		if is_weekend and no_punches:
			continue
		# Exclude if already on approved leave
		if has_leave:
			continue
		items.append(exc)

	class _Field:
		def __init__(self, name: str, data, renderer):
			self.name = name
			self.data = data
			self._renderer = renderer
		def __call__(self, **k):
			return Markup(self._renderer(**k))
		def label(self, **k):
			# simple passthrough; template prints its own text
			return ''

	def _render_date_input(field_name: str, value: str):
		def _r(**k):
			cls = k.get('class', 'form-control')
			typ = k.get('type', 'date')
			return f"<input type='{typ}' name='{field_name}' class='{cls}' value='{value}'>"
		return _r

	def _render_room_select():
		opts = []
		for v, lbl in room_filter_choices():
			val = '' if v is None else str(v)
			sel = ' selected' if ((room is None and v is None) or (v == room)) else ''
			opts.append(f"<option value='{val}'{sel}>{lbl}</option>")
		html = f"<select name='room_number' class='form-select'>{''.join(opts)}</select>"
		return lambda **k: Markup(html.replace("class='form-select'", f"class='{k.get('class','form-select')}'"))

	def _render_text_input(field_name: str, value: str):
		def _r(**k):
			ph = k.get('placeholder','')
			cls = k.get('class','form-control')
			return f"<input name='{field_name}' class='{cls}' value='{value or ''}' placeholder='{ph}'>"
		return _r

	filter_form = type('FilterForm', (), {})()
	setattr(filter_form, 'start_date', _Field('start_date', sd, _render_date_input('start_date', sd.isoformat() if sd else '')))
	setattr(filter_form, 'end_date', _Field('end_date', ed, _render_date_input('end_date', ed.isoformat() if ed else '')))
	setattr(filter_form, 'room_number', _Field('room_number', room, _render_room_select()))
	setattr(filter_form, 'name_like', _Field('name_like', name_like, _render_text_input('name_like', name_like or '')))

	return render_template('attendance/exceptions_list.html', items=items, filter_form=filter_form, operator_id_filter=op_filter, download_id=None)


@attendance_bp.route('/attendance/exception/fix', methods=['GET', 'POST'])
@login_required
def exception_fix():
	print("=== EXCEPTION_FIX ROUTE HIT ===")
	operator_id = request.args.get('operator_id', type=int) or request.form.get('operator_id', type=int)
	day_iso = request.args.get('day_iso') or request.form.get('day')
	day = parse_date(day_iso) or date.today()
	
	# Capture return URL context
	return_to = request.args.get('return_to') or request.form.get('return_to')
	start_date = request.args.get('start_date') or request.form.get('start_date')
	end_date = request.args.get('end_date') or request.form.get('end_date') 
	room_number = request.args.get('room_number') or request.form.get('room_number')
	exceptions_only = request.args.get('exceptions_only') or request.form.get('exceptions_only')
	
	print(f"DEBUG: Context - return_to='{return_to}', start_date='{start_date}', end_date='{end_date}', room_number='{room_number}'")
	
	op = Operator.query.get_or_404(operator_id)
	daily = AttendanceDaily.query.filter_by(operator_id=op.id, day=day).one_or_none()

	# Compute current balances for context on the page
	balances = compute_balances(op)

	class Form:
		def hidden_tag(self):
			from flask_wtf.csrf import generate_csrf
			return Markup(f"<input type='hidden' name='csrf_token' value='{generate_csrf()}'>")
		def operator_id(self):
			return Markup(f"<input type='hidden' name='operator_id' value='{op.id}'>")
		def day(self):
			return Markup(f"<input type='hidden' name='day' value='{day.isoformat()}'>")
		def return_to(self):
			return Markup(f"<input type='hidden' name='return_to' value='{return_to or ''}'>")
		def start_date(self):
			return Markup(f"<input type='hidden' name='start_date' value='{start_date or ''}'>")
		def end_date(self):
			return Markup(f"<input type='hidden' name='end_date' value='{end_date or ''}'>")
		def room_number(self):
			return Markup(f"<input type='hidden' name='room_number' value='{room_number or ''}'>")
		def leave_type(self, **k):
			# basic list
			options = ['annual','sick','unpaid','family','special']
			return Markup("<select name='leave_type' class='form-select' id='leaveType'>" + ''.join(f"<option value='{x}'>{x.title()}</option>" for x in options) + "</select>")
		def add_in(self, **k):
			return Markup(f"<input name='add_in' class='{k.get('class','form-control')}' id='addIn' value=''>")
		def add_out(self, **k):
			return Markup(f"<input name='add_out' class='{k.get('class','form-control')}' id='addOut' value=''>")
		def reason(self, **k):
			rows = k.get('rows','3')
			cls = k.get('class','form-control')
			return Markup(f"<textarea name='reason' class='{cls}' rows='{rows}' id='reason'></textarea>")
		def no_friday_night(self, **k):
			return Markup(f"<input type='checkbox' name='no_friday_night' class='{k.get('class','form-check-input')}' id='no-fri'>")
		def no_night(self, **k):
			return Markup(f"<input type='checkbox' name='no_night' class='{k.get('class','form-check-input')}' id='{k.get('id','no-night')}'>")
		def submit(self, **k):
			return Markup(f"<button class='{k.get('class','btn btn-primary')}' id='btnApply'>Apply</button>")

	if request.method == 'POST':
		print(f"DEBUG: POST received - return_to='{return_to}', mode='{request.form.get('mode')}'")
		mode = request.form.get('mode')  # 'leave' or 'adjust'
		reason = (request.form.get('reason') or '').strip()
		if not reason:
			flash('Reason is required.', 'warning')
			return redirect(request.url)

		# Optional: mark "No night shift" for this date and rebalance the week
		no_night_flag = (request.form.get('no_friday_night') in ('on','1','true','yes')) or (request.form.get('no_night') in ('on','1','true','yes'))
		if no_night_flag:
			if not daily:
				daily = AttendanceDaily(operator_id=op.id, day=day)
				db.session.add(daily)
			stamp = 'NO_NIGHT'
			notes = (daily.notes or '')
			if stamp not in notes:
				daily.notes = (notes + '\n' if notes else '') + stamp + (f" — {reason}" if reason else '')
			db.session.commit()
			# Recompute + propose for the ISO week
			week_start = iso_monday(day)
			week_end = week_start + timedelta(days=6)
			recompute_range(week_start, week_end, operator_ids=[op.id])
			propose_overtime_for_range(week_start, week_end, operator_ids=[op.id])
			db.session.commit()
			flash('Marked as No night shift for this date; week rebalanced and overtime proposals updated.', 'success')
			# Redirect back immediately (no need to enforce leave/adjust)
			if return_to == 'overtime_queue':
				return redirect(url_for('attendance.overtime_queue', start_date=start_date, end_date=end_date, room_number=room_number, exceptions_only=exceptions_only))
			else:
				return redirect(url_for('attendance.exceptions_list', start_date=start_date, end_date=end_date, room_number=room_number))
		if mode == 'leave':
			leave_type = (request.form.get('leave_type') or '').lower()
			leave_from = parse_date(request.form.get('leave_from')) or day
			leave_to = parse_date(request.form.get('leave_to')) or leave_from
			hours_txt = (request.form.get('leave_hours') or '').strip()
			hours_per_day = float(hours_txt) if hours_txt else (0.0 if leave_type == 'unpaid' else 8.0)
			# Soft check: warn if exceeding balance for annual/sick/family
			req_days = estimate_request_days(op, leave_from, leave_to)
			avail = {
				'annual': balances.annual_available,
				'sick': balances.sick_available_cycle,
				'family': balances.family_available_year,
			}.get(leave_type, float('inf'))
			if avail != float('inf') and req_days > avail:
				flash(f"Warning: Requested {req_days:.2f} days exceeds available {leave_type} balance ({avail:.2f}). Proceeding.", 'warning')
			lr = LeaveRequest(
				operator_id=op.id,
				leave_type=leave_type,
				start_date=leave_from,
				end_date=leave_to,
				hours_per_day=hours_per_day,
				status='approved',
				created_by_id=current_user.id,
				approved_by_id=current_user.id,
				approved_at=datetime.utcnow(),
				notes=f"Exception fix: {reason}",
			)
			db.session.add(lr)
			db.session.commit()
			# Annotate daily notes for each day in the leave range (within the selected week) to show reason in export comments
			try:
				cur = leave_from
				while cur <= leave_to:
					dly = AttendanceDaily.query.filter_by(operator_id=op.id, day=cur).one_or_none()
					if not dly:
						dly = AttendanceDaily(operator_id=op.id, day=cur)
						db.session.add(dly)
					existing = (dly.notes or '').strip()
					stamp = f"[Leave] {reason}"
					if stamp not in existing:
						dly.notes = (existing + '\n' if existing else '') + stamp
					cur += timedelta(days=1)
				db.session.commit()
			except Exception:
				pass
			flash('Leave recorded.', 'success')
			
			# Determine redirect destination based on context
			if return_to == 'overtime_queue':
				redirect_url = url_for('attendance.overtime_queue', start_date=start_date, end_date=end_date, room_number=room_number, exceptions_only=exceptions_only)
				print(f"DEBUG: Redirecting to overtime_queue: {redirect_url}")
				return redirect(redirect_url)
			else:
				redirect_url = url_for('attendance.exceptions_list', start_date=start_date, end_date=end_date, room_number=room_number, download=lr.id)
				print(f"DEBUG: Redirecting to exceptions_list: {redirect_url}")
				return redirect(redirect_url)
		else:
			# Adjust: add missing in/out then recompute
			add_in = (request.form.get('add_in') or '').strip()
			add_out = (request.form.get('add_out') or '').strip()
			if add_in:
				add_manual_event(op, day, add_in, 'check_in', source='adjust')
			if add_out:
				add_manual_event(op, day, add_out, 'check_out', source='adjust')
			db.session.commit()
			# Persist the reason on the daily record so exports can show it
			try:
				daily_note_target = AttendanceDaily.query.filter_by(operator_id=op.id, day=day).one_or_none()
				if not daily_note_target:
					daily_note_target = AttendanceDaily(operator_id=op.id, day=day)
					db.session.add(daily_note_target)
				existing = (daily_note_target.notes or '').strip()
				stamp = f"[Exceptions] {reason}"
				if stamp not in existing:
					daily_note_target.notes = (existing + '\n' if existing else '') + stamp
				db.session.commit()
			except Exception:
				pass
			recompute_day(op, day)
			db.session.commit()
			flash('Attendance adjusted.', 'success')
			
			# Determine redirect destination based on context
			if return_to == 'overtime_queue':
				redirect_url = url_for('attendance.overtime_queue', start_date=start_date, end_date=end_date, room_number=room_number, exceptions_only=exceptions_only)
				print(f"DEBUG: Redirecting to overtime_queue: {redirect_url}")
				return redirect(redirect_url)
			else:
				redirect_url = url_for('attendance.exceptions_list', start_date=start_date, end_date=end_date, room_number=room_number)
				print(f"DEBUG: Redirecting to exceptions_list: {redirect_url}")
				return redirect(redirect_url)

	return render_template('attendance/exception_fix.html', daily=daily, op=op, day=day, form=Form(), balances=balances)


@attendance_bp.route('/attendance/exception/mark_no_night', methods=['POST'])
@login_required
def exception_mark_no_night():
	operator_id = request.form.get('operator_id', type=int)
	day_iso = request.form.get('day_iso')
	day = parse_date(day_iso) or date.today()

	# Preserve filters
	start_date = request.form.get('start_date')
	end_date = request.form.get('end_date')
	room_number = request.form.get('room_number')
	return_to = request.form.get('return_to')
	next_url = request.form.get('next')
	exceptions_only = request.form.get('exceptions_only')

	op = Operator.query.get_or_404(operator_id)
	daily = AttendanceDaily.query.filter_by(operator_id=op.id, day=day).one_or_none()
	if not daily:
		daily = AttendanceDaily(operator_id=op.id, day=day)
		db.session.add(daily)

	if 'NO_NIGHT' not in (daily.notes or ''):
		daily.notes = ((daily.notes + '\n') if daily.notes else '') + 'NO_NIGHT — quick mark'
	db.session.commit()

	# Recompute week and regenerate OT proposals
	wk = iso_monday(day)
	recompute_range(wk, wk + timedelta(days=6), operator_ids=[op.id])
	propose_overtime_for_range(wk, wk + timedelta(days=6), operator_ids=[op.id])
	db.session.commit()

	flash('Marked as No night shift for this date. Week rebalanced and OT proposals updated.', 'success')
	if return_to == 'overtime_queue' and start_date and end_date:
		return redirect(url_for('attendance.overtime_queue', start_date=start_date, end_date=end_date, room_number=room_number, exceptions_only=exceptions_only))
	# Fall back to exceptions list, or next if provided
	if next_url:
		return redirect(next_url)
	return redirect(url_for('attendance.exceptions_list', start_date=start_date, end_date=end_date, room_number=room_number))
