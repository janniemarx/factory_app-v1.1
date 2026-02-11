# blueprints/pr16/routes.py
from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from datetime import datetime
from .forms import (
    StartPR16SessionForm, AddResourceUsageForm, WrapProductionForm,
    FinishWrappingForm, CompleteDryingForm, TrimmingLogForm,
)
from blueprints.qc.forms import PR16QualityControlForm
from .db_helpers import (
    get_pr16_blocks_ready, start_pr16_session, add_resource_usage, log_wrapping,
    pause_wrapping, resume_wrapping, complete_wrapping, complete_drying,
    log_trimming, cancel_session, mark_qc, recompute_session_metrics, pause_trimming, resume_trimming
)
from models.pr16_session import PR16Session, PR16ResourceUsage, PR16WrappingProduction, PR16TrimmingLog
from models.production import CuttingProductionRecord

PAPER_ROLL_M = 300.0
pr16_bp = Blueprint('pr16', __name__, template_folder='templates/pr16')


# --- 1) Start PR16 Session ---
@pr16_bp.route('/start', methods=['GET', 'POST'])
@login_required
def start_session():
    form = StartPR16SessionForm()
    pr16_cut_blocks = get_pr16_blocks_ready()
    form.block_id.choices = [(b.id, b.block_number) for b in pr16_cut_blocks] or []
    no_blocks = len(form.block_id.choices) == 0

    if form.validate_on_submit() and not no_blocks:
        try:
            start_partial_fraction = float(form.start_partial_roll.data or '0')
        except Exception:
            start_partial_fraction = 0.0

        session, error = start_pr16_session(
            block_id=form.block_id.data,
            operator_id=current_user.id,
            glue_kg=form.initial_glue_kg.data,
            paper_m=form.initial_paper_m.data or 0.0,
            start_partial_fraction=start_partial_fraction
        )
        if error:
            flash(error, 'danger')
            return redirect(url_for('pr16.start_session'))

        flash('PR16 Wrapping session started!', 'success')
        return redirect(url_for('pr16.session_detail', session_id=session.id))

    elif request.method == "POST" and no_blocks:
        flash('No PR16 blocks available for wrapping. Please cut a PR16 first.', 'danger')

    return render_template('pr16/start_session.html', form=form, no_blocks=no_blocks)


