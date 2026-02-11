from __future__ import annotations
from datetime import date
from io import BytesIO
import pandas as pd
from flask import request, render_template, send_file, redirect, url_for, flash, current_app
from flask_login import login_required, current_user
from .routes import attendance_bp
from .helpers import parse_date, room_filter_choices, week_bounds_from_any
from .db_helpers import propose_overtime_for_range, recompute_range
from models.attendance import NightWeekPlan, LeaveRequest
from datetime import timedelta
from models.operator import Operator
from models.attendance import AttendanceDaily, OvertimeRequest, WorkSchedule, AttendanceEvent
from models import db
from datetime import datetime


@attendance_bp.route('/attendance/overtime/report')
@login_required
def overtime_report():
	start_date = parse_date(request.args.get('start_date'))
	end_date = parse_date(request.args.get('end_date'))
	room_value = request.args.get('room_number')
	try:
		room_value = int(room_value) if room_value not in (None, '', 'None') else None
	except Exception:
		room_value = None

	filters_applied = bool(start_date and end_date)
	rows = []
	block_reason = None
	exceptions_count = 0
	pending_count = 0
	if filters_applied:
		# Enforce: do not allow generating report when there are outstanding exceptions or pending OT
		# Compute exception count (reuse same heuristics as exceptions_list, excluding approved leave and weekend no-punch)
		exc_q = AttendanceDaily.query.filter(AttendanceDaily.day >= start_date, AttendanceDaily.day <= end_date)
		if room_value is not None:
			exc_q = exc_q.join(Operator).filter(Operator.room_number == room_value)
		# Heuristics
		from sqlalchemy import or_, and_, not_
		exc_q = exc_q.filter(
			or_(
				AttendanceDaily.missing_in.is_(True),
				AttendanceDaily.missing_out.is_(True),
				AttendanceDaily.segment_count == 0,
				AttendanceDaily.first_in.is_(None),
				AttendanceDaily.last_out.is_(None),
			)
		)
		# Exclude dates marked as NO_NIGHT/NO_FRI_NIGHT
		exc_q = exc_q.filter((AttendanceDaily.notes.is_(None)) | (not_(AttendanceDaily.notes.ilike('%NO_FRI_NIGHT%'))))
		exc_q = exc_q.filter((AttendanceDaily.notes.is_(None)) | (not_(AttendanceDaily.notes.ilike('%NO_NIGHT%'))))
		exc_rows = exc_q.all()
		# Manually filter out approved leave days and weekend no-punch
		exceptions_count = 0
		for dly in exc_rows:
			# approved leave?
			has_leave = LeaveRequest.query.filter(
				LeaveRequest.operator_id == dly.operator_id,
				LeaveRequest.status == 'approved',
				LeaveRequest.start_date <= dly.day,
				LeaveRequest.end_date >= dly.day,
			).first()
			is_weekend = dly.day.weekday() >= 5
			no_punches = (dly.segment_count or 0) == 0 and (dly.first_in is None) and (dly.last_out is None)
			if not has_leave and not (is_weekend and no_punches):
				exceptions_count += 1

		# Pending overtime requests in the range
		pend_q = OvertimeRequest.query.filter(
			OvertimeRequest.day >= start_date,
			OvertimeRequest.day <= end_date,
			OvertimeRequest.status == 'pending',
		)
		if room_value is not None:
			pend_q = pend_q.join(Operator, Operator.id == OvertimeRequest.operator_id).filter(Operator.room_number == room_value)
		pending_count = pend_q.count()

		if exceptions_count > 0 or pending_count > 0:
			block_reason = f"Blocked: {exceptions_count} exceptions and {pending_count} pending overtime need attention."

		# Only build rows if not blocked
		if not block_reason:
			# Use approved overtime data from OvertimeRequest table, not raw AttendanceDaily
			q = OvertimeRequest.query
			q = q.filter(OvertimeRequest.day >= start_date, OvertimeRequest.day <= end_date)
			q = q.filter(OvertimeRequest.status == 'approved')  # Only show approved overtime
			if room_value is not None:
				q = q.join(Operator, Operator.id == OvertimeRequest.operator_id).filter(Operator.room_number == room_value)
			approved_ots = q.all()

			by_op = {}
			for ot in approved_ots:
				op = ot.operator
				key = ot.operator_id
				rec = by_op.setdefault(key, {
					'code': op.emp_no or '-',
					'name': op.full_name or op.username,
					'is_night': bool(op.is_night_shift),
					'mon_base': 0, 'mon_over': 0,
					'tue_base': 0, 'tue_over': 0,
					'wed_base': 0, 'wed_over': 0,
					'thu_base': 0, 'thu_over': 0,
					'fri_base': 0, 'over_fri': 0,
					'total_n': 0, 'total_o': 0,
					'night_shift': 0,
					'notes': '',
				})
				wd = ot.day.weekday()
				approved_h = float(ot.hours or 0.0)

				# Add normal hours from AttendanceDaily for the same day (if any)
				daily = AttendanceDaily.query.filter_by(operator_id=ot.operator_id, day=ot.day).first()
				base_h = (daily.normal_seconds or 0) / 3600.0 if daily else 0.0

				if wd == 0:
					rec['mon_base'] += round(base_h, 2); rec['mon_over'] += round(approved_h, 2)
				elif wd == 1:
					rec['tue_base'] += round(base_h, 2); rec['tue_over'] += round(approved_h, 2)
				elif wd == 2:
					rec['wed_base'] += round(base_h, 2); rec['wed_over'] += round(approved_h, 2)
				elif wd == 3:
					rec['thu_base'] += round(base_h, 2); rec['thu_over'] += round(approved_h, 2)
				elif wd == 4:
					rec['fri_base'] += round(base_h, 2); rec['over_fri'] += round(approved_h, 2)
				rec['total_n'] += round(base_h, 2)
				rec['total_o'] += round(approved_h, 2)
			rows = list(by_op.values())

	room_choices = [(str(v) if v is not None else 'None', label) for v, label in room_filter_choices()]
	return render_template('attendance/overtime_report.html',
						   rows=rows,
						   start_date=start_date, end_date=end_date,
						   room_choices=room_choices, room_value=(str(room_value) if room_value is not None else 'None'),
						   filters_applied=filters_applied,
						   block_reason=block_reason,
						   exceptions_count=exceptions_count,
						   pending_count=pending_count)


