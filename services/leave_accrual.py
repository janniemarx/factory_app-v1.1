from __future__ import annotations
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Dict, Tuple, Iterable
from models.operator import Operator
from models.attendance import LeaveRequest
from models import db

# --- Helpers ---

def daterange(start: date, end: date) -> Iterable[date]:
    cur = start
    while cur <= end:
        yield cur
        cur += timedelta(days=1)


def is_workday(d: date, work_days_per_week: int = 5) -> bool:
    # Simple: Mon-Fri = 5, Mon-Sat = 6
    if work_days_per_week >= 6:
        return d.weekday() <= 5  # Mon-Sat
    return d.weekday() <= 4      # Mon-Fri


def working_days_between(start: date, end: date, work_days_per_week: int = 5) -> int:
    return sum(1 for d in daterange(start, end) if is_workday(d, work_days_per_week))


@dataclass
class LeaveBalances:
    annual_total: float
    annual_used: float
    annual_available: float

    sick_total_cycle: float
    sick_used_cycle: float
    sick_available_cycle: float

    family_total_year: float
    family_used_year: float
    family_available_year: float


# --- Accrual Logic ---

def _annual_entitlement_for_period(op: Operator, start: date, end: date) -> float:
    """Monthly pro-rata annual leave accrual between two dates, using op.annual_entitlement_days per year.
       Simplify: accrue uniformly by month boundary. If start before employment_start_date, shift to employment date.
    """
    if op.employment_start_date and end < op.employment_start_date:
        return 0.0
    anchor = max(start, op.employment_start_date or start)
    # Accrue 1/12 of annual entitlement per started month fully within [anchor, end]
    months = set((d.year, d.month) for d in daterange(anchor, end))
    per_month = (op.annual_entitlement_days or 15.0) / 12.0
    return round(len(months) * per_month, 3)


def _sick_entitlement_cycle(op: Operator, today: date) -> Tuple[date, date, float]:
    """Return the 36-month cycle window and total days allowed for the cycle.
       BCEA: first 6 months on a new job: 1 day per 26 days worked; afterwards 30 days per 36 months (5-day week).
       We'll simplify to: full entitlement for the 36-month window starting at employment_start_date or opening as-of year.
    """
    start = (op.employment_start_date or today).replace(day=1)
    # Pick the cycle that contains 'today' counting by 36-month blocks
    while (start.year, start.month) <= (today.year, today.month):
        cycle_end = (start.replace(year=start.year + 3) - timedelta(days=1))
        if start <= today <= cycle_end:
            break
        start = start.replace(year=start.year + 3)
    total = float(op.sick_entitlement_days or 30.0)
    return start, cycle_end, total


def _family_entitlement_year(op: Operator, year: int) -> float:
    return float(op.family_resp_days_per_year or 3.0)


def _sum_used(op: Operator, leave_type: str, start: date, end: date) -> float:
    q = (LeaveRequest.query
        .filter(LeaveRequest.operator_id == op.id)
        .filter(LeaveRequest.status == 'approved')
        .filter(LeaveRequest.leave_type == leave_type)
        .filter(LeaveRequest.start_date <= end)
        .filter(LeaveRequest.end_date >= start))
    used_days = 0.0
    for lr in q.all():
        rng_start = max(lr.start_date, start)
        rng_end = min(lr.end_date, end)
        if rng_start > rng_end:
            continue
        # Use working days counting; hours_per_day defaults to 8 but we treat a working day as 1 day
        used_days += working_days_between(rng_start, rng_end, op.work_days_per_week or 5)
    return float(used_days)


def compute_balances(op: Operator, today: date | None = None) -> LeaveBalances:
    today = today or date.today()

    # Opening balances contribute to starting available on/after as-of date
    opening_asof = op.opening_balance_asof

    # Annual leave
    annual_total = 0.0
    if opening_asof:
        # Accrue from opening_asof month to current month inclusive
        annual_total += op.opening_annual_days or 0.0
        annual_total += _annual_entitlement_for_period(op, opening_asof, today)
    else:
        # Accrue from employment start or today
        annual_total += _annual_entitlement_for_period(op, op.employment_start_date or today, today)
    annual_used = _sum_used(op, 'annual', date(today.year, 1, 1), today)
    annual_available = max(0.0, round(annual_total - annual_used, 3))

    # Sick leave (36-month cycle)
    cyc_start, cyc_end, cyc_total = _sick_entitlement_cycle(op, today)
    sick_total = (op.opening_sick_days or 0.0) + cyc_total
    sick_used = _sum_used(op, 'sick', cyc_start, today)
    sick_available = max(0.0, round(sick_total - sick_used, 3))

    # Family responsibility (per calendar year)
    fam_total = (op.opening_family_days or 0.0) + _family_entitlement_year(op, today.year)
    fam_used = _sum_used(op, 'family', date(today.year, 1, 1), today)
    fam_available = max(0.0, round(fam_total - fam_used, 3))

    return LeaveBalances(
        annual_total=round(annual_total, 3),
        annual_used=round(annual_used, 3),
        annual_available=annual_available,
        sick_total_cycle=round(sick_total, 3),
        sick_used_cycle=round(sick_used, 3),
        sick_available_cycle=sick_available,
        family_total_year=round(fam_total, 3),
        family_used_year=round(fam_used, 3),
        family_available_year=fam_available,
    )


def estimate_request_days(op: Operator, start: date, end: date) -> float:
    return float(working_days_between(start, end, op.work_days_per_week or 5))
