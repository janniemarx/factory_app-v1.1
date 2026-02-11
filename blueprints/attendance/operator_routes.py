from __future__ import annotations
from datetime import date
from flask import request, render_template, redirect, url_for, flash
from flask_login import login_required
from .routes import attendance_bp
from models import db
from models.operator import Operator
from models.attendance import NightWeekPlan
from .helpers import parse_date, iso_monday
from markupsafe import Markup


@attendance_bp.route('/attendance/operators', methods=['GET', 'POST'])
@attendance_bp.route('/attendance/operators', methods=['GET', 'POST'], endpoint='operators_maintenance')
@login_required
def operators():
	# Simple filters
	room_number = request.args.get('room_number', type=int)
	name_like = (request.args.get('name_like') or '').strip()
	active_only = request.args.get('active_only') in {'on', '1', 'true'}
	week_any = parse_date(request.args.get('week')) or date.today()
	plan_week = iso_monday(week_any)

	if request.method == 'POST':
		# Collect rows-* indices from the form
		indices = set()
		for k in request.form.keys():
			if k.startswith('rows-') and k.endswith('-operator_id'):
				try:
					idx = int(k.split('-')[1])
					indices.add(idx)
				except Exception:
					pass
		updated_ops = 0
		updated_plans = 0
		for i in sorted(indices):
			op_id = request.form.get(f'rows-{i}-operator_id', type=int)
			if not op_id:
				continue
			op = Operator.query.get(op_id)
			if not op:
				continue
			# Base toggle
			is_ns = request.form.get(f'rows-{i}-is_night_shift') is not None
			if op.is_night_shift != is_ns:
				op.is_night_shift = is_ns
				updated_ops += 1
			# Inline week plan checkboxes for selected week
			mon = request.form.get(f'rows-{i}-night-mon') is not None
			tue = request.form.get(f'rows-{i}-night-tue') is not None
			wed = request.form.get(f'rows-{i}-night-wed') is not None
			thu = request.form.get(f'rows-{i}-night-thu') is not None
			fri = request.form.get(f'rows-{i}-night-fri') is not None
			sat = request.form.get(f'rows-{i}-night-sat') is not None
			sun = request.form.get(f'rows-{i}-night-sun') is not None
			# Always upsert the week's plan so unchecking clears prior flags
			p = NightWeekPlan.query.filter_by(operator_id=op.id, week_monday=plan_week).first()
			if not p:
				p = NightWeekPlan(operator_id=op.id, week_monday=plan_week)
				db.session.add(p)
			p.mon, p.tue, p.wed, p.thu, p.fri, p.sat, p.sun = mon, tue, wed, thu, fri, sat, sun
			updated_plans += 1
		if (updated_ops + updated_plans) > 0:
			db.session.commit()
			msg = []
			if updated_ops:
				msg.append(f"{updated_ops} operator flag(s)")
			if updated_plans:
				msg.append(f"{updated_plans} week plan(s)")
			flash('Updated ' + ' & '.join(msg) + '.', 'success')
		else:
			flash('No changes detected.', 'info')
		return redirect(url_for('attendance.operators', room_number=room_number, name_like=name_like, active_only=('on' if active_only else ''), week=plan_week.isoformat()))

	q = Operator.query
	if room_number is not None:
		q = q.filter(Operator.room_number == room_number)
	if active_only:
		q = q.filter(Operator.active.is_(True))
	if name_like:
		like = f"%{name_like}%"
		q = q.filter((Operator.full_name.ilike(like)) | (Operator.username.ilike(like)) | (Operator.emp_no.ilike(like)))
	operators = q.order_by(Operator.full_name.asc().nullslast(), Operator.username.asc()).all()

	# Minimal forms shims
	class FilterForm:
		def __init__(self):
			def label(**k): return ''
			def select_room(**k):
				from .helpers import room_filter_choices
				opts = []
				for v, lbl in room_filter_choices():
					val = '' if v is None else str(v)
					sel = ' selected' if ((room_number is None and v is None) or (v is not None and v == room_number)) else ''
					opts.append(f"<option value='{val}'{sel}>{lbl}</option>")
				return Markup(f"<select name='room_number' class='{k.get('class','form-select')}'>{''.join(opts)}</select>")
			def name_like_input(**k):
				val = name_like or ''
				return Markup(f"<input name='name_like' class='{k.get('class','form-control')}' value='{val}' placeholder='{k.get('placeholder','')}'>")
			self.room_number = type('F', (), {'label': lambda self, **k: '', '__call__': lambda self, **k: select_room(**k)})()
			self.name_like = type('F', (), {'label': lambda self, **k: '', '__call__': lambda self, **k: name_like_input(**k)})()
			self.active_only = type('F', (), {'id': 'active_only', '__call__': lambda self, **k: Markup(f"<input type='checkbox' name='active_only' id='active_only' class='{k.get('class','form-check-input')}' {'checked' if active_only else ''}>") })()
			self.submit = lambda **k: Markup("<button class='btn btn-primary w-100'>Filter</button>")
	class _RowField:
		def __init__(self, idx: int, op: Operator):
			self.idx = idx
			self.op = op
		def operator_id(self, value=None):
			val = value or (self.op.id if self.op else '')
			return Markup(f"<input type='hidden' name='rows-{self.idx}-operator_id' value='{val}'>")
		def is_night_shift(self, **k):
			checked = ' checked' if (self.op.is_night_shift if self.op else False) else ''
			return Markup(f"<input type='checkbox' name='rows-{self.idx}-is_night_shift' class='{k.get('class','form-check-input')}'{checked}>")
		def night_checkbox(self, name: str, plan: NightWeekPlan | None, **k):
			val = bool(getattr(plan, name)) if plan else False
			c = ' checked' if val else ''
			return Markup(f"<input type='checkbox' name='rows-{self.idx}-night-{name}' class='{k.get('class','form-check-input form-check-input-sm')}'{c}>")
	class Form:
		csrf_token = ''
		def __init__(self, ops):
			self.rows = [_RowField(i, o) for i, o in enumerate(ops)]
		def submit(self, **k): return Markup("<button class='btn btn-success'>Save</button>")
	filter_form = FilterForm()
	form = Form(operators)

	# Load week plans for preview
	plan_ids = [op.id for op in operators]
	plans = {p.operator_id: p for p in NightWeekPlan.query.filter(NightWeekPlan.operator_id.in_(plan_ids), NightWeekPlan.week_monday == plan_week).all()} if plan_ids else {}

	from flask import current_app
	use_night_plan = bool(current_app.config.get('USE_NIGHT_PLAN', False))
	return render_template(
		'attendance/operators.html',
		operators=operators,
		filter_form=filter_form,
		form=form,
		plans=plans,
		plan_week=plan_week,
		use_night_plan=use_night_plan,
	)


