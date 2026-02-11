"""Attendance database helpers (ingestion, recomputation, rollups).

Minimal, pragmatic implementation to unblock UI:
- recompute_day/range rolls up AttendanceEvent -> AttendanceDaily.
- simple weekday/weekend bucketization.
"""

from __future__ import annotations
from datetime import datetime, date, time, timedelta
from typing import Iterable, Optional, Tuple, Dict, Iterable as IterableType, Set
from types import SimpleNamespace

from models import db
from models.attendance import AttendanceEvent, AttendanceDaily, OvertimeRequest, NightWeekPlan, WorkSchedule
from models.operator import Operator
from sqlalchemy import text
from .helpers import iso_monday
from flask import current_app


def _day_bounds(d: date) -> Tuple[datetime, datetime]:
	start = datetime.combine(d, time.min)
	end = datetime.combine(d, time.max)
	return start, end


def _has_night(op: Operator, d: date) -> bool:
	"""Return whether operator is assigned a night for the evening of date d (18:00→+06:00)."""
	# If manual plans are disabled, rely solely on event-based detection elsewhere
	use_plan = bool(current_app.config.get('USE_NIGHT_PLAN', False))
	if not use_plan:
		return False
	# Try weekly plan
	plan = NightWeekPlan.query.filter_by(operator_id=op.id, week_monday=iso_monday(d)).one_or_none()
	dow = d.weekday()  # 0=Mon..6=Sun
	if plan:
		flags = [plan.mon, plan.tue, plan.wed, plan.thu, plan.fri, plan.sat, plan.sun]
		return bool(flags[dow])
	# Fallback: global flag
	return bool(getattr(op, "is_night_shift", False))


def _merge_intervals(intervals: list[Tuple[datetime, datetime]]) -> list[Tuple[datetime, datetime]]:
	if not intervals:
		return []
	intervals = sorted(intervals, key=lambda x: x[0])
	merged = [intervals[0]]
	for s, e in intervals[1:]:
		ls, le = merged[-1]
		if s <= le:
			merged[-1] = (ls, max(le, e))
		else:
			merged.append((s, e))
	return merged


def _overlap(a: Tuple[datetime, datetime], b: Tuple[datetime, datetime]) -> int:
	"""Return overlap seconds between intervals a and b."""
	s = max(a[0], b[0])
	e = min(a[1], b[1])
	if e <= s:
		return 0
	return int((e - s).total_seconds())


def _weekly_rebalance(start_date: date, end_date: date, operator_ids: Optional[Iterable[int]] = None) -> None:
	"""Reclassify weekday OT1 back to normal within each ISO week up to weekly target hours.

	Policy:
	- Weekly normal target is `NORMAL_WEEKLY_HOURS` (default 40h).
	- Consider only weeknights (Mon–Fri nights). Move OT1 seconds back into normal seconds until the
	  weekly total normal reaches the target. Prefer to fill later days first (Fri→Mon).
	  Day-shift OT should remain as OT and must not be used to fill the weekly 40h.
	- OT2 (Sundays) not touched.
	"""
	from models.attendance import AttendanceDaily
	weekly_target = int(float(current_app.config.get('NORMAL_WEEKLY_HOURS', 40)) * 3600)

	# Gather all days in range per operator grouped by ISO week
	q = AttendanceDaily.query.filter(AttendanceDaily.day >= start_date, AttendanceDaily.day <= end_date)
	if operator_ids:
		q = q.filter(AttendanceDaily.operator_id.in_(list(operator_ids)))
	rows = q.all()
	by_key: Dict[Tuple[int, int], list[AttendanceDaily]] = {}
	for drow in rows:
		key = (drow.operator_id, drow.day.isocalendar().week)
		by_key.setdefault(key, []).append(drow)

	# Helper: detect a night-shift daily rollup heuristically from first_in/last_out local times
	def _tz_offset() -> timedelta:
		try:
			s = str(current_app.config.get('DEVICE_TZ_OFFSET', '+02:00')).strip()
			sign = 1 if s[0] == '+' else -1
			hh, mm = s[1:].split(':')
			return timedelta(hours=sign*int(hh), minutes=sign*int(mm))
		except Exception:
			return timedelta(hours=2)
	TZ = _tz_offset()
	def to_local(dt: Optional[datetime]) -> Optional[datetime]:
		return (dt + TZ) if dt else None
	def _is_weeknight(d: AttendanceDaily) -> bool:
		if d.day.weekday() >= 5:
			return False
		fi = to_local(d.first_in); lo = to_local(d.last_out)
		if not fi and not lo:
			return False
		# Night if first_in is evening (>=17:30) OR last_out is next morning (<=06:15) and spans midnight
		try:
			from datetime import time as _t
			thr_ev = _t(17,30)
			thr_morn = _t(6,15)
			is_evening_start = bool(fi and fi.time() >= thr_ev)
			is_next_morning_checkout = bool(lo and lo.time() <= thr_morn and (fi and lo.date() > fi.date() or lo.date() > d.day))
			worked_ok = (d.worked_seconds or 0) >= 6*3600
			return worked_ok and (is_evening_start or is_next_morning_checkout)
		except Exception:
			return False

	for (op_id, weekno), days in by_key.items():
		# Sort days Mon..Sun; we’ll refill from Fri backward
		days.sort(key=lambda r: r.day)
		# Compute current normal seconds (Mon–Fri only)
		normal_sum = sum((r.normal_seconds or 0) for r in days if r.day.weekday() < 5)
		if normal_sum >= weekly_target:
			continue
		need = weekly_target - normal_sum
		# Iterate Fri->Mon, move OT1 -> normal but ONLY from night-shift weekdays
		for r in sorted([d for d in days if d.day.weekday() < 5 and _is_weeknight(d)], key=lambda r: r.day, reverse=True):
			if need <= 0:
				break
			avail = max(0, (r.ot1_seconds or 0))
			if avail <= 0:
				continue
			move = min(avail, need)
			r.ot1_seconds = avail - move
			r.normal_seconds = (r.normal_seconds or 0) + move
			need -= move
	# Do not commit here; caller commits


