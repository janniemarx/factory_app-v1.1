from flask import Blueprint, render_template, flash, request, jsonify

from utils.authz import manager_required
from .forms import EPSAnalyticsFilterForm
from .helpers import (
    get_batch_numbers,
    filter_pre_expansions,
    calculate_analytics
)

eps_factory_analytics_bp = Blueprint(
    'eps_factory_analytics', __name__,
    template_folder='../../templates/analytics/eps_factory'
)

@eps_factory_analytics_bp.route('/', methods=['GET', 'POST'])
@manager_required
def analytics_dashboard():
    form = EPSAnalyticsFilterForm()
    form.batch_no.choices = [('', 'All')] + get_batch_numbers()
    analytics_data = []

    if form.validate_on_submit():
        pre_expansions = filter_pre_expansions(
            batch_no=form.batch_no.data or None,
            usage_type=form.usage_type.data or None,
            date_from=form.date_from.data,
            date_to=form.date_to.data
        )
        if not pre_expansions:
            flash('No records found for the given filters.', 'warning')
        else:
            analytics_data = calculate_analytics(pre_expansions)

    return render_template(
        'analytics/eps_factory/dashboard.html',
        form=form,
        analytics_data=analytics_data
    )

# --- "View More" modal AJAX endpoint (returns HTML fragment or JSON) ---
@eps_factory_analytics_bp.route('/details/<string:kind>/<int:item_id>')
@manager_required
def analytics_details(kind, item_id):
    """
    View more details for a batch/session (for modal or dedicated page).
    :param kind: 'block' or 'moulded' or 'preexp'
    :param item_id: the session_id or pre_expansion_id
    """
    from .helpers import get_detailed_analytics

    details = get_detailed_analytics(kind, item_id)
    if not details:
        return jsonify({'error': 'Not found'}), 404

    # Return as HTML partial for modal (recommended)
    return render_template('analytics/eps_factory/details_modal_content.html', details=details)