@attendance_bp.route('/attendance/operators/night', methods=['GET', 'POST'])
@login_required
def night_plan():
	operator_id = request.args.get('operator_id', type=int) or request.form.get('operator_id', type=int)
	from .helpers import parse_date, iso_monday
	week_any = parse_date(request.args.get('week')) or parse_date(request.form.get('week_monday'))
	week_monday = iso_monday(week_any or date.today())

	if request.method == 'POST':
		# Upsert plan
		p = NightWeekPlan.query.filter_by(operator_id=operator_id, week_monday=week_monday).first()
		if not p:
			p = NightWeekPlan(operator_id=operator_id, week_monday=week_monday)
			db.session.add(p)
		p.mon = bool(request.form.get('mon'))
		p.tue = bool(request.form.get('tue'))
		p.wed = bool(request.form.get('wed'))
		p.thu = bool(request.form.get('thu'))
		p.fri = bool(request.form.get('fri'))
		p.sat = bool(request.form.get('sat'))
		p.sun = bool(request.form.get('sun'))
		p.notes = request.form.get('notes')
		db.session.commit()
		flash('Night plan saved.', 'success')
		return redirect(url_for('attendance.operators'))

	# Render form
	ops = Operator.query.filter_by(active=True).order_by(Operator.full_name.asc().nullslast(), Operator.username.asc()).all()
	p = NightWeekPlan.query.filter_by(operator_id=operator_id, week_monday=week_monday).first() if operator_id else None

	class Form:
		def hidden_tag(self): return ''
		def operator_id(self, **k):
			# simple select
			options = []
			for o in ops:
				sel = ' selected' if (operator_id and o.id == operator_id) else ''
				options.append(f"<option value='{o.id}'{sel}>{o.full_name or o.username}</option>")
			return f"<select name='operator_id' class='{k.get('class','')}'>{''.join(options)}</select>"
		def week_monday(self, **k):
			val = week_monday.isoformat()
			return f"<input name='week_monday' type='date' class='{k.get('class','')}' value='{val}'>"
		def _cb(self, name, val, **k):
			checked = ' checked' if val else ''
			return f"<input type='checkbox' name='{name}' class='{k.get('class','')}'{checked}>"
		def mon(self, **k): return self._cb('mon', p.mon if p else False, **k)
		def tue(self, **k): return self._cb('tue', p.tue if p else False, **k)
		def wed(self, **k): return self._cb('wed', p.wed if p else False, **k)
		def thu(self, **k): return self._cb('thu', p.thu if p else False, **k)
		def fri(self, **k): return self._cb('fri', p.fri if p else False, **k)
		def sat(self, **k): return self._cb('sat', p.sat if p else False, **k)
		def sun(self, **k): return self._cb('sun', p.sun if p else False, **k)
		def notes(self, **k):
			val = (p.notes if p and p.notes else '')
			return f"<textarea name='notes' class='{k.get('class','')}' rows='{k.get('rows','2')}' placeholder='{k.get('placeholder','')}'>{val}</textarea>"
		def submit(self, **k): return f"<button class='{k.get('class','btn btn-primary')}'>Save</button>"
	form = Form()
	return render_template('attendance/night_plan.html', form=form)