def _pair_events(events: list[AttendanceEvent]) -> Tuple[int, int, list[Tuple[datetime, datetime]]]:
	"""Return (missing_in, missing_out, pairs).
	Events should be sorted by timestamp. We try to pair IN -> OUT in order.
	"""
	pairs: list[Tuple[datetime, datetime]] = []
	missing_in = 0
	missing_out = 0
	cur_in: Optional[datetime] = None
	for ev in events:
		if ev.event_type == 'check_in':
			# If we already have an IN without OUT, consider previous missing_out and start new
			if cur_in is not None:
				missing_out += 1
			cur_in = ev.timestamp
		elif ev.event_type == 'check_out':
			if cur_in is None:
				# stray out
				missing_in += 1
				continue
			if ev.timestamp > cur_in:
				pairs.append((cur_in, ev.timestamp))
			else:
				# ignore reversed
				missing_out += 1
			cur_in = None
	if cur_in is not None:
		missing_out += 1
	return missing_in, missing_out, pairs


def recompute_day(op: Operator, d: date) -> AttendanceDaily:
	"""Recompute one operator/day rollup with night-shift attribution and day rules.

	Rules implemented:
	- Lunch: subtract schedule.lunch_minutes (default 60) from daytime (07:00–16:00 local) if >= 6h worked in that window.
	- In-rounding: if first check-in before 06:10 local → pre‑07:00 counts as OT; if between 06:10 and 07:00 → ignore until 07:00.
	- Out-rounding: post‑16:00 counts as OT only if clock-out is after 16:50 local; otherwise ignore 16:00–16:50.
	- Weekdays: normal up to 8h from daytime after lunch; OT1 = pre‑07 + post‑16 (and any remainder beyond 8h, which should be none).
	- Weekends: all worked in attribution windows is OT2.
	All times are evaluated in local timezone defined by DEVICE_TZ_OFFSET, while events are stored as naive UTC.
	"""
	# Helper: timezone offset from config (e.g., '+02:00')
	def _tz_offset() -> timedelta:
		# Default to +02:00 to match UI display filter
		s = str(current_app.config.get('DEVICE_TZ_OFFSET', '+02:00'))
		try:
			sign = 1 if s.strip()[0] == '+' else -1
			hh, mm = s.strip()[1:].split(':')
			return timedelta(hours=sign*int(hh), minutes=sign*int(mm))
		except Exception:
			return timedelta(0)

	tz_off = _tz_offset()
	def loc(dt_time: time, day: date = None) -> datetime:
		base_day = d if day is None else day
		# Convert local time on base_day to stored naive UTC by subtracting tz offset
		return datetime.combine(base_day, dt_time) - tz_off

	# Build attribution windows for this day in local-time anchored frames
	cur_night = _has_night(op, d)
	prev_night = _has_night(op, d - timedelta(days=1))

	# Local day boundaries mapped to stored naive UTC
	day_start = loc(time(0, 0, 0))
	end_of_day = loc(time(0, 0, 0), d + timedelta(days=1))  # next midnight local
	six_local = loc(time(6, 0, 0))
	# Allow late checkout grace for pairing (but we won't attribute those minutes to night)
	grace_min = int(current_app.config.get('NIGHT_END_GRACE_MINUTES', 15))
	six_local_plus = six_local + timedelta(minutes=grace_min)
	six_next_local = loc(time(6, 0, 0), d + timedelta(days=1))
	six_next_local_plus = six_next_local + timedelta(minutes=grace_min)
	eighteen_local = loc(time(18, 0, 0))
	# Allow early evening detection tolerance for night inference (not for pay)
	evening_tol_min = int(current_app.config.get('EVENING_START_TOLERANCE_MIN', 30))
	evening_detect_start = eighteen_local - timedelta(minutes=evening_tol_min)
	prev_eighteen_local = loc(time(18, 0, 0), d - timedelta(days=1))
	prev_noon_local = loc(time(12, 0, 0), d - timedelta(days=1))
	seven_local = loc(time(7, 0, 0))
	six_ten_local = loc(time(6, 10, 0))
	sixteen_local = loc(time(16, 0, 0))
	sixteen_fifty_local = loc(time(16, 50, 0))

	# Base window for the day: exclude 00:00–06:00 local if that belongs to previous night's attribution
	base_start = day_start if not prev_night else six_local
	base_end = end_of_day
	windows: list[Tuple[datetime, datetime]] = []
	if base_start < base_end:
		windows.append((base_start, base_end))
	if cur_night:
		# extend to +grace to capture late checkout for pairing
		windows.append((eighteen_local, six_next_local_plus))
	# Merge to get disjoint union
	eff_windows = _merge_intervals(windows)

	# Fetch events in a superset window (prev 12:00 local -> +06:00 local next day) to allow cross-evening/midnight pairing
	sup_start = prev_noon_local
	sup_end = six_next_local_plus
	events_all = (
		AttendanceEvent.query
		.filter(AttendanceEvent.operator_id == op.id,
				AttendanceEvent.timestamp >= sup_start,
				AttendanceEvent.timestamp <= sup_end)
		.order_by(AttendanceEvent.timestamp.asc())
		.all()
	)

	# Auto-detect night activity from actual events to make historical recomputations robust
	# even if NightWeekPlan entries are missing (e.g., in fresh test databases).
	def _has_any(s: datetime, e: datetime) -> bool:
		for ev in events_all:
			if s <= ev.timestamp < e:
				return True
		return False

	# Heuristics:
	# - prev_night: morning-only activity (00:00–06:00) with no daytime activity suggests
	#   a shift continuing from the previous evening; keep current-day pre-7 intact by
	#   not flagging prev_night if there is daytime activity.
	# - cur_night: any evening (>=18:00) or next-morning (00:00–06:00 next day) activity.
	_morning_act = _has_any(day_start, six_local_plus)
	_daytime_act = _has_any(seven_local, sixteen_local)
	_evening_act = _has_any(evening_detect_start, end_of_day)
	_next_morning_act = _has_any(end_of_day, six_next_local)

	# Specific signals used for robust night assignment
	def _has_checkout(s: datetime, e: datetime) -> bool:
		for ev in events_all:
			if s <= ev.timestamp < e and ev.event_type == 'check_out':
				return True
		return False

	def _has_checkin(s: datetime, e: datetime) -> bool:
		for ev in events_all:
			if s <= ev.timestamp < e and ev.event_type == 'check_in':
				return True
		return False

	noon_local = loc(time(12, 0, 0))
	_afternoon_in = _has_checkin(noon_local, end_of_day)
	_next_morning_checkout = _has_checkout(end_of_day, six_next_local_plus)

	# Stronger signal for previous night: any check_out before 06:00 (+grace) AND evidence
	# of an evening/nighshift on the previous calendar day (to avoid day-shift prep noise).
	if not prev_night:
		# Look for any check-in after noon on previous day as a strong signal of a night that spills past midnight
		prev_afternoon_in = _has_checkin(prev_noon_local, day_start)
		for ev in events_all:
			if day_start <= ev.timestamp < six_local_plus and ev.event_type == 'check_out' and prev_afternoon_in:
				prev_night = True
				break
	# If plan marks a night but there is no actual evening/next-morning activity and there IS daytime activity,
	# treat it as a day to avoid zero normal hours for day work by night-flagged operators.
	if cur_night and not (_evening_act or _next_morning_act) and _daytime_act:
		cur_night = False
	# Relax previous-night when there is no morning-after activity and we have daytime-only work today.
	if prev_night and not _morning_act and _daytime_act and not _evening_act:
		prev_night = False

	# Do NOT treat a mere evening check-out (e.g., 17:30–18:00) as a night start.
	# Only a next-morning check-out (spillover past midnight) should force cur_night here.
	if not cur_night:
		if _next_morning_checkout:
			cur_night = True

	# Rebuild windows if auto-detection flipped any flags
	if windows:
		# clear and rebuild using updated flags
		windows.clear()
		base_start = day_start if not prev_night else six_local
		if base_start < base_end:
			windows.append((base_start, base_end))
		if cur_night:
			windows.append((eighteen_local, six_next_local_plus))
		eff_windows = _merge_intervals(windows)

	# Filter events to attribution windows only for pairing and flags
	def _in_windows(ts: datetime) -> bool:
		for s, e in eff_windows:
			if s <= ts <= e:
				return True
		return False

	# Build a simple two-shift inference (safe rules):
	# - Do NOT force prev_night True solely because of a previous-day afternoon check-in; this causes
	#   legitimate early-morning day-shift arrivals to be dropped from attribution.
	# - If the first event today is an early check-in (<= 06:10), explicitly keep prev_night False so
	#   the 00:00–06:00 window belongs to today.
	first_today = next((ev for ev in events_all if day_start <= ev.timestamp < end_of_day), None)
	if first_today and first_today.event_type == 'check_in' and first_today.timestamp <= six_ten_local:
		prev_night = False
	# For current night, rely on actual evening check-in signal only
	cur_evening_in_any = any(
		ev.event_type == 'check_in' and evening_detect_start <= ev.timestamp < end_of_day
		for ev in events_all
	)
	if cur_evening_in_any:
		cur_night = True

	# Now restrict events to the effective windows (with night flags possibly adjusted)
	# Events inside effective windows; drop stray next-morning night checkouts when previous night flowed into today.
	events = [
		ev for ev in events_all
		if _in_windows(ev.timestamp)
		and not (prev_night and six_local <= ev.timestamp < six_local_plus and ev.event_type == 'check_out')
	]
	# If the first event is an accidental early-morning CHECK_OUT (before 06:00)
	# and there is a later day CHECK_IN, drop the stray OUT. This happens when
	# an operator taps "out" instead of "in" on arrival.
	if events and events[0].event_type == 'check_out' and events[0].timestamp < six_local:
		# Look for a later check_in within the current local day window
		_has_later_day_in = any(
			(ev.event_type == 'check_in' and seven_local <= ev.timestamp < end_of_day)
			for ev in events
		)
		if _has_later_day_in:
			# Safe to drop the stray OUT so pairing/flags behave sensibly
			events.pop(0)

	# If there is NO check_in at all and the first event is a pre‑07:00 check_out,
	# virtually treat that first event as a check_in for pairing/flags. This covers
	# the common mis-tap where the worker selects "out" on arrival. We do not mutate
	# the DB event; we only substitute a synthetic check_in object in the local list.
	if events and events[0].event_type == 'check_out' and events[0].timestamp < seven_local:
		if not any(ev.event_type == 'check_in' for ev in events):
			synthetic_in = SimpleNamespace(timestamp=events[0].timestamp, event_type='check_in')
			events = [synthetic_in] + events[1:]
	# Heuristic cleanup: only drop an early-morning check-in if the very next event is
	# another check-in that clearly starts an evening/night (>= evening_detect_start).
	# Otherwise, keep both so we can convert the later check-in into a synthetic checkout
	# for day-shift long gaps (04:02 -> 16:01).
	if len(events) >= 2 and events[0].event_type == 'check_in' and events[1].event_type == 'check_in':
		if events[0].timestamp <= six_ten_local and events[1].timestamp <= seven_local:
			# very close morning double-tap – drop the first IN
			events.pop(0)
	# Additional cleanup for wrong-punch cases: if we see consecutive check-ins far apart
	# (common when the device labels both entries as IN), treat the later one as a checkout
	# for the purpose of pairing and flags. This is non-destructive: we do not mutate DB,
	# only adjust the local list by inserting a synthetic check_out at the later timestamp.
	# Minimum gap (in minutes) is configurable via CONSECUTIVE_IN_TO_OUT_MIN_MINUTES; default 240 (4h).
	try:
		min_gap_min = int(current_app.config.get('CONSECUTIVE_IN_TO_OUT_MIN_MINUTES', 240))
	except Exception:
		min_gap_min = 240
	min_gap = timedelta(minutes=min_gap_min)
	norm_events: list = []
	open_in_ts: Optional[datetime] = None
	for ev in events:
		if ev.event_type == 'check_in':
			if open_in_ts is None:
				open_in_ts = ev.timestamp
				norm_events.append(ev)
			else:
				# If the gap is large enough, consider the later check-in as a checkout
				if (ev.timestamp - open_in_ts) >= min_gap:
					# Append a synthetic checkout at the later timestamp
					norm_events.append(SimpleNamespace(timestamp=ev.timestamp, event_type='check_out'))
					open_in_ts = None
				else:
					# Too close – likely a double-tap. Keep only the newer IN to avoid zero-length segments.
					norm_events[-1] = ev
					open_in_ts = ev.timestamp
		else:
			# A proper checkout closes any open IN window
			norm_events.append(ev)
			open_in_ts = None
	# Use normalized list for pairing
	events = norm_events
	# Pair inside effective windows for both exception flags and pay attribution.
	# Rationale: using the broader superset window (prev noon -> next 06:00)
	# caused cross-day edges to be counted as missing for clean day-shift patterns
	# (e.g., previous day's 16:00 OUT + next day's ~04:00 IN). Restricting to the
	# effective windows avoids those false positives while still capturing valid
	# night segments (we already extend the night window to 06:00 + grace).
	# Pair while tolerating one leading OUT (before first IN) and one trailing IN (after last OUT)
	tmp_mi, tmp_mo, tmp_pairs = _pair_events(events)
	# If there is at least one proper IN/OUT pair inside windows, relax a single edge mismatch
	if tmp_pairs:
		# Leading OUT only (common when superset contributes a closing OUT that lands inside window start)
		if tmp_mi == 1 and (events and events[0].event_type == 'check_out'):
			tmp_mi = 0
		# Trailing IN only (common when next segment starts just before window end)
		if tmp_mo == 1 and (events and events[-1].event_type == 'check_in'):
			tmp_mo = 0
	mi, mo, _ = tmp_mi, tmp_mo, tmp_pairs
	_, _, pairs = _pair_events(events)
	# Clean night pattern: exactly one pair bridging evening->next morning; ensure flags are clear
	if len(pairs) == 1:
		fr, to = pairs[0]
		if fr.hour >= 15 or fr >= eighteen_local:
			# treat as a clean pair
			mi = False
			mo = False

	# Daytime and OT contributions (weekdays use special rules)
	daytime_seconds = 0
	pre7_ot = 0
	post16_ot = 0
	total_worked = 0  # includes all contributions within eff_windows prior to lunch subtraction
	night_core_seconds = 0  # for night shifts, only 18:00–24:00 + 00:00–06:00 count
	segs = 0

	seven_next_local = loc(time(7, 0, 0), d + timedelta(days=1))

	# Determine first actual check-in within attribution windows for rounding decisions
	first_in_event = next((ev for ev in events if ev.event_type == 'check_in'), None)
	last_out_event = next((ev for ev in reversed(events) if ev.event_type == 'check_out'), None)
	first_in_threshold_ok = bool(first_in_event and first_in_event.timestamp <= six_ten_local)
	for fr, to in pairs:
		# Clip to effective windows first
		clip_pairs: list[Tuple[datetime, datetime]] = []
		for w in eff_windows:
			s = max(fr, w[0]); e = min(to, w[1])
			if e > s:
				clip_pairs.append((s, e))
		if not clip_pairs:
			continue
		segs += 1
		for s, e in clip_pairs:
			total_worked += int((e - s).total_seconds())
			if d.weekday() < 5:
				# pre‑07:00 (current day) — only if first check-in is before 06:10
				if first_in_threshold_ok:
					pre7_ot += _overlap((s, e), (day_start, seven_local))
				# pre‑07:00 next morning belongs to the evening day when cur_night is True
				# cap at 06:00 hard stop (do not include 06:00–07:00 which is the early day shift setup)
				if cur_night:
					pre7_ot += _overlap((s, e), (end_of_day, six_next_local))
					# Night core time only counts from 18:00 to midnight and 00:00 to 06:00 next morning
					night_core_seconds += _overlap((s, e), (eighteen_local, end_of_day))
					night_core_seconds += _overlap((s, e), (end_of_day, six_next_local))
				# daytime overlap 07:00–16:00 local
				daytime_seconds += _overlap((s, e), (seven_local, sixteen_local))
				# post‑16:00 for day shift; for night shift, start at 18:00 and stop at midnight
				post_start = eighteen_local if cur_night else sixteen_local
				post_thresh = sixteen_fifty_local if not cur_night else eighteen_local
				if e > post_thresh:
					post16_ot += _overlap((s, e), (post_start, end_of_day))
			else:
				# weekend treated later as OT2; no special rounding here
				pass

	# Determine lunch minutes from schedule (fallback 60)
	def _lunch_minutes_for(op: Operator) -> int:
		try:
			# Priority: operator-specific, then room, then default
			sch = WorkSchedule.query.filter_by(operator_id=op.id, enabled=True).first()
			if not sch and op.room_number is not None:
				sch = WorkSchedule.query.filter_by(room_number=op.room_number, enabled=True).first()
			if not sch:
				sch = WorkSchedule.query.filter_by(is_default=True, enabled=True).first()
			return int(getattr(sch, 'lunch_minutes', 60) or 60)
		except Exception:
			return 60

	lunch_minutes = _lunch_minutes_for(op)
	lunch_seconds = lunch_minutes * 60

	# first_in/last_out based primarily on valid IN/OUT pairs.
	# If no pairs exist and there is a stray OUT, surface it for display so the Exceptions
	# page can show evidence (but flags still indicate missing IN).
	if pairs:
		first_in = pairs[0][0]
		last_out = pairs[-1][1]
	else:
		first_in = first_in_event.timestamp if first_in_event else None
		last_out = (last_out_event.timestamp if last_out_event else None)

	# Buckets per policy
	normal_seconds = 0
	ot1_seconds = 0
	ot2_seconds = 0
	if d.weekday() < 5:
		# Apply lunch once: day shift eats into daytime; night shift consumes into total_worked
		if cur_night:
			# Night paid time: only night core (18:00–24:00 + 00:00–06:00 next day)
			# Snap near-full nights to exactly 12h if within tolerance to avoid losing minutes
			snap_min = int(current_app.config.get('NIGHT_FULL_SNAP_MIN', 15))
			full = 12 * 3600
			if full - snap_min * 60 <= night_core_seconds <= full:
				night_core_seconds = full
			# Cap at 12h
			night_paid = min(night_core_seconds, full)
			if night_paid >= 6 * 3600:
				night_paid = max(0, night_paid - lunch_seconds)
			paid_total = max(0, night_paid)
			# Split into 8h normal + remainder OT1 to allow daily approvals for nights
			normal_seconds = min(8 * 3600, paid_total)
			ot1_seconds = max(0, paid_total - normal_seconds)
			worked = paid_total
		else:
			# Day shift: lunch only reduces daytime window
			if daytime_seconds >= 6 * 3600:
				daytime_paid = max(0, daytime_seconds - lunch_seconds)
			else:
				daytime_paid = daytime_seconds
			normal_seconds = min(daytime_paid, 8 * 3600)
			# OT1 = pre7 + post16 + any excess daytime beyond 8h (should be 0 normally)
			ot1_seconds = pre7_ot + post16_ot + max(0, daytime_paid - normal_seconds)
			worked = daytime_paid + pre7_ot + post16_ot
	elif d.weekday() == 5:
		# Saturday – all worked is OT1 (1.5x rate)
		worked = total_worked
		ot1_seconds = worked
	else:
		# Sunday – all worked is OT2 (2x rate)
		worked = total_worked
		ot2_seconds = worked

	daily = AttendanceDaily.query.filter_by(operator_id=op.id, day=d).one_or_none()
	if not daily:
		daily = AttendanceDaily(operator_id=op.id, day=d)
		db.session.add(daily)
	daily.emp_no = op.emp_no
	daily.first_in = first_in
	daily.last_out = last_out
	daily.worked_seconds = worked
	daily.segment_count = segs
	daily.missing_in = mi > 0
	daily.missing_out = mo > 0
	daily.normal_seconds = normal_seconds
	daily.ot1_seconds = ot1_seconds
	daily.ot2_seconds = ot2_seconds
	daily.computed_at = datetime.utcnow()
	return daily


