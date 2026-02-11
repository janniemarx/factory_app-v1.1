# blueprints/analytics/boxing/routes.py

from flask import Blueprint, render_template, request, flash
from flask_login import login_required
from .helpers import get_boxing_analytics
from models.operator import Operator
from .forms import BoxingAnalyticsFilterForm
from datetime import datetime

boxing_analytics_bp = Blueprint(
    "boxing_analytics", __name__,
    template_folder="../../templates/analytics/boxing"
)

@boxing_analytics_bp.route("/", methods=["GET", "POST"])
@login_required
def dashboard():
    form = BoxingAnalyticsFilterForm()
    # Choices as ints, 0 = All
    operators = Operator.query.order_by(Operator.full_name).all()
    form.operator_id.choices = [(0, 'All')] + [
        (op.id, getattr(op, 'full_name', getattr(op, 'username', f"User {op.id}"))) for op in operators
    ]

    analytics = []
    if form.validate_on_submit():
        analytics = get_boxing_analytics(
            operator_id=form.operator_id.data if form.operator_id.data != 0 else None,
            date_from=form.date_from.data,
            date_to=form.date_to.data,
            period=form.period.data
        )
    else:
        analytics = get_boxing_analytics()

    return render_template(
        "analytics/boxing/dashboard.html",
        analytics=analytics,
        form=form,
        now=datetime.now()  # <-- ADD THIS LINE!
    )