@attendance_bp.route('/attendance/operators/<int:operator_id>/edit', methods=['GET', 'POST'])
@login_required
def operator_edit(operator_id: int):
	op = Operator.query.get_or_404(operator_id)
	if request.method == 'POST':
		# Basic validation/parsing
		op.currency = (request.form.get('currency') or 'ZAR').strip()[:8]
		try:
			op.hourly_rate = float(request.form.get('hourly_rate') or 0)
		except Exception:
			op.hourly_rate = 0.0
		op.employment_start_date = parse_date(request.form.get('employment_start_date'))
		try:
			op.work_days_per_week = int(request.form.get('work_days_per_week') or 5)
		except Exception:
			op.work_days_per_week = 5

		# Entitlements
		def _f(name, default):
			try:
				return float(request.form.get(name) or default)
			except Exception:
				return default
		op.annual_entitlement_days = _f('annual_entitlement_days', 15.0)
		op.sick_entitlement_days = _f('sick_entitlement_days', 30.0)
		op.family_resp_days_per_year = _f('family_resp_days_per_year', 3.0)
		op.special_study_days_per_year = _f('special_study_days_per_year', 0.0)

		# Opening balances
		op.opening_annual_days = _f('opening_annual_days', 0.0)
		op.opening_sick_days = _f('opening_sick_days', 0.0)
		op.opening_family_days = _f('opening_family_days', 0.0)
		op.opening_special_days = _f('opening_special_days', 0.0)
		op.opening_balance_asof = parse_date(request.form.get('opening_balance_asof'))

		db.session.commit()
		flash('Operator payroll/leave settings saved.', 'success')
		return redirect(url_for('attendance.operators'))

	# Render simple form
	return render_template('attendance/operator_edit.html', op=op)