def recompute_range(start_date: date, end_date: date, operator_ids: Optional[Iterable[int]] = None) -> int:
	"""Recompute for all operators in range; returns count of days touched."""
	if start_date > end_date:
		start_date, end_date = end_date, start_date
	q = Operator.query
	if operator_ids:
		q = q.filter(Operator.id.in_(list(operator_ids)))
	ops = q.all()
	d = start_date
	count = 0
	while d <= end_date:
		for op in ops:
			recompute_day(op, d)
			count += 1
		d += timedelta(days=1)
	# After day-level, apply weekly rebalance: move OT1 -> normal up to weekly target
	try:
		_weekly_rebalance(start_date, end_date, operator_ids)
	except Exception:
		pass
	db.session.commit()
	return count


def _impacted_days_by_ingest(started_at: datetime, ended_at: Optional[datetime] = None) -> Set[Tuple[int, date]]:
	"""Return set of (operator_id, day) for events ingested in a time window."""
	q = AttendanceEvent.query.filter(AttendanceEvent.ingested_at >= started_at)
	if ended_at:
		q = q.filter(AttendanceEvent.ingested_at <= ended_at)
	impacted: Set[Tuple[int, date]] = set()
	for ev in q.yield_per(1000):
		if not ev.operator_id:
			continue
		impacted.add((ev.operator_id, ev.timestamp.date()))
	return impacted


