from datetime import date, datetime, timedelta
from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required
from .routes import attendance_bp
from models import db
from models.attendance import AttendanceSyncRun, AttendanceEvent
from .helpers import parse_date
from .db_helpers import recompute_range, propose_overtime_for_range, recompute_for_ingest_window, propose_overtime_for_days
from services.sync_service import fetch_employees_from_device, fetch_events


@attendance_bp.route('/attendance/sync', methods=['GET', 'POST'], endpoint='sync')
@login_required
def sync_home():
	# Simple form shim that emits safe HTML (no WTForms dependency)
	from markupsafe import Markup

	# Determine defaults
	_today = date.today()
	_default_from = _today - timedelta(days=1)
	_default_to = _today

	class Form:
		def __init__(self, from_date=_default_from, to_date=_default_to):
			self._from = from_date
			self._to = to_date

		def hidden_tag(self):
			return Markup("")

		def from_date(self, **k):
			cls = k.get('class', 'form-control')
			id_ = k.get('id', 'from_date')
			val = (self._from or _default_from).isoformat()
			return Markup(f"<input type='date' name='from_date' class='{cls}' id='{id_}' value='{val}'>")

		def to_date(self, **k):
			cls = k.get('class', 'form-control')
			id_ = k.get('id', 'to_date')
			val = (self._to or _default_to).isoformat()
			return Markup(f"<input type='date' name='to_date' class='{cls}' id='{id_}' value='{val}'>")

		def submit(self, **k):
			cls = k.get('class', 'btn btn-primary')
			return Markup(f"<button name='action' value='sync' class='{cls}'>Sync Now</button>")

		def quick_sync(self, **k):
			cls = k.get('class', 'btn btn-warning')
			return Markup(f"<button name='action' value='quick_sync' class='{cls}'>Quick Sync</button>")

		def sync_all(self, **k):
			cls = k.get('class', 'btn btn-outline-secondary')
			return Markup(f"<button name='action' value='sync_all' class='{cls}'>Sync All</button>")

	if request.method == 'POST':
		action = request.form.get('action') or 'sync'

		# Determine date range
		if action == 'sync_all':
			# From earliest known event (or a wide default) to today
			min_ts = db.session.query(db.func.min(AttendanceEvent.timestamp)).scalar()
			from_d = (min_ts.date() if min_ts else date(2022, 1, 1))
			to_d = date.today()
		else:
			from_d = parse_date(request.form.get('from_date')) or _default_from
			to_d = parse_date(request.form.get('to_date')) or _default_to
			if from_d > to_d:
				flash('From date cannot be after To date.', 'danger')
				return redirect(url_for('attendance.sync'))

		# Create sync run record
		run = AttendanceSyncRun(
			from_date=from_d,
			to_date=to_d,
			status='ok',
			started_at=datetime.utcnow(),
			fetched_events=0,
			inserted_events=0,
		)
		db.session.add(run)
		db.session.commit()

		try:
			if action == 'sync_all':
				# Full rescan: fixed base to today
				from services.sync_service import upsert_operators_from_map
				emp_map = fetch_employees_from_device()
				try:
					upsert_operators_from_map(emp_map)
				except Exception:
					pass
				from flask import current_app
				cfg_start = (current_app.config.get('SYNC_ALL_START') or '').strip() or None
				try:
					from_d = datetime.fromisoformat(cfg_start).date() if cfg_start else date(2000, 1, 1)
				except Exception:
					from_d = date(2000, 1, 1)
				to_d = date.today()
				from blueprints.attendance.db_helpers import insert_events_from_device
				# Process in month-sized chunks to reduce device pagination and memory
				fetched = 0
				inserted = 0
				cursor = from_d.replace(day=1)
				while cursor <= to_d:
					# month end
					next_month = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
					chunk_end = min(next_month - timedelta(days=1), to_d)
					events_iter = fetch_events(cursor, chunk_end, emp_map)
					f_i, i_i = insert_events_from_device(events_iter)
					fetched += f_i
					inserted += i_i
					cursor = next_month
				stats = {
					'fetched_events': fetched,
					'inserted_events': inserted,
					'min_date': from_d,
					'max_date': to_d,
					'errors': None,
				}
			elif action == 'quick_sync':
				# Current and previous month
				from services.sync_service import upsert_operators_from_map
				emp_map = fetch_employees_from_device()
				try:
					upsert_operators_from_map(emp_map)
				except Exception:
					pass
				# compute first day of previous month
				_today_local = date.today()
				first_this = _today_local.replace(day=1)
				prev_month_last = first_this - timedelta(days=1)
				first_prev = prev_month_last.replace(day=1)
				from_d = first_prev
				to_d = _today_local
				from blueprints.attendance.db_helpers import insert_events_from_device
				events_iter = fetch_events(from_d, to_d, emp_map)
				fetched, inserted = insert_events_from_device(events_iter)
				stats = {
					'fetched_events': fetched,
					'inserted_events': inserted,
					'min_date': from_d,
					'max_date': to_d,
					'errors': None,
				}
			else:
				# Range sync: fetch employees, then events in [from_d, to_d]
				from services.sync_service import upsert_operators_from_map
				emp_map = fetch_employees_from_device()
				# Ensure operators exist/updated so events get linked with operator_id
				try:
					upsert_operators_from_map(emp_map)
				except Exception:
					pass
				from blueprints.attendance.db_helpers import insert_events_from_device
				events_iter = fetch_events(from_d, to_d, emp_map)
				fetched, inserted = insert_events_from_device(events_iter)
				stats = {
					'fetched_events': fetched,
					'inserted_events': inserted,
					'min_date': from_d,
					'max_date': to_d,
					'errors': None,
				}

			# update run record
			run.fetched_events = int(stats.get('fetched_events') or 0)
			run.inserted_events = int(stats.get('inserted_events') or 0)
			run.from_date = stats.get('min_date') or from_d
			run.to_date = stats.get('max_date') or to_d
			run.ended_at = datetime.utcnow()
			run.status = 'ok' if not stats.get('errors') else 'error'
			run.errors = stats.get('errors')
			db.session.commit()

			# For Sync All and Quick Sync, always recompute/propose; for Sync Now we do incremental recompute
			recompute = (action in ('sync_all', 'quick_sync', 'sync'))
			if stats.get('errors'):
				flash(f"Sync finished with errors: {stats['errors']}", 'danger')
			else:
				if recompute:
					# Incremental recompute: only days touched by this ingest window
					impacted = recompute_for_ingest_window(run.started_at, run.ended_at)
					propose_overtime_for_days(impacted)
					flash(f"Synced {run.fetched_events} events (inserted {run.inserted_events}); recomputed and proposed OT for {len(impacted)} impacted days.", 'success')
				else:
					flash(f"Synced {run.fetched_events} events (inserted {run.inserted_events}) for {run.from_date} → {run.to_date} — recompute skipped.", 'info')
		except Exception as e:
			run.status = 'error'
			run.ended_at = datetime.utcnow()
			run.errors = str(e)
			db.session.commit()
			flash(f'Sync failed: {e}', 'danger')

		# For Sync All, clear filters by redirecting to base path with no query
		if action == 'sync_all':
			return redirect(url_for('attendance.sync'))
		return redirect(url_for('attendance.sync', **{}))

	recent_runs = AttendanceSyncRun.query.order_by(AttendanceSyncRun.started_at.desc()).limit(20).all()
	# Pre-fill form with either query args or sensible defaults
	q_from = parse_date(request.args.get('from')) or _default_from
	q_to = parse_date(request.args.get('to')) or _default_to
	return render_template('attendance/sync.html', form=Form(q_from, q_to), recent_runs=recent_runs)