@attendance_bp.route('/attendance/overtime/report/export')
@login_required
def overtime_report_export():
	start_date = parse_date(request.args.get('start_date'))
	end_date = parse_date(request.args.get('end_date'))
	room_value = request.args.get('room_number')
	try:
		room_value = int(room_value) if room_value not in (None, '', 'None') else None
	except Exception:
		room_value = None

	if not (start_date and end_date):
		# Return empty workbook
		buf = BytesIO()
		with pd.ExcelWriter(buf, engine='xlsxwriter') as writer:
			pd.DataFrame().to_excel(writer, index=False)
		buf.seek(0)
		return send_file(buf, as_attachment=True, download_name='overtime.xlsx', mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

	# Block export when there are outstanding exceptions or pending overtime
	room_value_raw = request.args.get('room_number')
	try:
		room_value2 = int(room_value_raw) if room_value_raw not in (None, '', 'None') else None
	except Exception:
		room_value2 = None

	exc_q = AttendanceDaily.query.filter(AttendanceDaily.day >= start_date, AttendanceDaily.day <= end_date)
	if room_value2 is not None:
		exc_q = exc_q.join(Operator).filter(Operator.room_number == room_value2)
	from sqlalchemy import or_, not_
	exc_q = exc_q.filter(
		or_(
			AttendanceDaily.missing_in.is_(True),
			AttendanceDaily.missing_out.is_(True),
			AttendanceDaily.segment_count == 0,
			AttendanceDaily.first_in.is_(None),
			AttendanceDaily.last_out.is_(None),
		)
	)
	exc_q = exc_q.filter((AttendanceDaily.notes.is_(None)) | (not_(AttendanceDaily.notes.ilike('%NO_FRI_NIGHT%'))))
	exc_q = exc_q.filter((AttendanceDaily.notes.is_(None)) | (not_(AttendanceDaily.notes.ilike('%NO_NIGHT%'))))
	exc_rows = exc_q.all()
	exceptions_count = 0
	for dly in exc_rows:
		has_leave = LeaveRequest.query.filter(
			LeaveRequest.operator_id == dly.operator_id,
			LeaveRequest.status == 'approved',
			LeaveRequest.start_date <= dly.day,
			LeaveRequest.end_date >= dly.day,
		).first()
		is_weekend = dly.day.weekday() >= 5
		no_punches = (dly.segment_count or 0) == 0 and (dly.first_in is None) and (dly.last_out is None)
		if not has_leave and not (is_weekend and no_punches):
			exceptions_count += 1

	pend_q = OvertimeRequest.query.filter(
		OvertimeRequest.day >= start_date,
		OvertimeRequest.day <= end_date,
		OvertimeRequest.status == 'pending',
	)
	if room_value2 is not None:
		pend_q = pend_q.join(Operator, Operator.id == OvertimeRequest.operator_id).filter(Operator.room_number == room_value2)
	pending_count = pend_q.count()

	if exceptions_count > 0 or pending_count > 0:
		flash(f"Overtime export blocked: resolve {exceptions_count} exceptions and {pending_count} pending overtime first.", 'warning')
		return redirect(url_for('attendance.overtime_report', start_date=start_date.isoformat(), end_date=end_date.isoformat(), room_number=(str(room_value2) if room_value2 is not None else 'None')))

	# Build a two-sheet workbook: Summary (per operator, week layout) + Clocking (raw In/Out per day)
	# Determine the target work week using the start_date provided
	mon = week_bounds_from_any(start_date)[0]
	tue = mon + timedelta(days=1)
	wed = mon + timedelta(days=2)
	thu = mon + timedelta(days=3)
	fri = mon + timedelta(days=4)
	prev_fri = mon - timedelta(days=3)
	prev_sat = mon - timedelta(days=2)
	week_days = [prev_fri, prev_sat, mon, tue, wed, thu, fri]

	# Filter operators by room (active only)
	op_q = Operator.query.filter(Operator.active.is_(True))
	if room_value is not None:
		op_q = op_q.filter(Operator.room_number == room_value)
	ops = op_q.order_by(Operator.full_name.asc(), Operator.username.asc()).all()

	# Helpers: schedule and rounding
	def _get_default_schedule():
		try:
			return WorkSchedule.query.filter_by(is_default=True, enabled=True).first()
		except Exception:
			return None
	SCHED = _get_default_schedule()
	def _apply_rounding_hours(hours: float) -> float:
		step = int(getattr(SCHED, 'ot_round_minutes', 15) or 15)
		m = int(round(float(hours or 0.0) * 60))
		m = (m // step) * step
		return round(m / 60.0, 2)

	# AttendanceDaily index by (op_id, day)
	dly_q = AttendanceDaily.query.filter(AttendanceDaily.day >= prev_fri, AttendanceDaily.day <= fri)
	if room_value is not None:
		dly_q = dly_q.join(Operator, Operator.id == AttendanceDaily.operator_id).filter(Operator.room_number == room_value)
	dlies = dly_q.all()
	dly_by_key = {(d.operator_id, d.day): d for d in dlies}

	# Night plan by operator for Mon..Thu (optional; can be disabled)
	use_plan = bool(current_app.config.get('USE_NIGHT_PLAN', False))
	plans = {p.operator_id: p for p in NightWeekPlan.query.filter_by(week_monday=mon).all()} if use_plan else {}

	# Leave map by op/day
	leave_q = LeaveRequest.query.filter(
		LeaveRequest.status == 'approved',
		LeaveRequest.start_date <= fri,
		LeaveRequest.end_date >= mon,
	)
	if room_value is not None:
		leave_q = leave_q.join(Operator, Operator.id == LeaveRequest.operator_id).filter(Operator.room_number == room_value)
	leaves = leave_q.all()
	leave_by_op_day = {}
	for l in leaves:
		cur = max(mon, l.start_date)
		stop = min(fri, l.end_date)
		while cur <= stop:
			leave_by_op_day[(l.operator_id, cur)] = (l.leave_type or '').strip()
			cur += timedelta(days=1)

	# Approved OT map by (op_id, day)
	ot_q = OvertimeRequest.query.filter(
		OvertimeRequest.day >= mon,
		OvertimeRequest.day <= fri,
		OvertimeRequest.status == 'approved',
	)
	if room_value is not None:
		ot_q = ot_q.join(Operator, Operator.id == OvertimeRequest.operator_id).filter(Operator.room_number == room_value)
	ots = ot_q.all()
	ot_by_key = {}
	for r in ots:
		ot_by_key[(r.operator_id, r.day)] = ot_by_key.get((r.operator_id, r.day), 0.0) + float(getattr(r, 'hours', 0.0) or 0.0)

	# Helpers for night/day computations
	def _overlap_seconds(a_start, a_end, b_start, b_end):
		s = max(a_start, b_start); e = min(a_end, b_end)
		return max(0, int((e - s).total_seconds()))
	def _night_daily_ot_hours(op_id, the_day):
		"""18:00→24:00 of the_day + 00:00→06:00 of next day, tolerant of missing edges."""
		eve_start = datetime.combine(the_day, datetime.min.time()).replace(hour=18, minute=0)
		midn = datetime.combine(the_day + timedelta(days=1), datetime.min.time())
		next_06 = datetime.combine(the_day + timedelta(days=1), datetime.min.time()).replace(hour=6, minute=0)
		seg_today = dly_by_key.get((op_id, the_day))
		seg_next = dly_by_key.get((op_id, the_day + timedelta(days=1)))
		ov_eve = 0; ov_morn = 0
		# Evening part: if we have a first_in on the day, assume work until midnight when last_out missing
		if seg_today and seg_today.first_in:
			s = max(seg_today.first_in, eve_start)
			e = midn
			if seg_today.last_out:
				e = min(seg_today.last_out, midn)
			if e > s:
				ov_eve = int((e - s).total_seconds())
		# Morning part: if we have a last_out next day ≤ 06:00, count midnight→last_out even if no first_in
		if seg_next and seg_next.last_out:
			s = midn
			if seg_next.first_in and seg_next.first_in > midn:
				s = max(seg_next.first_in, midn)
			e = min(seg_next.last_out, next_06)
			if e > s:
				ov_morn = int((e - s).total_seconds())
		total_sec = ov_eve + ov_morn
		if total_sec <= 0:
			return 0.0
		lunch_min = int(getattr(SCHED, 'lunch_minutes', 60) or 60)
		worked_h = max(0.0, (total_sec - max(0, lunch_min) * 60) / 3600.0)
		worked_h = _apply_rounding_hours(worked_h)
		return _apply_rounding_hours(max(0.0, worked_h - 8.0))

	def _is_night_day(op_id, the_day):
		"""Heuristic: a day is a night shift if it starts in the evening (>=17:30 local)
		or ends the next morning (<=06:15 local) with at least ~6h worked.

		Uses AttendanceDaily first_in/last_out (stored as naive UTC) and converts to local using DEVICE_TZ_OFFSET.
		This avoids false positives where a day employee clocks 18:00+ a few minutes.
		"""
		dly = dly_by_key.get((op_id, the_day))
		if not dly:
			return False
		fi = dly.first_in; lo = dly.last_out
		if not fi and not lo:
			return False
		try:
			s = str(current_app.config.get('DEVICE_TZ_OFFSET', '+00:00')).strip()
			sign = 1 if s[0] == '+' else -1
			hh, mm = s[1:].split(':')
			TZ = timedelta(hours=sign*int(hh), minutes=sign*int(mm))
		except Exception:
			TZ = timedelta(0)
		fi_loc = (fi + TZ) if fi else None
		lo_loc = (lo + TZ) if lo else None
		worked_ok = (dly.worked_seconds or 0) >= 6*3600
		from datetime import time as _t
		thr_ev = _t(17,30)
		thr_morn = _t(6,15)
		is_evening_start = bool(fi_loc and fi_loc.time() >= thr_ev)
		spans_midnight = bool(fi_loc and lo_loc and lo_loc.date() > fi_loc.date())
		is_next_morning_checkout = bool(lo_loc and lo_loc.time() <= thr_morn and (spans_midnight or (fi_loc is None and lo_loc.date() > the_day)))
		return worked_ok and (is_evening_start or is_next_morning_checkout)

	def _leave_abbr(lt: str | None) -> tuple[str, bool]:
		if not lt:
			return ('', False)
		s = (lt or '').strip().lower()
		if 'unpaid' in s:
			return ('U', False)   # Unpaid Leave (no base contribution)
		if 'annual' in s:
			return ('AL', True)
		if 'sick' in s:
			return ('S', True)
		if 'fam' in s or 'family' in s:
			return ('FR', True)
		if s.startswith('sp') or 'special' in s:
			return ('Sp', True)
		return ('LV', True)

	def _normal_hours(op_id, d):
		dly = dly_by_key.get((op_id, d))
		return round(((dly.normal_seconds or 0) / 3600.0), 2) if dly else 0.0

	# Build Summary rows using old allocation rules
	summary_rows = []
	for op in ops:
		# Determine if operator has any activity or approvals in week to include
		include = any(((op.id, d) in dly_by_key or (op.id, d) in ot_by_key) for d in [mon, tue, wed, thu, fri])
		include = include or any(((op.id, d) in dly_by_key) for d in [prev_fri, prev_sat])
		if not include:
			continue

		is_night = bool(getattr(op, 'is_night_shift', False))
		plan = plans.get(op.id)
		plan_flags = [bool(getattr(plan, n)) for n in ('mon','tue','wed','thu')] if plan else [False, False, False, False]

		# Paid leave bonus seconds accumulator
		paid_leave_bonus_sec = 0
		def _paid_bonus_for_day(d):
			lt = leave_by_op_day.get((op.id, d))
			abbr, paid = _leave_abbr(lt)
			return abbr, (8 * 3600 if paid else 0)

		row = {
			'code': (op.emp_no or '-'),
			'name': (op.full_name or op.username),
		}

		# Base columns + Over allocation
		if is_night:
			def _night_base_for(d):
				nonlocal paid_leave_bonus_sec
				abbr, bonus = _paid_bonus_for_day(d)
				if abbr:
					paid_leave_bonus_sec += bonus
					return abbr
				# If actual night pattern detected, display 'N/S'; otherwise show daytime normal hours if any
				if _is_night_day(op.id, d):
					return 'N/S'
				val = _normal_hours(op.id, d)
				return val if val > 0 else '-'

			mon_base = _night_base_for(mon)
			tue_base = _night_base_for(tue)
			wed_base = _night_base_for(wed)
			thu_base = _night_base_for(thu)
			# Friday: if explicit leave exists, use it; else if Thu had leave and Thu is planned night, mirror label for display only
			fri_lab = leave_by_op_day.get((op.id, fri))
			if fri_lab:
				abbr, bonus = _leave_abbr(fri_lab)
				fri_base = abbr
				paid_leave_bonus_sec += (8*3600 if bonus else 0)
			elif plan_flags[3] and leave_by_op_day.get((op.id, thu)):
				fri_base = _leave_abbr(leave_by_op_day.get((op.id, thu)))[0]
			else:
				# If Friday night not worked, show 'No N/S' explicitly; else show based on actual
				fri_base = ('No N/S' if not _is_night_day(op.id, fri) else 'N/S')
			sat_base = '-'

			# Night daily OT capacity Mon..Thu
			cap_mon = _apply_rounding_hours(_night_daily_ot_hours(op.id, mon))
			cap_tue = _apply_rounding_hours(_night_daily_ot_hours(op.id, tue))
			cap_wed = _apply_rounding_hours(_night_daily_ot_hours(op.id, wed))
			cap_thu = _apply_rounding_hours(_night_daily_ot_hours(op.id, thu))
			# Approved minutes for Mon..Fri
			approved_week_min = 0
			for d in (mon, tue, wed, thu, fri):
				approved_week_min += int(round((ot_by_key.get((op.id, d), 0.0) or 0.0) * 60))
			# Allocate Mon..Thu in order up to each night's capacity; remainder is Over Fri.
			caps_min = [
				(mon, int(round(cap_mon * 60))),
				(tue, int(round(cap_tue * 60))),
				(wed, int(round(cap_wed * 60))),
				(thu, int(round(cap_thu * 60))),
			]
			alloc_min = {mon:0, tue:0, wed:0, thu:0}
			remaining = approved_week_min
			for d, capm in caps_min:
				take = min(capm, remaining)
				alloc_min[d] = take
				remaining -= take
			mon_over = round(alloc_min[mon] / 60.0, 2)
			tue_over = round(alloc_min[tue] / 60.0, 2)
			wed_over = round(alloc_min[wed] / 60.0, 2)
			thu_over = round(alloc_min[thu] / 60.0, 2)
			# Default Over Fri. from approvals remainder
			over_fri = _apply_rounding_hours(remaining / 60.0)

			# Compute Mon–Thu approved OT sum for Friday fill logic
			sum_approved_mon_thu = 0.0
			for d0 in (mon, tue, wed, thu):
				sum_approved_mon_thu += float(ot_by_key.get((op.id, d0), 0.0) or 0.0)
			sum_approved_mon_thu = _apply_rounding_hours(sum_approved_mon_thu)
			fill_remainder = _apply_rounding_hours(max(0.0, sum_approved_mon_thu - 8.0))

			# Count nights worked Mon–Thu + Friday (approved OT days preferred; fallback to observed overlap)
			nights_worked = sum(1 for d0 in (mon, tue, wed, thu) if (ot_by_key.get((op.id, d0), 0.0) or 0.0) > 0.0)
			if nights_worked == 0:
				nights_worked = sum(1 for d0 in (mon, tue, wed, thu) if _is_night_day(op.id, d0))
			fri_touched = _is_night_day(op.id, fri)
			nights_worked += 1 if fri_touched else 0

			# If Friday night wasn't worked and no explicit leave label, keep 'No N/S' and set Over Fri. as remainder
			if not fri_lab and not fri_touched:
				fri_base = 'No N/S'
				over_fri = fill_remainder

			# Totals: include paid leave bonus seconds
			def _base_hours(val):
				if isinstance(val, (int, float)):
					return float(val)
				if not isinstance(val, str):
					return 0.0
				s = val.strip().upper()
				if s in ('N/S', 'AL', 'S', 'FR', 'SP', 'LV'):
					return 8.0
				return 0.0
			total_n = round(
				_base_hours(mon_base) + _base_hours(tue_base) + _base_hours(wed_base) + _base_hours(thu_base) + _base_hours(fri_base), 2
			)
			# Saturday approved (for completeness)
			sat_ot = _apply_rounding_hours(ot_by_key.get((op.id, prev_sat), 0.0))
			total_o = round(mon_over + tue_over + wed_over + thu_over + over_fri + sat_ot, 2)
			night_shift_col = nights_worked  # count of nights worked

			# For display, show 'No N/S' on Friday only when explicitly marked as No Night in daily notes
			fri_notes = (dly_by_key.get((op.id, fri)).notes if dly_by_key.get((op.id, fri)) else '') or ''
			fri_nn_flag = 'NO_NIGHT' in fri_notes.upper() or 'NO_FRI_NIGHT' in fri_notes.upper()
			fri_display = ('No N/S' if fri_nn_flag else fri_base)

			row_out = {
				'Code': row['code'], 'Name': row['name'],
				'FRI': (_normal_hours(op.id, prev_fri) or '-') ,
				'SAT': (_normal_hours(op.id, prev_sat) or '-') ,
				'Mon': mon_base, 'OVER Mon': (mon_over or '-'),
				'Tue': tue_base, 'OVER Tue': (tue_over or '-'),
				'Wed': wed_base, 'OVER Wed': (wed_over or '-'),
				'Thu': thu_base, 'OVER Thu': (thu_over or '-'),
				'Fri': fri_display, 'Over Fri.': (over_fri or '-'),
				'Total N': (total_n or '-'), 'Total O': (total_o or '-'),
				'Night Shift': (night_shift_col or '-'),
				'Notes': '', 'N/S': '', 'Over': '', 'Leave': '',
				'is_night': True,
			}
			# Add day-wise leave notes + Friday fill explanation when applicable
			notes_parts = []
			for d in (mon, tue, wed, thu, fri):
				lt = leave_by_op_day.get((op.id, d))
				if lt:
					abbr, _paid = _leave_abbr(lt)
					notes_parts.append(f"{abbr}: {d.strftime('%d.%m')}")
			# Friday fill note
			if not fri_lab and not fri_touched:
				notes_parts.append(
					f"Fri not worked: filled 8.00h from Mon–Thu ({sum_approved_mon_thu:.2f}h), remainder {fill_remainder:.2f}h paid as OT"
				)
			row_out['Notes'] = '; '.join(notes_parts)
			summary_rows.append(row_out)
		else:
			# Day employees
			paid_leave_bonus_sec = 0
			def _day_base_for(d):
				nonlocal paid_leave_bonus_sec
				abbr, bonus = _paid_bonus_for_day(d)
				if abbr:
					paid_leave_bonus_sec += bonus
					return abbr
				# If they actually worked a night pattern on this day, reflect it as 'N/S'
				if _is_night_day(op.id, d):
					return 'N/S'
				return 8 if _normal_hours(op.id, d) > 0 else '-'

			mon_base = _day_base_for(mon)
			tue_base = _day_base_for(tue)
			wed_base = _day_base_for(wed)
			thu_base = _day_base_for(thu)
			fri_base = _day_base_for(fri)
			sat_base = '-'

			# If this day-employee actually worked at least one night Mon–Thu,
			# and Friday night was NOT worked and there's no leave, display 'No N/S' for Friday
			try:
				had_night_mon_thu = any(_is_night_day(op.id, d0) for d0 in (mon, tue, wed, thu))
			except Exception:
				had_night_mon_thu = False
			if had_night_mon_thu and not leave_by_op_day.get((op.id, fri)) and not _is_night_day(op.id, fri):
				fri_base = 'No N/S'

			# Over columns: per-day approved, rounded
			mon_over = _apply_rounding_hours(ot_by_key.get((op.id, mon), 0.0))
			tue_over = _apply_rounding_hours(ot_by_key.get((op.id, tue), 0.0))
			wed_over = _apply_rounding_hours(ot_by_key.get((op.id, wed), 0.0))
			thu_over = _apply_rounding_hours(ot_by_key.get((op.id, thu), 0.0))
			over_fri = _apply_rounding_hours(ot_by_key.get((op.id, fri), 0.0))
			sat_ot = _apply_rounding_hours(ot_by_key.get((op.id, prev_sat), 0.0))

			def _base_hours(val):
				if isinstance(val, (int, float)):
					return float(val)
				if not isinstance(val, str):
					return 0.0
				s = val.strip().upper()
				if s in ('N/S', 'AL', 'S', 'FR', 'SP', 'LV'):
					return 8.0
				return 0.0
			total_n = round(
				_base_hours(mon_base) + _base_hours(tue_base) + _base_hours(wed_base) + _base_hours(thu_base) + _base_hours(fri_base), 2
			)
			total_o = round(mon_over + tue_over + wed_over + thu_over + over_fri + sat_ot, 2)

			row_out = {
				'Code': row['code'], 'Name': row['name'],
				'FRI': (_normal_hours(op.id, prev_fri) or '-') ,
				'SAT': (_normal_hours(op.id, prev_sat) or '-') ,
				'Mon': mon_base, 'OVER Mon': (mon_over or '-'),
				'Tue': tue_base, 'OVER Tue': (tue_over or '-'),
				'Wed': wed_base, 'OVER Wed': (wed_over or '-'),
				'Thu': thu_base, 'OVER Thu': (thu_over or '-'),
				'Fri': fri_base, 'Over Fri.': (over_fri or '-'),
				'Total N': (total_n or '-'), 'Total O': (total_o or '-'),
				'Night Shift': '-',
				'Notes': '', 'N/S': '', 'Over': '', 'Leave': '',
				'is_night': False,
			}
			notes_parts = []
			for d in (mon, tue, wed, thu, fri):
				lt = leave_by_op_day.get((op.id, d))
				if lt:
					abbr, _paid = _leave_abbr(lt)
					notes_parts.append(f"{abbr}: {d.strftime('%d.%m')}")
			row_out['Notes'] = '; '.join(notes_parts)
			summary_rows.append(row_out)

	# Timezone offset for clocking display
	def _tz_offset():
		s = str(current_app.config.get('DEVICE_TZ_OFFSET', '+00:00'))
		try:
			sign = 1 if s.strip()[0] == '+' else -1
			hh, mm = s.strip()[1:].split(':')
			return timedelta(hours=sign*int(hh), minutes=sign*int(mm))
		except Exception:
			return timedelta(0)
	TZ = _tz_offset()
	def _local_str(dt):
		if not dt:
			return ''
		ldt = dt + TZ
		return ldt.strftime('%H:%M:%S')

	# Write workbook using xlsxwriter to mirror old style
	import xlsxwriter
	buf = BytesIO()
	wb = xlsxwriter.Workbook(buf, {"in_memory": True})

	# ====================== SHEET 1: Overtime ======================
	ws = wb.add_worksheet("Overtime")
	# Formats
	num_zero_dash = '0.00;-0.00;"-"'
	h_group = wb.add_format({"bold": True, "align": "center", "valign": "vcenter", "bg_color": "#B7DEE8", "border": 1})
	h_group_right = wb.add_format({"bold": True, "align": "center", "valign": "vcenter", "bg_color": "#B7DEE8", "border": 1, "right": 2})
	h_sub_base = wb.add_format({"bold": True, "align": "center", "valign": "vcenter", "bg_color": "#E2EFDA", "border": 1})
	h_sub_over = wb.add_format({"bold": True, "align": "center", "valign": "vcenter", "bg_color": "#D9E1F2", "border": 1})
	h_sub_right = wb.add_format({"bold": True, "align": "center", "valign": "vcenter", "bg_color": "#D9E1F2", "border": 1, "right": 2})
	h_sub_weekend = wb.add_format({"bold": True, "align": "center", "valign": "vcenter", "bg_color": "#FFF2CC", "border": 1})
	h_sub_weekend_right = wb.add_format({"bold": True, "align": "center", "valign": "vcenter", "bg_color": "#FFF2CC", "border": 1, "right": 2})
	cell_txt = wb.add_format({"border": 1, "align": "center"})
	cell_txt_sep = wb.add_format({"border": 1, "align": "center", "right": 2})
	cell_name = wb.add_format({"border": 1, "align": "left"})
	cell_code = wb.add_format({"border": 1, "align": "center"})
	cell_weekend = wb.add_format({"border": 1, "align": "center", "bg_color": "#FFF2CC"})
	cell_weekend_sep = wb.add_format({"border": 1, "align": "center", "bg_color": "#FFF2CC", "right": 2})
	cell_num = wb.add_format({"border": 1, "align": "center", "num_format": num_zero_dash})
	cell_num_sep = wb.add_format({"border": 1, "align": "center", "num_format": num_zero_dash, "right": 2})
	night_txt = wb.add_format({"border": 1, "align": "center", "bg_color": "#E2EFDA"})
	night_txt_sep = wb.add_format({"border": 1, "align": "center", "bg_color": "#E2EFDA", "right": 2})
	night_num = wb.add_format({"border": 1, "align": "center", "bg_color": "#E2EFDA", "num_format": num_zero_dash})
	night_num_sep = wb.add_format({"border": 1, "align": "center", "bg_color": "#E2EFDA", "num_format": num_zero_dash, "right": 2})
	totalN_num = wb.add_format({"border": 1, "align": "center", "bg_color": "#FFF2CC", "num_format": num_zero_dash})
	totalN_num_night = wb.add_format({"border": 1, "align": "center", "bg_color": "#D9EAD3", "num_format": num_zero_dash})
	note_fmt = wb.add_format({"border": 1, "align": "left", "text_wrap": True})

	# Header
	ws.set_row(0, 22); ws.set_row(1, 20)
	ws.merge_range(0, 0, 1, 0, "Code", h_group)
	ws.merge_range(0, 1, 1, 1, "Name", h_group_right)
	ws.merge_range(0, 2, 0, 3, "Lead", h_group_right)
	ws.merge_range(0, 4, 0, 5, "Mon", h_group_right)
	ws.merge_range(0, 6, 0, 7, "Tue", h_group_right)
	ws.merge_range(0, 8, 0, 9, "Wed", h_group_right)
	ws.merge_range(0,10, 0,11, "Thur", h_group_right)
	ws.merge_range(0,12, 0,13, "Fri", h_group_right)
	ws.merge_range(0,14, 0,15, "Totals", h_group_right)
	ws.merge_range(0,16, 1,16, "Night\nShift", h_group_right)
	ws.merge_range(0,17, 1,17, "Notes", h_group_right)
	ws.write(1, 2, "FRI", h_sub_weekend); ws.write(1, 3, "SAT", h_sub_weekend_right)
	ws.write(1, 4, "Base", h_sub_base); ws.write(1, 5, "OVER", h_sub_right)
	ws.write(1, 6, "Base", h_sub_base); ws.write(1, 7, "OVER", h_sub_right)
	ws.write(1, 8, "Base", h_sub_base); ws.write(1, 9, "OVER", h_sub_right)
	ws.write(1,10, "Base", h_sub_base); ws.write(1,11, "OVER", h_sub_right)
	ws.write(1,12, "Base", h_sub_base); ws.write(1,13, "Over Fri.", h_sub_right)
	ws.write(1,14, "Total N", h_sub_base); ws.write(1,15, "Total O", h_sub_right)
	# Column widths
	widths = [10, 26, 6, 6, 5, 6, 5, 6, 5, 6, 5, 6, 5, 8, 8, 8, 10, 26]
	for c, w in enumerate(widths):
		ws.set_column(c, c, w)
	ws.freeze_panes(2, 2)

	sep_after = {3, 5, 7, 9, 11, 13, 15, 16}
	def pick_fmt(col, is_night, kind="num"):
		sep = col in sep_after
		if kind == "weekend":
			return (cell_weekend_sep if sep else cell_weekend)
		if kind == "txt":
			return (night_txt_sep if sep else night_txt) if is_night else (cell_txt_sep if sep else cell_txt)
		if kind == "totalN":
			return totalN_num_night if is_night else totalN_num
		return (night_num_sep if sep else night_num) if is_night else (cell_num_sep if sep else cell_num)

	# Data rows
	r = 2
	for row in summary_rows:
		is_night_row = bool(row.get('is_night'))
		ws.write(r, 0, row.get('Code', ''), cell_code)
		ws.write(r, 1, row.get('Name', ''), cell_name)
		# Weekend lead
		fri0 = row.get('FRI', '-')
		sat0 = row.get('SAT', '-')
		if isinstance(fri0, str): ws.write(r, 2, fri0, pick_fmt(2, is_night_row, 'txt'))
		else: ws.write_number(r, 2, fri0 or 0, pick_fmt(2, is_night_row, 'weekend'))
		if isinstance(sat0, str): ws.write(r, 3, sat0, pick_fmt(3, is_night_row, 'txt'))
		else: ws.write_number(r, 3, sat0 or 0, pick_fmt(3, is_night_row, 'weekend'))
		# Mon..Thu
		for base_key, over_key, c_base, c_over in [
			('Mon','OVER Mon',4,5), ('Tue','OVER Tue',6,7), ('Wed','OVER Wed',8,9), ('Thu','OVER Thu',10,11)
		]:
			base_val = row.get(base_key, '-')
			fmt_kind = 'txt'
			fmt = pick_fmt(c_base, is_night_row, fmt_kind)
			# Highlight any 'N/S' as night green regardless of row type
			if isinstance(base_val, str) and base_val.strip().upper() == 'N/S':
				fmt = night_txt if c_base not in {5,7,9,11} else night_txt_sep
			if isinstance(base_val, str):
				ws.write(r, c_base, base_val, fmt)
			else:
				ws.write_number(r, c_base, base_val or 0, pick_fmt(c_base, is_night_row, 'num'))
			ov = row.get(over_key, '-')
			if isinstance(ov, str):
				ws.write(r, c_over, ov if ov != '-' else '', pick_fmt(c_over, is_night_row, 'num'))
			else:
				ws.write_number(r, c_over, ov or 0, pick_fmt(c_over, is_night_row, 'num'))
		# Fri base + Over Fri.
		fb = row.get('Fri', '-')
		if isinstance(fb, str):
			fmt_fb = pick_fmt(12, is_night_row, 'txt')
			if fb.strip().upper() == 'N/S':
				fmt_fb = night_txt_sep
			ws.write(r, 12, fb, fmt_fb)
		else: ws.write_number(r, 12, fb or 0, pick_fmt(12, is_night_row, 'num'))
		of = row.get('Over Fri.', '-')
		if isinstance(of, str):
			ws.write(r, 13, of if of != '-' else '', pick_fmt(13, is_night_row, 'num'))
		else:
			ws.write_number(r, 13, of or 0, pick_fmt(13, is_night_row, 'num'))
		# Totals
		tn = row.get('Total N', '-')
		to = row.get('Total O', '-')
		if isinstance(tn, str): ws.write(r, 14, tn if tn != '-' else '', pick_fmt(14, is_night_row, 'totalN'))
		else: ws.write_number(r, 14, tn or 0, pick_fmt(14, is_night_row, 'totalN'))
		if isinstance(to, str): ws.write(r, 15, to if to != '-' else '', pick_fmt(15, is_night_row, 'num'))
		else: ws.write_number(r, 15, to or 0, pick_fmt(15, is_night_row, 'num'))
		# Night Shift column (numbers for night only)
		nsc = row.get('Night Shift', '-')
		if is_night_row:
			ws.write_number(r, 16, (nsc or 0) if isinstance(nsc, (int, float)) else 0, pick_fmt(16, True, 'num'))
		else:
			ws.write(r, 16, '', pick_fmt(16, False, 'txt'))
		# Notes
		ws.write(r, 17, row.get('Notes', ''), note_fmt)
		r += 1

	ws.set_landscape(); ws.set_paper(9); ws.fit_to_pages(1, 0); ws.repeat_rows(0, 1)

	# ====================== SHEET 2: Clock Data (selected range) ======================
	cd = wb.add_worksheet("Clock Data")
	# Build selected day list
	selected_days = []
	curd = start_date
	while curd <= end_date:
		selected_days.append(curd)
		curd += timedelta(days=1)

	# Formats
	head_group = wb.add_format({"bold": True, "align": "center", "valign": "vcenter", "bg_color": "#9BC2E6", "border": 1})
	head_sub = wb.add_format({"bold": True, "align": "center", "valign": "vcenter", "bg_color": "#D9E1F2", "border": 1})
	name_hdr = wb.add_format({"bold": True, "align": "left", "valign": "vcenter", "bg_color": "#B7DEE8", "border": 1})
	name_col = wb.add_format({"border": 1, "align": "left", "bg_color": "#E2EFDA"})
	time_fmt = wb.add_format({"border": 1, "align": "center"})
	# Highlight adjusted times in red (font + background) similar to missing cells styling
	time_red = wb.add_format({"border": 1, "align": "center", "font_color": "#9C0006", "bg_color": "#FFC7CE"})
	missing_fmt = wb.add_format({"border": 1, "align": "center", "bg_color": "#FFC7CE", "font_color": "#9C0006"})
	leave_fmt = wb.add_format({"border": 1, "align": "center", "bg_color": "#C6EFCE", "font_color": "#006100"})
	# Use the same green style to denote "No Night Shift" days
	ns_fmt = leave_fmt
	comments_hdr = wb.add_format({"bold": True, "align": "left", "valign": "vcenter", "bg_color": "#B7DEE8", "border": 1})
	comments_cell = wb.add_format({"border": 1, "align": "left", "text_wrap": True})

	# Header rows
	cd.set_row(0, 22); cd.set_row(1, 20)
	cd.merge_range(0, 0, 1, 0, "Employee", name_hdr)
	col = 1
	for d in selected_days:
		cd.merge_range(0, col, 0, col + 1, d.strftime('%A %d/%m/%Y'), head_group)
		cd.write(1, col, "In", head_sub)
		cd.write(1, col + 1, "Out", head_sub)
		col += 2
	comments_col = col
	cd.merge_range(0, comments_col, 1, comments_col, "Comments", comments_hdr)

	# Widths & panes
	cd.set_column(0, 0, 26)
	for i in range(1, comments_col):
		cd.set_column(i, i, 12)
	cd.set_column(comments_col, comments_col, 38)
	cd.freeze_panes(2, 1)

	# Operator scope
	op_q2 = Operator.query.filter(Operator.active.is_(True))
	if room_value is not None:
		op_q2 = op_q2.filter(Operator.room_number == room_value)
	ops2 = op_q2.order_by(Operator.full_name.asc(), Operator.username.asc()).all()
	op_ids2 = [o.id for o in ops2] or [0]

	# Leaves and daily rows in selected range
	lr_rows = (LeaveRequest.query
		.filter(LeaveRequest.status == 'approved', LeaveRequest.operator_id.in_(op_ids2), LeaveRequest.end_date >= selected_days[0], LeaveRequest.start_date <= selected_days[-1])
		.all())
	leave_map = {}
	def leave_label(lt: str) -> str:
		lt = (lt or "").lower()
		if lt == "unpaid": return "Unpaid Leave"
		if lt == "annual": return "Annual Leave"
		if lt == "family": return "Fam Respon"
		if lt == "sick": return "Sick Leave"
		return (lt.title() + " Leave") if lt else "Leave"
	for lr in lr_rows:
		dd = max(selected_days[0], lr.start_date)
		stop = min(selected_days[-1], lr.end_date)
		lab = leave_label(getattr(lr, 'leave_type', ''))
		while dd <= stop:
			leave_map[(lr.operator_id, dd)] = lab
			dd += timedelta(days=1)

	daily_rows2 = (AttendanceDaily.query
		.filter(AttendanceDaily.operator_id.in_(op_ids2), AttendanceDaily.day >= selected_days[0], AttendanceDaily.day <= selected_days[-1])
		.all())
	daily_notes = {(d.operator_id, d.day): (d.notes or '') for d in daily_rows2}
	daily_meta = {(d.operator_id, d.day): d for d in daily_rows2}

	# Manual fixes
	start_dt = datetime.combine(selected_days[0], datetime.min.time())
	end_dt = datetime.combine(selected_days[-1] + timedelta(days=1), datetime.min.time())
	fix_evs = (AttendanceEvent.query
		.filter(AttendanceEvent.operator_id.in_(op_ids2), AttendanceEvent.timestamp >= start_dt, AttendanceEvent.timestamp < end_dt, AttendanceEvent.source.in_(["manual_fix", "manual", "adjust"]))
		.all())
	fixed_in, fixed_out = set(), set()
	for ev in fix_evs:
		d = ev.timestamp.date()
		if ev.event_type == 'check_in':
			if selected_days[0] <= d <= selected_days[-1]:
				fixed_in.add((ev.operator_id, d))
		else:
			noon = datetime.min.time().replace(hour=12)
			prev_d = d - timedelta(days=1) if ev.timestamp.time() <= noon else d
			if selected_days[0] <= prev_d <= selected_days[-1]:
				fixed_out.add((ev.operator_id, prev_d))

	def fmt_time(dtobj):
		return dtobj.strftime('%H:%M:%S') if dtobj else None

	# Rows
	r = 2
	for o in ops2:
		cd.write(r, 0, (o.full_name or o.username), name_col)
		comment_lines = []
		c = 1
		for the_day in selected_days:
			leave_text = leave_map.get((o.id, the_day))
			# Figure display in/out using precomputed daily edges
			dm = daily_meta.get((o.id, the_day))
			ui_in = dm.first_in if dm else None
			ui_out = dm.last_out if dm else None
			no_punches = (ui_in is None and ui_out is None)
			note_str = daily_notes.get((o.id, the_day), '')
			note_up = (note_str or '').upper()
			# Leave day without punches
			if leave_text and no_punches:
				cd.merge_range(r, c, r, c + 1, leave_text, leave_fmt)
				# Include reason if present
				if note_str:
					comment_lines.append(f"{the_day.strftime('%a %d/%m')}: {note_str}")
				else:
					comment_lines.append(f"{the_day.strftime('%a %d/%m')}: {leave_text}")
				c += 2
				continue
			# No Night Shift annotation without punches
			if no_punches and (('NO_NIGHT' in note_up) or ('NO_FRI_NIGHT' in note_up)):
				cd.merge_range(r, c, r, c + 1, "No N/S", ns_fmt)
				# Add a comment line reflecting the note
				if note_str:
					comment_lines.append(f"{the_day.strftime('%a %d/%m')}: {note_str}")
				else:
					comment_lines.append(f"{the_day.strftime('%a %d/%m')}: No Night Shift")
				c += 2
				continue
			# IN
			if ui_in:
				fmt_in = time_red if (o.id, the_day) in fixed_in else time_fmt
				cd.write(r, c, fmt_time(ui_in + TZ), fmt_in)
				if (o.id, the_day) in fixed_in and daily_notes.get((o.id, the_day)):
					comment_lines.append(f"{the_day.strftime('%a %d/%m')} IN: {daily_notes[(o.id, the_day)]}")
			else:
				cd.write(r, c, "No Clock In", missing_fmt)
			# OUT
			if ui_out:
				fmt_out = time_red if (o.id, the_day) in fixed_out else time_fmt
				cd.write(r, c + 1, fmt_time(ui_out + TZ), fmt_out)
				if (o.id, the_day) in fixed_out and daily_notes.get((o.id, the_day)):
					comment_lines.append(f"{the_day.strftime('%a %d/%m')} OUT: {daily_notes[(o.id, the_day)]}")
			else:
				cd.write(r, c + 1, "No Clock Out", missing_fmt)
			# extra daily note (always include tagged notes)
			extra = daily_notes.get((o.id, the_day))
			if extra and ("[Manual" in extra or "[Exceptions]" in extra or "[Leave]" in extra):
				# Avoid duplicate day entries if IN/OUT already appended a note line
				if not any(t.startswith(the_day.strftime('%a %d/%m')) for t in comment_lines):
					comment_lines.append(f"{the_day.strftime('%a %d/%m')}: {extra}")
			c += 2
		cd.write(r, comments_col, "\n".join(comment_lines), comments_cell)
		r += 1

	cd.set_landscape(); cd.set_paper(9); cd.fit_to_pages(1, 0); cd.repeat_rows(0, 1)

	# Finalize
	wb.close()
	buf.seek(0)
	fname = f"Overtime Report {start_date.strftime('%Y-%m-%d')} - {end_date.strftime('%Y-%m-%d')}.xlsx"
	return send_file(buf, as_attachment=True, download_name=fname, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


@attendance_bp.route('/attendance/export', methods=['GET', 'POST'])
@login_required
def export():
	# Render simple page; on POST generate using the same export above
	from .helpers import week_bounds_from_any
	today = date.today()
	mon, sat = week_bounds_from_any(today)
	room_choices = [(str(v) if v is not None else 'None', label) for v, label in room_filter_choices()]
	if request.method == 'POST':
		start = parse_date(request.form.get('start_date')) or mon
		end = parse_date(request.form.get('end_date')) or sat
		room = request.form.get('room_number')
		return overtime_report_export()
	return render_template('attendance/ot_export.html', start_default=mon.isoformat(), end_default=sat.isoformat(), room_choices=room_choices)


# --- Approvals queue ---
@attendance_bp.route('/attendance/overtime/queue')
@login_required
def overtime_queue():
	# Filters
	today = date.today()
	mon, sat = week_bounds_from_any(today)
	arg_sd = parse_date(request.args.get('start_date'))
	arg_ed = parse_date(request.args.get('end_date'))
	applied = bool(request.args.get('start_date') and request.args.get('end_date'))
	start_date = arg_sd or mon
	end_date = arg_ed or sat
	room_value = request.args.get('room_number')
	exceptions_only = str(request.args.get('exceptions_only') or '').lower() in ('1','true','on','yes')
	try:
		room_value = int(room_value) if room_value not in (None, '', 'None') else None
	except Exception:
		room_value = None

	groups = []
	if applied:
		# Ensure AttendanceDaily rows exist for the filtered scope so that
		# no-punch weekdays appear as exceptions (otherwise blank days would be invisible).
		try:
			op_ids = []
			if room_value is not None:
				op_ids = [op.id for op in Operator.query.filter(Operator.active.is_(True), Operator.room_number == room_value).all()]
			# As a fallback, if no room filter is set, recompute at least for operators who have pending OT
			if not op_ids:
				op_ids = list({r.operator_id for r in OvertimeRequest.query.filter(
					OvertimeRequest.day >= start_date,
					OvertimeRequest.day <= end_date,
				).all()})
			if op_ids:
				recompute_range(start_date, end_date, operator_ids=op_ids)
		except Exception:
			pass
		# Build queue: pending overtime requests in range, grouped per operator
		q = OvertimeRequest.query.filter(
			OvertimeRequest.status == 'pending',
			OvertimeRequest.day >= start_date,
			OvertimeRequest.day <= end_date,
		)
		if room_value is not None:
			q = q.join(Operator, Operator.id == OvertimeRequest.operator_id).filter(Operator.room_number == room_value)

		reqs = q.order_by(OvertimeRequest.operator_id.asc(), OvertimeRequest.day.asc()).all()

		# Aggregate per operator
		by_op = {}
		for r in reqs:
			g = by_op.get(r.operator_id)
			if not g:
				# Count exceptions similarly to Exceptions list logic:
				# - missing in/out OR zero segments
				# - also include missing first_in/last_out (stricter day-shift catch)
				# - exclude days marked NO_NIGHT/NO_FRI_NIGHT
				# - exclude weekends (Sat/Sun) with no punches at all
				# - exclude days with approved leave
				dq = AttendanceDaily.query.filter(
					AttendanceDaily.operator_id == r.operator_id,
					AttendanceDaily.day >= start_date,
					AttendanceDaily.day <= end_date,
				).all()

				exceptions_count = 0
				for dly in dq:
					# Skip explicit no-night markers
					note = (dly.notes or '').upper()
					if 'NO_NIGHT' in note or 'NO_FRI_NIGHT' in note:
						continue
					# Skip approved leave days
					has_leave = LeaveRequest.query.filter(
						LeaveRequest.operator_id == dly.operator_id,
						LeaveRequest.status == 'approved',
						LeaveRequest.start_date <= dly.day,
						LeaveRequest.end_date >= dly.day,
					).first()
					if has_leave:
						continue
					# Weekend no-punch days are not exceptions
					is_weekend = dly.day.weekday() >= 5
					no_segs = (dly.segment_count or 0) == 0
					no_punches = no_segs and (dly.first_in is None) and (dly.last_out is None)
					if is_weekend and no_punches:
						continue
					# Exception conditions
					if (bool(dly.missing_in) or bool(dly.missing_out) or no_segs or (dly.first_in is None) or (dly.last_out is None)):
						exceptions_count += 1
				g = {
					'operator': r.operator,
					'count': 0,
					'total_hours': 0.0,
					'exceptions_count': exceptions_count,
				}
				by_op[r.operator_id] = g
				groups.append(g)
			g['count'] += 1
			g['total_hours'] += float(r.proposed_hours or r.hours or 0.0)

		# Add operators with exceptions even if they have zero pending OT
		exc_q = AttendanceDaily.query.filter(AttendanceDaily.day >= start_date, AttendanceDaily.day <= end_date)
		if room_value is not None:
			exc_q = exc_q.join(Operator).filter(Operator.room_number == room_value)
		exc_rows = exc_q.all()
		from collections import defaultdict
		exc_by_op: dict[int, int] = defaultdict(int)
		for dly in exc_rows:
			# Skip explicit no-night markers
			note = (dly.notes or '').upper()
			if 'NO_NIGHT' in note or 'NO_FRI_NIGHT' in note:
				continue
			# Skip approved leave days
			has_leave = LeaveRequest.query.filter(
				LeaveRequest.operator_id == dly.operator_id,
				LeaveRequest.status == 'approved',
				LeaveRequest.start_date <= dly.day,
				LeaveRequest.end_date >= dly.day,
			).first()
			if has_leave:
				continue
			# Weekend no-punch days are not exceptions
			is_weekend = dly.day.weekday() >= 5
			no_segs = (dly.segment_count or 0) == 0
			no_punches = no_segs and (dly.first_in is None) and (dly.last_out is None)
			if is_weekend and no_punches:
				continue
			if (bool(dly.missing_in) or bool(dly.missing_out) or no_segs or (dly.first_in is None) or (dly.last_out is None)):
				exc_by_op[dly.operator_id] += 1

		# Also account for days where there is no AttendanceDaily record at all (true no-punch days).
		# If weekday and not on approved leave, count as an exception for that operator.
		dly_keys = {(d.operator_id, d.day) for d in exc_rows}
		# Determine operator scope for this queue view
		if room_value is not None:
			ops_scope = Operator.query.filter(Operator.active.is_(True), Operator.room_number == room_value).all()
		else:
			# fall back to operators present in pending OT or any AttendanceDaily in the window
			op_ids_scope = set(by_op.keys()) | {d.operator_id for d in exc_rows}
			ops_scope = Operator.query.filter(Operator.id.in_(list(op_ids_scope))) if op_ids_scope else []
		cur = start_date
		while cur <= end_date:
			# weekdays only
			if cur.weekday() < 5:
				for op in ops_scope:
					if (op.id, cur) not in dly_keys:
						# Approved leave?
						has_leave = LeaveRequest.query.filter(
							LeaveRequest.operator_id == op.id,
							LeaveRequest.status == 'approved',
							LeaveRequest.start_date <= cur,
							LeaveRequest.end_date >= cur,
						).first()
						if not has_leave:
							exc_by_op[op.id] += 1
			cur += timedelta(days=1)

		# Create group entries for exceptions-only operators
		if exc_by_op:
			missing_ids = [op_id for op_id in exc_by_op.keys() if op_id not in by_op]
			if missing_ids:
				for op in Operator.query.filter(Operator.id.in_(missing_ids)).all():
					groups.append({
						'operator': op,
						'count': 0,
						'total_hours': 0.0,
						'exceptions_count': exc_by_op.get(op.id, 0),
					})

	# Filter form shim
	FF = type('FF', (), {})()
	setattr(FF, 'start_date', type('F', (), {'data': start_date})())
	setattr(FF, 'end_date', type('F', (), {'data': end_date})())
	setattr(FF, 'room_number', type('F', (), {
		'data': (str(room_value) if room_value is not None else 'None'),
		'choices': [(str(v) if v is not None else 'None', lbl) for v, lbl in room_filter_choices()]
	})())

	# Optional filter: show only operators that have exceptions in the range
	if exceptions_only and groups:
		groups = [g for g in groups if (g.get('exceptions_count', 0) or 0) > 0]

	return render_template('attendance/overtime_queue.html', filter_form=FF, groups=groups, filters_applied=applied)


@attendance_bp.route('/attendance/overtime/review/<int:operator_id>', methods=['GET', 'POST'])
@login_required
def overtime_review_employee(operator_id: int):
	# Inputs
	start_date = parse_date(request.args.get('start_date'))
	end_date = parse_date(request.args.get('end_date'))
	room_number = request.args.get('room_number')

	op = Operator.query.get_or_404(operator_id)

	# Form shim for CSRF and submit
	from markupsafe import Markup
	class Form:
		def hidden_tag(self):
			from flask_wtf.csrf import generate_csrf
			return Markup(f"<input type='hidden' name='csrf_token' value='{generate_csrf()}'>")
		def submit(self, **k):
			cls = k.get('class', 'btn btn-primary')
			dis = ' disabled' if k.get('disabled') else ''
			id_attr = f" id='{k.get('id')}'" if k.get('id') else ''
			return Markup(f"<button class='{cls}'{dis}{id_attr}>Submit</button>")

	# If range not provided, default to the current workweek
	if not (start_date and end_date):
		mon, sat = week_bounds_from_any(date.today())
		start_date = start_date or mon
		end_date = end_date or sat

	# Ensure proposals exist/are refreshed for this operator in range
	try:
		propose_overtime_for_range(start_date, end_date, operator_ids=[operator_id])
	except Exception:
		pass

	# Load pending requests and render rows
	q = OvertimeRequest.query.filter(OvertimeRequest.operator_id == operator_id, OvertimeRequest.status == 'pending')
	if start_date:
		q = q.filter(OvertimeRequest.day >= start_date)
	if end_date:
		q = q.filter(OvertimeRequest.day <= end_date)
	reqs = q.order_by(OvertimeRequest.day.asc()).all()

	# Map day -> AttendanceDaily for context
	dmap = {d.day: d for d in AttendanceDaily.query.filter(AttendanceDaily.operator_id == operator_id, AttendanceDaily.day >= start_date, AttendanceDaily.day <= end_date).all()}

	# Build rows for template
	rows = []
	# Timezone-adjusted display helpers
	def _tz_offset() -> timedelta:
		s = str(current_app.config.get('DEVICE_TZ_OFFSET', '+00:00'))
		try:
			sign = 1 if s.strip()[0] == '+' else -1
			hh, mm = s.strip()[1:].split(':')
			return timedelta(hours=sign*int(hh), minutes=sign*int(mm))
		except Exception:
			return timedelta(0)

	tz_off = _tz_offset()
	def _local(dt):
		return (dt + tz_off) if dt else None


	def _lunch_minutes_for(op: Operator) -> int:
		try:
			sch = WorkSchedule.query.filter_by(operator_id=op.id, enabled=True).first()
			if not sch and op.room_number is not None:
				sch = WorkSchedule.query.filter_by(room_number=op.room_number, enabled=True).first()
			if not sch:
				sch = WorkSchedule.query.filter_by(is_default=True, enabled=True).first()
			return int(getattr(sch, 'lunch_minutes', 60) or 60)
		except Exception:
			return 60

	def _night_like(ui_in, ui_out) -> bool:
		try:
			if ui_in and ui_in.hour >= 17:
				return True
			if ui_out and ui_out.hour <= 6:
				return True
			return False
		except Exception:
			return False

	for r in reqs:
		d = dmap.get(r.day)
		worked_hours = ((d.worked_seconds or 0)/3600.0) if d else 0.0
		daily_ot_hours = (((d.ot1_seconds or 0)+(d.ot2_seconds or 0))/3600.0) if d else (r.proposed_hours or r.hours or 0.0)
		ui_in = _local(d.first_in) if d else None
		ui_out = _local(d.last_out) if d else None
		
		# Default Hours(edit) logic based on day type:
		dow = r.day.weekday()  # 0=Mon..6=Sun
		lunch_h = _lunch_minutes_for(op) / 60.0
		
		if dow == 5:  # Saturday - all worked hours are OT1 (1.5x rate)
			actual_ot_hours = max(0.0, worked_hours - lunch_h) if worked_hours > 0 else 0.0
			edit_hours = round(actual_ot_hours * 1.5, 2) if actual_ot_hours > 0 else daily_ot_hours
		elif dow == 6:  # Sunday - all worked hours are OT2 (2x rate)
			actual_ot_hours = max(0.0, worked_hours - lunch_h) if worked_hours > 0 else 0.0
			edit_hours = round(actual_ot_hours * 2.0, 2) if actual_ot_hours > 0 else daily_ot_hours
		elif _night_like(ui_in, ui_out) and worked_hours > 0:  # Weekday night shift
			# worked_hours already reflects lunch deduction; subtract only the 8h normal portion
			edit_hours = max(0.0, round(worked_hours - 8.0, 2))
		else:  # Regular weekday overtime
			edit_hours = daily_ot_hours
		rows.append({
			'mode': 'request',
			'req': r,
			'day': r.day,
			'ui_in': ui_in,
			'ui_out': ui_out,
			'worked_hours': worked_hours,
			'daily_ot_hours': daily_ot_hours,
			'edit_default_hours': edit_hours,
		})

	# --- Night/Fri remainder logic ---
	def _week_monday(d: date) -> date:
		return d - timedelta(days=d.weekday())

	def _has_night(op: Operator, d: date) -> bool:
		wm = _week_monday(d)
		plan = NightWeekPlan.query.filter_by(operator_id=op.id, week_monday=wm).one_or_none()
		idx = d.weekday()  # 0=Mon..6=Sun
		if plan:
			flags = [plan.mon, plan.tue, plan.wed, plan.thu, plan.fri, plan.sat, plan.sun]
			return bool(flags[idx])
		return bool(getattr(op, 'is_night_shift', False))

	# Compute Friday remainder row for each Friday in range
	cur = start_date
	while cur <= end_date:
		if cur.weekday() == 4:  # Friday
			fri = cur
			# If the operator has a night assignment for Friday evening
			if _has_night(op, fri):
				mon = _week_monday(fri)
				thu = mon + timedelta(days=3)
				# Compute post-fill remainder using total paid Mon–Thu hours, not current OT balances
				# This is robust to weekly rebalancing.
				sum_paid_mon_thu = 0.0
				for k in range(4):
					dayk = mon + timedelta(days=k)
					d = dmap.get(dayk)
					if d:
						paid_secs = int(d.normal_seconds or 0) + int(d.ot1_seconds or 0) + int(d.ot2_seconds or 0)
						sum_paid_mon_thu += round(paid_secs / 3600.0, 2)

				# Fill to 40h with Mon–Thu paid time; remainder is overtime to pay
				unpaid_fill = 8.0
				remainder = max(0.0, round(sum_paid_mon_thu - 40.0, 2))

				fri_daily = dmap.get(fri)
				# Determine if Friday night was actually worked (has substantial night-like timing and OT)
				fri_worked_night = False
				if fri_daily and fri_daily.worked_seconds and fri_daily.worked_seconds > 0:
					# Check if this looks like night work (evening start or early morning end)
					fri_ui_in = _local(fri_daily.first_in) if fri_daily.first_in else None
					fri_ui_out = _local(fri_daily.last_out) if fri_daily.last_out else None
					if _night_like(fri_ui_in, fri_ui_out):
						fri_worked_night = True

				# Friday messaging / action:
				if not fri_worked_night:
					# If exceptions page already marked NO_NIGHT, show user-friendly info row instead of a blocking exception
					no_night_marked = False
					if fri_daily and (fri_daily.notes or ''):
						note_u = fri_daily.notes.upper()
						no_night_marked = ('NO_NIGHT' in note_u) or ('NO_FRI_NIGHT' in note_u)

					if no_night_marked:
						# After weekly rebalance, Mon–Thu OT1 already reflects the remainder to pay.
						# Use that directly for messaging and UI.
						rows.append({
							'mode': 'capped',  # non-editable info
							'day': fri,
							'ui_in': None,
							'ui_out': None,
							'worked_hours': 0.0,
							'daily_ot_hours': remainder,
							'is_friday_remainder': True,
							'post_fill': True,
							'friday_remainder_hours': round(remainder, 2),
							'calc_unpaid_fill_hours': unpaid_fill,
							'calc_sum_daily_ot': sum_paid_mon_thu,  # display context if needed
							'calc_remainder_after_fill': remainder,
							'note': f"No night shift worked Friday night. Used Mon–Thu overtime to fill 40h; {remainder:.2f}h will be posted as overtime.",
						})
					else:
						rows.append({
							'mode': 'missing',  # prompts exception action
							'day': fri,
							'missing_hours': unpaid_fill,
							'exception_url': url_for('attendance.exception_fix', operator_id=op.id, day_iso=fri.isoformat(), start_date=start_date.isoformat(), end_date=end_date.isoformat(), room_number=room_number),
						})
				# If Friday was actually worked, no remainder row needed - the regular OT request already exists
		cur += timedelta(days=1)

	if request.method == 'POST':
		# Process bulk decisions for rows present in the form
		# Expect repeated fields: request_id, row_day, hours, decision, reason
		ids = request.form.getlist('request_id')
		days = request.form.getlist('row_day')
		hours_list = request.form.getlist('hours')
		decisions = request.form.getlist('decision')
		reasons = request.form.getlist('reason')

		updated = 0
		for rid, day_iso, h_txt, dec, reason in zip(ids, days, hours_list, decisions, reasons):
			r = OvertimeRequest.query.get(int(rid))
			if not r or r.operator_id != operator_id or r.status != 'pending':
				continue
			dec = (dec or '').lower()
			if dec not in ('approved', 'rejected'):
				continue
			reason = (reason or '').strip()
			if not reason:
				continue
			if dec == 'approved':
				try:
					hours = float(h_txt)
				except Exception:
					hours = 0.0
				if hours <= 0:
					continue
				r.hours = round(hours, 2)
				r.status = 'approved'
				r.approved_at = datetime.utcnow()
				r.approved_by_id = (current_user.id if getattr(current_user, 'id', None) else None)
				r.reason = reason
			else:
				r.hours = 0.0
				r.status = 'rejected'
				r.approved_at = datetime.utcnow()
				r.approved_by_id = (current_user.id if getattr(current_user, 'id', None) else None)
				r.reason = reason
			updated += 1
		# Handle optional mark_unpaid_fri checkbox
		unpaid_days = request.form.getlist('mark_unpaid_fri')
		unpaid_added = 0
		for iso in unpaid_days:
			try:
				d = date.fromisoformat(iso)
			except Exception:
				continue
			lr = LeaveRequest(
				operator_id=op.id,
				leave_type='unpaid',
				start_date=d,
				end_date=d,
				hours_per_day=0.0,
				status='approved',
				created_by_id=(current_user.id if getattr(current_user, 'id', None) else None),
				approved_by_id=(current_user.id if getattr(current_user, 'id', None) else None),
				approved_at=datetime.utcnow(),
				notes='Marked unpaid from OT review',
			)
			db.session.add(lr)
			unpaid_added += 1

		if updated or unpaid_added:
			db.session.commit()
			msg = []
			if updated: msg.append(f"{updated} OT item(s)")
			if unpaid_added: msg.append(f"{unpaid_added} unpaid day(s)")
			flash('Updated: ' + ', '.join(msg) + '.', 'success')
		else:
			flash('No changes applied. Please select decisions and provide reasons.', 'warning')
		return redirect(url_for('attendance.overtime_queue', start_date=start_date.isoformat() if start_date else None, end_date=end_date.isoformat() if end_date else None, room_number=room_number))

	return render_template('attendance/overtime_review_employee.html',
						   op=op,
						   rows=rows,
						   reqs=reqs,
						   form=Form(),
						   start_date=start_date or date.today(),
						   end_date=end_date or date.today(),
						   room_number=(str(room_number) if room_number is not None else 'None'))