def recompute_for_ingest_window(started_at: datetime, ended_at: Optional[datetime] = None) -> Set[Tuple[int, date]]:
	"""Recompute only days that received newly ingested events in [started_at, ended_at].

	Returns the set of (operator_id, day) recomputed.
	"""
	impacted = _impacted_days_by_ingest(started_at, ended_at)
	if not impacted:
		return impacted
	# group by day per operator
	for op_id, d in impacted:
		op = Operator.query.get(op_id)
		if not op:
			continue
		recompute_day(op, d)
	db.session.commit()
	return impacted


def propose_overtime_for_days(pairs: IterableType[Tuple[int, date]]) -> int:
	"""Upsert OT proposals for specific (operator_id, day) pairs only."""
	count = 0
	for op_id, d in pairs:
		daily = AttendanceDaily.query.filter_by(operator_id=op_id, day=d).one_or_none()
		if not daily:
			continue
		for ot_type, seconds in (('ot1', daily.ot1_seconds or 0), ('ot2', daily.ot2_seconds or 0)):
			if seconds <= 0:
				continue
			hours = round(seconds / 3600.0, 2)
			ot = (OvertimeRequest.query
				.filter_by(operator_id=op_id, day=d, ot_type=ot_type)
				.one_or_none())
			if not ot:
				ot = OvertimeRequest(
					operator_id=op_id,
					day=d,
					ot_type=ot_type,
					source='auto',
					daily_id=daily.id,
					proposed_hours=hours,
					status='pending',
				)
				db.session.add(ot)
				count += 1
			else:
				ot.proposed_hours = hours
				ot.daily_id = daily.id
				count += 1
	db.session.commit()
	return count


