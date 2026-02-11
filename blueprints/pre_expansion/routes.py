# blueprints/pre_expansion/routes.py

from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from .forms import PreExpansionForm, DensityCheckForm, PreExpansionChecklistForm, MarkPastelForm
from datetime import date
from models.pre_expansion import PreExpansion, db
from blueprints.pre_expansion.db_helpers import (
    generate_batch_no, create_pre_expansion, link_checklist_to_session,
    add_density_check, get_active_sessions, get_completed_sessions, add_finish_session,
    add_checklist, get_dashboard_counts, _is_pastel_captureable, add_checklist_from_values,
)

pre_expansion_bp = Blueprint('pre_expansion', __name__, template_folder='../../templates/pre_expansion')


@pre_expansion_bp.route('/start_session', methods=['GET', 'POST'])
@login_required
def start_pre_expansion_session():
    """
    Optional Option 4:
      If the page (or modal) posts precheck_mode="skip", we start the session
      WITHOUT saving a pre-start checklist or audit event.
      Otherwise we behave as before, saving the checklist values if provided.
    """
    checklist_id = request.args.get('checklist_id', type=int)
    form = PreExpansionForm()

    if form.validate_on_submit():
        # Server-side validation: density 18 can only be used for Block purpose
        if form.density.data == 18 and form.purpose.data == 'Moulded':
            flash("For 18 g/l density, only 'Block' purpose is allowed.", 'warning')
            return render_template('pre_expansion/start_pre_expansion.html', form=form)

        batch_no = generate_batch_no(date.today(), form.density.data, form.purpose.data)
        pre_exp, error = create_pre_expansion(form, current_user.id, batch_no)
        if error:
            flash(f"Database error: {error}", "danger")
            return render_template('pre_expansion/start_pre_expansion.html', form=form)

        # ---- Optional Option 4 gate ----
        precheck_mode = (request.form.get('precheck_mode') or '').strip().lower()
        # modes could be: '', 'with_checks' (default), or 'skip' (option 4)

        if precheck_mode == 'skip':
            # Do NOT create checklist or audit “pre” event
            flash('Pre-Expansion session started without a pre-start checklist (Option 4).', 'info')
        else:
            # Save pre-checklist values if they were posted by your modal
            checks = {f'check{i}': (request.form.get(f'check{i}') == 'y') for i in range(1, 11)}
            # default after-operation checks to False at start
            for i in range(11, 14):
                checks[f'check{i}'] = False

            # Save checklist tied to this session + audit "pre"
            _, evt_err = add_checklist_from_values(checks, current_user, pre_exp, ip_address=request.remote_addr)
            if evt_err:
                # not fatal for starting the session, but surface it
                flash(f"Saved session but failed to log checklist audit: {evt_err}", "warning")

        # Link an existing checklist if the flow created one before the session existed
        if checklist_id:
            linked, link_error = link_checklist_to_session(checklist_id, pre_exp.id)
            if not linked:
                flash(link_error, "warning")

        flash('Pre-Expansion session started! Now begin density checks.', 'success')
        return redirect(url_for('pre_expansion.active_session', session_id=pre_exp.id))

    return render_template('pre_expansion/start_pre_expansion.html', form=form)


@pre_expansion_bp.route('/active_session/<int:session_id>', methods=['GET', 'POST'])
@login_required
def active_session(session_id):
    pre_exp = PreExpansion.query.get_or_404(session_id)
    form = DensityCheckForm()
    if form.validate_on_submit():
        check, error = add_density_check(pre_exp.id, form, current_user.id)
        if error:
            flash(f"Could not record density check: {error}", "danger")
        else:
            flash('Density check recorded!', 'success')
        return redirect(url_for('pre_expansion.active_session', session_id=pre_exp.id))
    return render_template('pre_expansion/active_session.html', pre_exp=pre_exp, form=form)


@pre_expansion_bp.route('/finish_session/<int:session_id>', methods=['GET', 'POST'])
@login_required
def finish_session(session_id):
    pre_exp = PreExpansion.query.get_or_404(session_id)
    if pre_exp.operator_id != current_user.id:
        flash('You are not allowed to finish this session.', 'danger')
        return redirect(url_for('pre_expansion.dashboard'))

    if request.method == 'POST':
        success, error = add_finish_session(pre_exp, request.form, operator=current_user, ip_address=request.remote_addr)
        if not success:
            flash(f"Could not finish session: {error}", "danger")
            return render_template('pre_expansion/finish_session.html', pre_exp=pre_exp)
        flash('Pre-Expansion session finished!', 'success')
        return redirect(url_for('pre_expansion.view_pre_expansions'))

    return render_template('pre_expansion/finish_session.html', pre_exp=pre_exp)


