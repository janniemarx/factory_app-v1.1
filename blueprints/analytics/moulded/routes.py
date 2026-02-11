# routes.py
from datetime import datetime
from flask import Blueprint, render_template, request
from flask_login import login_required

from .forms import MouldedAnalyticsFilterForm
from .helpers import get_moulded_analytics, get_operators_list
from models.moulded_cornice import MouldedMachine


moulded_analytics_bp = Blueprint(
    "moulded_analytics",
    __name__,
    template_folder='../../templates/analytics/moulded'
)


def _coerce_nonzero(value):
    """Return int(value) if truthy and not 0, else None."""
    try:
        iv = int(value)
        return iv if iv != 0 else None
    except Exception:
        return None


@moulded_analytics_bp.route("/analytics", methods=["GET", "POST"])
@login_required
def dashboard():
    # Instantiate empty form first; we’ll populate choices before validation
    form = MouldedAnalyticsFilterForm()

    # ----- Dynamic choices -----
    # Operators
    ops = get_operators_list()
    form.operator_id.choices = [(0, '-- All Operators --')] + [
        (o.id, (o.full_name or o.username)) for o in ops
    ]

    # Machines
    machines = MouldedMachine.query.order_by(MouldedMachine.id.asc()).all()
    form.machine_id.choices = [(0, '-- All Machines --')] + [(m.id, m.name) for m in machines]

    # Default period on first load
    if request.method == "GET" and not form.period.data:
        form.period.data = "today"

    # Bind POST data and validate (won’t error on GET)
    form.process(request.form if request.method == "POST" else None)
    form.validate()  # we don’t block on validation; fields are Optional

    # Selected filters (keep 0 == "All")
    selected_mould = form.mould_number.data or 0
    selected_operator = form.operator_id.data or 0
    selected_machine = form.machine_id.data or 0
    selected_period = form.period.data or "today"
    date_from = form.date_from.data
    date_to = form.date_to.data

    # Build analytics payload (helpers now compute made vs boxed and wastage%)
    analytics = get_moulded_analytics(
        mould_number=_coerce_nonzero(selected_mould),
        operator_id=_coerce_nonzero(selected_operator),
        machine_id=_coerce_nonzero(selected_machine),
        date_from=date_from,
        date_to=date_to,
        period=selected_period,
    )

    # This can be handy in the template for showing a “Filters active” pill, etc.
    has_filters = any([
        _coerce_nonzero(selected_mould),
        _coerce_nonzero(selected_operator),
        _coerce_nonzero(selected_machine),
        date_from,
        date_to,
        selected_period not in ("today",),  # treat today as the “default”
    ])

    return render_template(
        "analytics/moulded/dashboard.html",
        form=form,
        analytics=analytics,
        now=datetime.now(),
        has_filters=has_filters,
    )