def _validate_and_fix_event_sequence(operator_id: int, emp_no: str, new_event_type: str, new_timestamp: datetime) -> str:
	"""
	Validate event sequence and fix consecutive check_in events.
	Returns the corrected event_type.

	IMPORTANT: Look at the event immediately BEFORE the new event's timestamp,
	not the globally latest event. Using the global latest causes false positives
	when inserting historical adjustments (e.g., adding a 07:00 event for a day
	where a later day's last event was a check_in).
	"""
	if new_event_type == 'check_in' and operator_id:
		# Find the last event BEFORE the new timestamp for this operator
		prev_event = (
			AttendanceEvent.query
			.filter(
				AttendanceEvent.operator_id == operator_id,
				AttendanceEvent.timestamp < new_timestamp,
			)
			.order_by(AttendanceEvent.timestamp.desc())
			.first()
		)

		if prev_event and prev_event.event_type == 'check_in':
			# Convert this check_in to check_out to fix the immediate sequence
			return 'check_out'

	return new_event_type


def add_manual_event(operator: Operator, d: date, hhmm: str, ev_type: str, source: str = 'manual') -> AttendanceEvent:
	# Manual/adjust inputs are provided in LOCAL time. Convert to storage naive-UTC
	# to match device ingestion and recomputation windows.
	def _tz_offset() -> timedelta:
		s = str(current_app.config.get('DEVICE_TZ_OFFSET', '+02:00'))
		try:
			sign = 1 if s.strip()[0] == '+' else -1
			hh, mm = s.strip()[1:].split(':')
			return timedelta(hours=sign*int(hh), minutes=sign*int(mm))
		except Exception:
			return timedelta(0)

	tz_off = _tz_offset()
	ts_local = datetime.combine(d, time.fromisoformat(hhmm))
	ts = ts_local - tz_off
	
	# Only validate for manual events, not bulk sync
	if source in ('manual', 'adjust'):
		# Validate and fix event sequence
		corrected_ev_type = _validate_and_fix_event_sequence(operator.id, operator.emp_no, ev_type, ts)
		
		if corrected_ev_type != ev_type:
			from flask import flash
			flash(f'Warning: Consecutive check-in detected for {operator.full_name or operator.username}. '
				  f'Automatically converted to check-out at {hhmm}.', 'warning')
	else:
		corrected_ev_type = ev_type
	
	# If an identical manual/adjust event already exists (same UQ tuple), reuse it
	existing = (AttendanceEvent.query
		.filter_by(source=source,
				   emp_no=operator.emp_no,
				   timestamp=ts,
				   event_type=corrected_ev_type)
		.one_or_none())
	if existing:
		return existing

	ev = AttendanceEvent(
		operator_id=operator.id,
		emp_no=operator.emp_no,
		emp_name=operator.full_name or operator.username,
		timestamp=ts,
		event_type=corrected_ev_type,
		room_number=operator.room_number,
		source=source,
		source_uid=None,
	)
	db.session.add(ev)
	from sqlalchemy.exc import IntegrityError
	try:
		db.session.flush()  # get id early if needed
		return ev
	except IntegrityError:
		db.session.rollback()
		existing_again = (AttendanceEvent.query
			.filter_by(source=source,
					   emp_no=operator.emp_no,
					   timestamp=ts,
					   event_type=corrected_ev_type)
			.one_or_none())
		if existing_again:
			return existing_again
		raise