@pre_expansion_bp.route('/active_sessions')
@login_required
def view_active_sessions():
    sessions, error = get_active_sessions()
    if error:
        flash(f"Could not load active sessions: {error}", "danger")
        sessions = []
    return render_template('pre_expansion/view_active_sessions.html', sessions=sessions)


@pre_expansion_bp.route('/view')
@login_required
def view_pre_expansions():
    sessions, error = get_completed_sessions()
    if error:
        flash(f"Could not load completed sessions: {error}", "danger")
        sessions = []
    return render_template('pre_expansion/view_pre_expansions.html', pre_expansions=sessions)


@pre_expansion_bp.route('/detail/<int:pre_expansion_id>', methods=['GET', 'POST'])
@login_required
def view_pre_expansion_detail(pre_expansion_id):
    pre_exp = PreExpansion.query.get_or_404(pre_expansion_id)
    form = DensityCheckForm()
    if form.validate_on_submit():
        check, error = add_density_check(pre_exp.id, form, current_user.id)
        if error:
            flash(f"Could not add density check: {error}", "danger")
        else:
            flash('Density check added!', 'success')
        return redirect(url_for('pre_expansion.view_pre_expansion_detail', pre_expansion_id=pre_exp.id))
    return render_template('pre_expansion/view_pre_expansion_detail.html', pre_exp=pre_exp, form=form)


@pre_expansion_bp.route('/pre_start_checklist', methods=['GET', 'POST'])
@login_required
def pre_start_checklist():
    """
    Standalone checklist page remains the same.
    (Option 4 is handled in /start_session via precheck_mode="skip".)
    """
    form = PreExpansionChecklistForm()
    if form.validate_on_submit():
        checklist, error = add_checklist(form, current_user, ip_address=request.remote_addr)
        if error:
            flash(f"Could not save checklist: {error}", "danger")
            return render_template('pre_expansion/pre_start_checklist.html', form=form)
        return redirect(url_for('pre_expansion.start_pre_expansion_session', checklist_id=checklist.id))
    return render_template('pre_expansion/pre_start_checklist.html', form=form)


@pre_expansion_bp.route('/dashboard')
@login_required
def dashboard():
    counts, error = get_dashboard_counts()
    if error:
        flash(f"Could not load dashboard stats: {error}", "danger")
    return render_template(
        'pre_expansion/dashboard.html',
        active_count=counts['active_count'],
        completed_today=counts['completed_today'],
        overdue_count=counts['overdue_count'],
        total_completed=counts['total_completed']
    )


@pre_expansion_bp.route('/pastel_pending')
@login_required
def pastel_pending():
    candidates = (PreExpansion.query
                  .filter_by(status='completed', is_pastel_captured=False)
                  .order_by(PreExpansion.end_time.desc())
                  .all())
    sessions = [s for s in candidates if _is_pastel_captureable(s)]
    return render_template('pre_expansion/pastel_pending.html', sessions=sessions)

