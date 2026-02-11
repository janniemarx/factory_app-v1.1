from flask import Blueprint, render_template
from flask_login import login_required
from blueprints.analytics.eps_factory_analytics_helpers import (
    get_unutilized_pre_expansions,
    get_block_stats,
    get_pre_expansion_usage,
    get_inactive_sessions,
    get_dashboard_stats,
    get_blocks_not_cut,
    get_top_batches_by_block_count
)

analytics_bp = Blueprint('analytics', __name__, template_folder='../../templates/analytics')

@analytics_bp.route('/dashboard')
@login_required
def analytics_dashboard():
    unused_batches = get_unutilized_pre_expansions()
    stats_today = get_block_stats('today')
    stats_week = get_block_stats('this_week')
    stats_month = get_block_stats('this_month')
    pre_exp_usage = get_pre_expansion_usage()
    inactive_sessions = get_inactive_sessions()
    quick_stats = get_dashboard_stats()
    blocks_not_cut = get_blocks_not_cut()
    top_batches = get_top_batches_by_block_count()
    return render_template(
        'analytics/dashboard.html',
        unused_batches=unused_batches,
        stats_today=stats_today,
        stats_week=stats_week,
        stats_month=stats_month,
        pre_exp_usage=pre_exp_usage,
        inactive_sessions=inactive_sessions,
        quick_stats=quick_stats,
        blocks_not_cut=blocks_not_cut,
        top_batches=top_batches,
    )