def propose_overtime_for_range(start_date: date, end_date: date, operator_ids: Optional[Iterable[int]] = None) -> int:
	"""Create or update OT proposals from AttendanceDaily buckets.

	Rules (basic):
	- For each day, if ot1_seconds > 0 -> upsert OvertimeRequest(ot_type='ot1', proposed_hours=ot1_seconds/3600).
	- If ot2_seconds > 0 -> upsert OvertimeRequest(ot_type='ot2', proposed_hours=ot2_seconds/3600).
	- Do NOT overwrite approved/rejected `hours` or `status`.
	- Always update `proposed_hours` and `daily_id` link.
	Returns count of proposals touched.
	"""
	if start_date > end_date:
		start_date, end_date = end_date, start_date

	q = AttendanceDaily.query.filter(AttendanceDaily.day >= start_date, AttendanceDaily.day <= end_date)
	if operator_ids:
		q = q.filter(AttendanceDaily.operator_id.in_(list(operator_ids)))

	rows = q.all()
	count = 0
	for d in rows:
		for ot_type, seconds in (('ot1', d.ot1_seconds or 0), ('ot2', d.ot2_seconds or 0)):
			if seconds <= 0:
				continue
			hours = round(seconds / 3600.0, 2)
			ot = (OvertimeRequest.query
				.filter_by(operator_id=d.operator_id, day=d.day, ot_type=ot_type)
				.one_or_none())
			if not ot:
				ot = OvertimeRequest(
					operator_id=d.operator_id,
					day=d.day,
					ot_type=ot_type,
					source='auto',
					daily_id=d.id,
					proposed_hours=hours,
					status='pending',
				)
				db.session.add(ot)
				count += 1
			else:
				# update proposal; keep final approval intact
				ot.proposed_hours = hours
				ot.daily_id = d.id
				count += 1
	# One commit for the batch
	db.session.commit()
	return count