@pre_expansion_bp.route('/pastel_capture/<int:pre_exp_id>', methods=['GET', 'POST'])
@login_required
def pastel_capture(pre_exp_id):
    from sqlalchemy import func
    from models.block import Block, BlockMaterialConsumption
    from models.moulded_cornice import MouldedCorniceSession
    from models.production import CuttingProductionRecord

    pre_exp = PreExpansion.query.get_or_404(pre_exp_id)

    # Hard gate before doing any heavy work
    if not _is_pastel_captureable(pre_exp):
        flash(
            "This pre-expansion is not captureable yet. It must be completed and have output (blocks or moulded).",
            "warning"
        )
        return redirect(url_for('pre_expansion.pastel_pending'))

    form = MarkPastelForm()

    # Common/summary fields
    operator_entered_used_kg = float(pre_exp.total_kg_used or 0.0)
    leftover_kg = float(pre_exp.leftover_kg or 0.0)
    leftover_disposition = (pre_exp.leftover_disposition or "").lower()

    # Defaults for template
    total_blocks = 0
    total_block_kg = 0.0
    kg_from_pr16_in_session = 0.0
    kg_from_this_batch_in_session = 0.0
    cut_profiles_by_block = []
    remaining_blocks_count = 0
    remaining_block_numbers = []
    cornice_profiles = {}
    total_cornice_kg = 0.0
    capture_qty_kg = 0.0

    if pre_exp.purpose == 'Block':
        # All blocks recorded against THIS batch (this pre-exp)
        blocks = Block.query.filter_by(pre_expansion_id=pre_exp.id).all()
        block_ids = [b.id for b in blocks]

        remaining = [b for b in blocks if not getattr(b, 'is_cut', False)]
        remaining_blocks_count = len(remaining)
        remaining_block_numbers = sorted([b.block_number for b in remaining if b.block_number])

        total_blocks = len(blocks)
        total_block_kg = round(sum((b.weight or 0.0) for b in blocks), 2)

        if block_ids:
            # KG that came from old PR16/other batches (not this batch)
            kg_from_pr16_in_session = (
                db.session.query(func.coalesce(func.sum(BlockMaterialConsumption.kg_from_source), 0.0))
                .filter(BlockMaterialConsumption.block_id.in_(block_ids))  # <-- correct in_
                .filter(BlockMaterialConsumption.source_pre_expansion_id != pre_exp.id)
                .scalar()
            ) or 0.0

            # KG actually drawn from THIS batch into these blocks
            kg_from_this_batch_in_session = (
                db.session.query(func.coalesce(func.sum(BlockMaterialConsumption.kg_from_source), 0.0))
                .filter(BlockMaterialConsumption.block_id.in_(block_ids))  # <-- correct in_
                .filter(BlockMaterialConsumption.source_pre_expansion_id == pre_exp.id)
                .scalar()
            ) or 0.0
        else:
            kg_from_pr16_in_session = 0.0
            kg_from_this_batch_in_session = 0.0

        kg_from_pr16_in_session = round(float(kg_from_pr16_in_session), 2)
        kg_from_this_batch_in_session = round(float(kg_from_this_batch_in_session), 2)

        # Profiles cut from blocks produced in this pre-expansion batch
        if block_ids:
            rows = (
                db.session.query(
                    CuttingProductionRecord.block_number,
                    CuttingProductionRecord.profile_code,
                    func.coalesce(func.sum(CuttingProductionRecord.cornices_produced), 0).label('profiles_cut'),
                    func.coalesce(func.sum(CuttingProductionRecord.total_cornices_damaged), 0).label('damaged'),
                )
                .filter(CuttingProductionRecord.block_id.in_(block_ids))
                .group_by(CuttingProductionRecord.block_number, CuttingProductionRecord.profile_code)
                .order_by(CuttingProductionRecord.block_number.asc(), CuttingProductionRecord.profile_code.asc())
                .all()
            )
            cut_profiles_by_block = [
                {
                    'block_number': r.block_number,
                    'profile_code': r.profile_code,
                    'profiles_cut': int(r.profiles_cut or 0),
                    'damaged': int(r.damaged or 0),
                }
                for r in rows
            ]

        # ✅ Capture WHAT WAS PRODUCED this session (all blocks’ weight),
        # even if some KG came from PR16 stash.
        capture_qty_kg = total_block_kg

    elif pre_exp.purpose == 'Moulded':
        # Sum the produced kg across moulded sessions tied to this batch
        sessions = MouldedCorniceSession.query.filter_by(pre_expansion_id=pre_exp.id).all()
        for s in sessions:
            # lines → profile counts
            for line in getattr(s, 'lines', []):
                profile = line.profile_code
                qty = s.cycles or 0
                cornice_profiles[profile] = cornice_profiles.get(profile, 0) + qty

            if s.actual_produced_kg:
                total_cornice_kg += float(s.actual_produced_kg)

        total_cornice_kg = round(total_cornice_kg, 2)

        # ✅ For moulded we capture what was actually produced
        capture_qty_kg = total_cornice_kg

    # POST: mark captured (re-check gate to be safe)
    if form.validate_on_submit():
        if not _is_pastel_captureable(pre_exp):
            flash("Cannot capture: session no longer eligible.", "danger")
            return redirect(url_for('pre_expansion.pastel_pending'))
        pre_exp.is_pastel_captured = True
        db.session.commit()
        flash("Session marked as captured in Pastel.", "success")
        return redirect(url_for('pre_expansion.pastel_pending'))

    material_used_kg = float(pre_exp.total_kg_used or pre_exp.planned_kg or 0.0)

    return render_template(
        'pre_expansion/pastel_capture_detail.html',
        pre_exp=pre_exp,
        form=form,

        # Blocks side
        total_blocks=total_blocks,
        total_block_kg=total_block_kg,
        kg_from_pr16_in_session=kg_from_pr16_in_session,
        kg_from_this_batch_in_session=kg_from_this_batch_in_session,
        cut_profiles_by_block=cut_profiles_by_block,
        remaining_blocks_count=remaining_blocks_count,
        remaining_block_numbers=remaining_block_numbers,

        # Moulded side
        cornice_profiles=cornice_profiles,
        total_cornice_kg=total_cornice_kg,
        material_used_kg=material_used_kg,

        # Shared
        capture_qty_kg=round(float(capture_qty_kg), 2),
        operator_entered_used_kg=operator_entered_used_kg,
        leftover_kg=leftover_kg,
        leftover_disposition=leftover_disposition
    )