# --- 2) View / Edit PR16 Session ---
@pr16_bp.route('/session/<int:session_id>', methods=['GET', 'POST'])
@login_required
def session_detail(session_id):
    session = PR16Session.query.get_or_404(session_id)

    # Friendly block label for the header
    block_no = (
        session.block.block_number
        if getattr(session, "block", None) and getattr(session.block, "block_number", None)
        else session.block_id
    )

    # Forms
    add_resource_form = AddResourceUsageForm()
    wrap_form = WrapProductionForm()
    finish_wrap_form = FinishWrappingForm()
    drying_form = CompleteDryingForm()
    trim_form = TrimmingLogForm()
    qc_form = PR16QualityControlForm()

    show_finish_wrapping_modal = request.args.get("finish_wrapping")
    show_trimmed_modal = request.args.get("show_trimmed_modal")

    # Quantities for gating / display
    cut_rec = CuttingProductionRecord.query.filter_by(
        block_id=session.block_id, profile_code='PR16'
    ).order_by(CuttingProductionRecord.id.desc()).first()
    cut_qty = int(cut_rec.cornices_produced if cut_rec and cut_rec.cornices_produced else 0)
    wrapped_qty = int(session.wrapped_cornices or 0)
    remaining_to_wrap = max(cut_qty - wrapped_qty, 0)

    # ==============================
    # Global pause guards by stage
    # ==============================

    # Wrapping: only allow "resume" when paused
    if request.method == 'POST' and session.status == 'active' and session.is_paused:
        if 'resume' in request.form:
            ok, err = resume_wrapping(session)
            flash('Session resumed.' if ok else f'Resume error: {err}', 'success' if ok else 'danger')
        else:
            flash('Session is paused. Please resume before continuing.', 'warning')
        return redirect(url_for('pr16.session_detail', session_id=session.id))

    # Trimming: only allow "resume_trim" when paused
    if request.method == 'POST' and session.status == 'trimming' and getattr(session, 'is_trim_paused', False):
        if 'resume_trim' in request.form:
            ok, err = resume_trimming(session)
            flash('Trimming resumed.' if ok else f'Error: {err}', 'success' if ok else 'danger')
        else:
            flash('Trimming is paused. Please resume before continuing.', 'warning')
        return redirect(url_for('pr16.session_detail', session_id=session.id))

    # ==============================
    # Pause / Resume triggers
    # ==============================

    # Wrapping -> pause
    if request.method == 'POST' and 'pause' in request.form and session.status == 'active' and not session.is_paused:
        ok, err = pause_wrapping(session)
        flash('Session paused.' if ok else f'Pause error: {err}', 'warning' if ok else 'danger')
        return redirect(url_for('pr16.session_detail', session_id=session.id))

    # Trimming -> pause
    if request.method == 'POST' and 'pause_trim' in request.form and session.status == 'trimming' and not getattr(session, 'is_trim_paused', False):
        ok, err = pause_trimming(session)
        flash('Trimming paused.' if ok else f'Pause error: {err}', 'warning' if ok else 'danger')
        return redirect(url_for('pr16.session_detail', session_id=session.id))

    # ==============================
    # Stage actions
    # ==============================

    # Add glue/paper (wrapping only, not paused)
    if (add_resource_form.validate_on_submit()
        and 'add_resource_usage' in request.form
        and session.status == 'active' and not session.is_paused):
        success, error = add_resource_usage(
            session.id,
            glue_kg=add_resource_form.glue_kg.data or 0.0,
            paper_m=add_resource_form.paper_m.data or 0.0
        )
        flash('Added resource usage.' if success else f'Error: {error}', "info" if success else "danger")
        return redirect(url_for('pr16.session_detail', session_id=session.id))

    # Log wrapped (wrapping only, not paused)
    if (wrap_form.validate_on_submit()
        and 'save_wrapped' in request.form
        and session.status == 'active' and not session.is_paused):
        success, error = log_wrapping(session.id, wrap_form.cornices_wrapped.data)
        flash('Wrapping production logged.' if success else f'Error: {error}', 'info' if success else 'danger')
        return redirect(url_for('pr16.session_detail', session_id=session.id))

    # Complete wrapping -> Drying (wrapping only, not paused)
    if (finish_wrap_form.validate_on_submit()
        and 'complete_wrapping' in request.form
        and session.status == 'active' and not session.is_paused):
        try:
            end_fraction = float(finish_wrap_form.end_partial_roll.data or '0')
        except Exception:
            end_fraction = 0.0
        success, error = complete_wrapping(session, end_fraction)
        if not success:
            flash(error, "danger")
            return redirect(url_for('pr16.session_detail', session_id=session.id, finish_wrapping=1))
        flash("Wrapping complete. Drying started.", "success")
        return redirect(url_for('pr16.session_detail', session_id=session.id))

    # Complete Drying -> Trimming
    if (drying_form.validate_on_submit()
        and 'complete_drying' in request.form
        and session.status == 'in_drying'):
        success, error = complete_drying(session)
        flash(("Drying complete. Trimming started." if success else error), "success" if success else "danger")
        return redirect(url_for('pr16.session_detail', session_id=session.id, show_trimmed_modal=1 if success else None))

    # Save trimmed -> Awaiting QC (trimming only, not paused)
    if (trim_form.validate_on_submit()
        and 'save_trimmed' in request.form
        and session.status == 'trimming'
        and not getattr(session, 'is_trim_paused', False)):
        success, error = log_trimming(
            session_id=session.id,
            trimming_start=session.trimming_start,
            trimming_end=datetime.utcnow(),
            cornices_trimmed=trim_form.cornices_trimmed.data
        )
        flash('PR16 session trimmed. Awaiting QC.' if success else f'Error: {error}', 'warning' if success else 'danger')
        return redirect(url_for('pr16.session_detail', session_id=session.id))

    # QC pass/fail
    if (qc_form.validate_on_submit()
        and 'mark_qc' in request.form
        and session.status == 'awaiting_qc'):
        success, error = mark_qc(session.id, current_user.id, qc_form.passed.data, qc_form.notes.data)
        if not success:
            flash(error, 'danger')
        else:
            flash('QC passed. READY FOR BOXING.' if qc_form.passed.data else 'QC failed.', 'success' if qc_form.passed.data else 'danger')
        return redirect(url_for('pr16.session_detail', session_id=session.id))

    # Keep analytics fresh for the view
    recompute_session_metrics(session)

    # Logs for display
    resource_usages = PR16ResourceUsage.query.filter_by(session_id=session.id)\
        .order_by(PR16ResourceUsage.timestamp.asc()).all()
    wrapped = PR16WrappingProduction.query.filter_by(session_id=session.id)\
        .order_by(PR16WrappingProduction.logged_at.asc()).all()
    trimmed = PR16TrimmingLog.query.filter_by(session_id=session.id)\
        .order_by(PR16TrimmingLog.timestamp.asc()).all()

    return render_template(
        'pr16/session_detail.html',
        session=session,
        block_no=block_no,
        cut_qty=cut_qty,
        wrapped_qty=wrapped_qty,
        remaining_to_wrap=remaining_to_wrap,
        resource_usages=resource_usages,
        wrapped=wrapped,
        trimmed=trimmed,
        add_resource_form=add_resource_form,
        wrap_form=wrap_form,
        finish_wrap_form=finish_wrap_form,
        drying_form=drying_form,
        trim_form=trim_form,
        qc_form=qc_form,
        show_finish_wrapping_modal=show_finish_wrapping_modal,
        show_trimmed_modal=show_trimmed_modal
    )


# --- 3) List all PR16 sessions ---
@pr16_bp.route('/sessions')
@login_required
def sessions():
    sessions = PR16Session.query.order_by(PR16Session.started_at.desc()).all()
    return render_template('pr16/sessions.html', sessions=sessions)


# --- 4) Cancel/Delete Session ---
@pr16_bp.route('/session/<int:session_id>/cancel', methods=['POST'])
@login_required
def cancel_session_view(session_id):
    session = PR16Session.query.get_or_404(session_id)
    if session.status not in ('qc_passed', 'qc_failed'):
        success, error = cancel_session(session)
        flash('Session cancelled.' if success else error, 'warning' if success else 'danger')
    else:
        flash('Cannot cancel a QC-determined session.', 'danger')
    return redirect(url_for('pr16.sessions'))
