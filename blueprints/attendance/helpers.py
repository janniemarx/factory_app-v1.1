from __future__ import annotations
from datetime import date, datetime, timedelta
from typing import Optional, Tuple, List


def parse_date(s: Optional[str]) -> Optional[date]:
	if not s:
		return None
	try:
		return date.fromisoformat(s)
	except Exception:
		return None


def iso_monday(d: date) -> date:
	# ISO Monday for a given date
	return d - timedelta(days=(d.weekday()))


def week_bounds_from_any(d: date) -> Tuple[date, date]:
	"""Return Monday..Saturday bounds for the given date's ISO week."""
	mon = iso_monday(d)
	sat = mon + timedelta(days=5)
	return mon, sat


def room_filter_choices() -> List[Tuple[Optional[int], str]]:
	return [
		(None, "All rooms"),
		(1, "Room 1"),
		(2, "Room 2"),
		(3, "Room 3"),
	]