def insert_events_from_device(events: Iterable[Dict], batch_commit: int = 1000) -> tuple[int, int]:
	"""Insert events yielded by device fetch.

	Each event dict is expected to have keys:
	- emp_no, emp_name, timestamp (naive UTC datetime), event_type ('check_in'/'check_out'),
	- room_number, source, source_uid

	Returns (fetched_count, inserted_count).
	"""
	backend = db.engine.url.get_backend_name()
	use_sqlite_insert_ignore = backend == 'sqlite'
	if use_sqlite_insert_ignore:
		# Speed up bulk inserts on SQLite
		try:
			db.session.execute(text("PRAGMA journal_mode = WAL"))
			db.session.execute(text("PRAGMA synchronous = NORMAL"))
			db.session.execute(text("PRAGMA temp_store = MEMORY"))
			db.session.commit()
		except Exception:
			pass

	# Build mapping of emp_no -> Operator for foreign key
	op_by_emp: Dict[str, Operator] = {op.emp_no: op for op in Operator.query.all() if op.emp_no}

	fetched = 0
	inserted = 0
	if use_sqlite_insert_ignore:
		stmt = text(
			"""
			INSERT OR IGNORE INTO attendance_events
			(operator_id, emp_no, emp_name, timestamp, event_type, room_number, source, source_uid, ingested_at)
			VALUES (:operator_id, :emp_no, :emp_name, :timestamp, :event_type, :room_number, :source, :source_uid, :ingested_at)
			"""
		)
		batch: list[Dict] = []
		for row in events:
			fetched += 1
			emp_no = row.get('emp_no')
			op = op_by_emp.get(emp_no)
			
			# TEMPORARILY DISABLED: Validate and fix event sequence
			# original_event_type = row.get('event_type')
			# corrected_event_type = _validate_and_fix_event_sequence(
			# 	op.id if op else None, 
			# 	emp_no, 
			# 	original_event_type, 
			# 	row.get('timestamp')
			# )
			
			batch.append({
				"operator_id": op.id if op else None,
				"emp_no": emp_no,
				"emp_name": row.get('emp_name'),
				"timestamp": row.get('timestamp'),
				"event_type": row.get('event_type'),  # Use original event_type
				"room_number": row.get('room_number'),
				"source": row.get('source', 'hikvision'),
				"source_uid": row.get('source_uid'),
				"ingested_at": datetime.utcnow(),
			})
			if len(batch) >= batch_commit:
				res = db.session.execute(stmt, batch)
				inserted += int(res.rowcount or 0)
				batch.clear()
				db.session.commit()
		# flush remainder
		if batch:
			res = db.session.execute(stmt, batch)
			inserted += int(res.rowcount or 0)
		db.session.commit()
		# final commit
		return fetched, inserted

	# Generic fallback (non-sqlite): rely on UQ constraint and ignore duplicates
	from sqlalchemy.exc import IntegrityError
	for row in events:
		fetched += 1
		emp_no = row.get('emp_no')
		op = op_by_emp.get(emp_no)
		
		# TEMPORARILY DISABLED: Validate and fix event sequence
		# original_event_type = row.get('event_type')
		# corrected_event_type = _validate_and_fix_event_sequence(
		# 	op.id if op else None, 
		# 	emp_no, 
		# 	original_event_type, 
		# 	row.get('timestamp')
		# )
		
		obj = AttendanceEvent(
			operator_id=op.id if op else None,
			emp_no=emp_no,
			emp_name=row.get('emp_name'),
			timestamp=row.get('timestamp'),
			event_type=row.get('event_type'),  # Use original event_type
			room_number=row.get('room_number'),
			source=row.get('source', 'hikvision'),
			source_uid=row.get('source_uid'),
		)
		db.session.add(obj)
		try:
			# flush per row to surface duplicates
			db.session.flush()
			inserted += 1
		except IntegrityError:
			db.session.rollback()
			# duplicate – ignore
		if fetched % batch_commit == 0:
			db.session.commit()
	# final commit
	db.session.commit()
	return fetched, inserted
