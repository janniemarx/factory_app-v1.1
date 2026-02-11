# blueprints/blocks/routes.py

from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from sqlalchemy import func

from .forms import StartBlockSessionForm, AddBlockForm, FinishBlockSessionForm, BlockSessionFilterForm, EditBlockForm
from models import db
from models.block import BlockSession, Block, BlockMaterialConsumption
from models.pre_expansion import PreExpansion

from .db_helpers import (
    get_available_pre_expansions,
    create_block_session,
    get_active_block_sessions,
    get_session_blocks,
    add_block_to_session,
    finish_block_session_with_leftover,
    get_completed_blocks_and_sessions,
    pr16_total_remaining,
)

blocks_bp = Blueprint('blocks', __name__, template_folder='../../templates/blocks')


@blocks_bp.route('/active_sessions')
@login_required
def active_sessions():
    sessions, error = get_active_block_sessions()
    if error:
        flash(f"Could not load active sessions: {error}", "danger")
        sessions = []
    return render_template('blocks/view_active_blocks.html', sessions=sessions)


@blocks_bp.route('/start_session', methods=['GET', 'POST'])
@login_required
def start_block_session():
    form = StartBlockSessionForm()
    available_pre_expansions, error = get_available_pre_expansions()
    if error:
        flash(f"Could not load pre-expansions: {error}", "danger")
        form.pre_expansion_id.choices = []
    else:
        form.pre_expansion_id.choices = [
            (pe.id, f"{pe.batch_no} ({pe.density} g/l, {pe.planned_kg} kg)")
            for pe in available_pre_expansions
        ]

    # Warn if PR16 stash exists for the selected density/material
    if form.validate_on_submit():
        selected_pre_exp = PreExpansion.query.get(form.pre_expansion_id.data)
        if not selected_pre_exp or selected_pre_exp.is_used or selected_pre_exp.status != 'completed':
            flash("Invalid or already used pre-expansion batch.", "danger")
            return redirect(url_for('blocks.start_block_session'))

        stash_kg = pr16_total_remaining(selected_pre_exp.density, selected_pre_exp.material_code)
        if stash_kg > 0:
            flash(
                f"Note: There is {stash_kg:.2f} kg PR16 material available in the silo. "
                f"If you make a PR16 block, it will draw from the stash automatically.",
                "warning"
            )

        session, error = create_block_session(form.pre_expansion_id.data, current_user.id)
        if error or not session:
            flash(f"Could not start block session: {error}", "danger")
            return render_template('blocks/add_block.html', form=form)

        flash('Block production session started.', 'success')
        return redirect(url_for('blocks.session_detail', session_id=session.id))

    return render_template('blocks/add_block.html', form=form)


@blocks_bp.route('/session/<int:session_id>', methods=['GET', 'POST'])
@login_required
def session_detail(session_id):
    session = BlockSession.query.get_or_404(session_id)
    pre_exp = session.pre_expansion
    form = AddBlockForm()
    finish_form = FinishBlockSessionForm()

    # list blocks
    blocks, error = get_session_blocks(session_id)
    if error:
        flash(f"Could not load blocks: {error}", "danger")
        blocks = []

    # PR16 stash for this density/material
    pr16_stash_kg = pr16_total_remaining(pre_exp.density, pre_exp.material_code)

    # Has this session already produced at least one PR16 block?
    has_pr16_block = (
        db.session.query(func.count(Block.id))
        .filter(Block.block_session_id == session.id, Block.is_profile16.is_(True))
        .scalar() or 0
    ) > 0

    # If there is stash available and we haven't made a PR16 block yet,
    # force the next block to be PR16.
    force_pr16_first = (pr16_stash_kg > 0) and (not has_pr16_block)

    # ---- compute leftover estimate (kg drawn FROM THIS BATCH only) ----
    # Prefer the greater of operator-entered actual output (total_kg_used) and planned_kg
    # to avoid under-reporting leftover when 'used' is mis-entered.
    entered_used = float(pre_exp.total_kg_used or 0.0)
    planned = float(pre_exp.planned_kg or 0.0)
    batch_available = max(entered_used, planned)
    consumed_from_this_batch = (
        db.session.query(func.coalesce(func.sum(BlockMaterialConsumption.kg_from_source), 0.0))
        .filter(BlockMaterialConsumption.source_pre_expansion_id == pre_exp.id)
        .scalar()
    ) or 0.0
    leftover_estimate = max(round(batch_available - float(consumed_from_this_batch), 3), 0.0)

    # ------- Add a new block -------
    if form.validate_on_submit() and 'add_block' in request.form and session.status == 'active':
        # Server-side enforcement: first block must be PR16 when stash exists
        if force_pr16_first:
            form.is_profile16.data = True  # cannot be unchecked until first PR16 is made
            flash("First block auto-set to PR16 to use leftover stash.", "info")

        block, error, block_number = add_block_to_session(session, pre_exp, form, current_user.id)
        if error or not block:
            flash(f"Error adding block: {error}", "danger")
        else:
            flash(f"Block {block_number} added.", "success")
        return redirect(url_for('blocks.session_detail', session_id=session.id))

    # ------- Finish session (leftover modal guard) -------
    show_leftover_modal = False
    leftover_kg = 0.0
    is_finish_attempt = ('finish_session' in request.form) or ('leftover_action' in request.form)

    if finish_form.validate_on_submit() and is_finish_attempt and session.status == 'active':
        assignment = request.form.get('leftover_action')  # "moulded" | "pr16" | None
        ok, err, leftover_kg, _created_target = finish_block_session_with_leftover(
            session=session,
            assignment=assignment,
            operator_id=current_user.id
        )
        if not ok and err == "LEFTOVER_NEEDS_ASSIGNMENT":
            show_leftover_modal = True
            flash(f"{leftover_kg:.2f} kg material left. Choose an assignment to finish.", "warning")
        elif not ok:
            flash(f"Error finishing session: {err}", "danger")
            return redirect(url_for('blocks.session_detail', session_id=session.id))
        else:
            if leftover_kg > 0 and assignment == 'moulded':
                flash(f"Block session finished. {leftover_kg:.2f} kg moved to a new Moulded batch.", "success")
            elif leftover_kg > 0 and assignment == 'pr16':
                flash(f"Block session finished. {leftover_kg:.2f} kg moved to PR16 stash.", "success")
            else:
                flash("Block session finished. No leftover material.", "success")
            return redirect(url_for('blocks.active_sessions'))

    return render_template(
        'blocks/session_detail.html',
        session=session,
        pre_exp=pre_exp,
        blocks=blocks,
        form=form,
        finish_form=finish_form,
        leftover_estimate=leftover_estimate,
        show_leftover_modal=show_leftover_modal,
        leftover_kg=leftover_kg or leftover_estimate,
        pr16_stash_kg=pr16_stash_kg,
        force_pr16_first=force_pr16_first,   # <-- pass to template
    )


@blocks_bp.route('/block/<int:block_id>/edit', methods=['POST'])
@login_required
def edit_block(block_id):
    """Inline edit for an existing Block. Keeps number, operator, curing_end, created_at read-only."""
    block = Block.query.get_or_404(block_id)
    session = block.block_session

    if not session:
        flash('Invalid block session.', 'danger')
        return redirect(url_for('blocks.active_sessions'))

    if session.status != 'active':
        flash('Cannot edit blocks for a completed session.', 'warning')
        return redirect(url_for('blocks.session_detail', session_id=session.id))

    form = EditBlockForm()
    if form.validate_on_submit():
        try:
            block.weight = form.weight.data
            block.heating1_time = form.heating1_time.data
            block.heating2_time = form.heating2_time.data
            block.heating3_time = form.heating3_time.data
            block.cooling_time = form.cooling_time.data
            block.is_profile16 = bool(form.is_profile16.data)
            db.session.commit()
            flash(f'Block {block.block_number} updated.', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating block: {e}', 'danger')
    else:
        # WTForms validation failed; show a generic message
        flash('Please correct the highlighted fields and try again.', 'danger')

    return redirect(url_for('blocks.session_detail', session_id=session.id))



@blocks_bp.route('/block/<int:block_id>')
@login_required
def block_detail(block_id):
    from models.production import CuttingProductionRecord

    block = Block.query.get_or_404(block_id)
    pre_exp = block.pre_expansion
    session = block.block_session

    prod_recs = CuttingProductionRecord.query.filter_by(block_id=block.id).all()
    stats = {}
    for rec in prod_recs:
        qc = rec.quality_control
        pcode = rec.profile_code
        s = stats.setdefault(pcode, {
            "profile_code": pcode,
            "cornices_produced": 0,
            "damaged": 0,
            "rated_areo_effect": [],
            "rated_eps_binding": [],
            "rated_wetspots": [],
            "rated_dryness": [],
            "rated_lines": [],
            "time_min": [],
        })
        s["cornices_produced"] += rec.cornices_produced
        s["damaged"] += getattr(rec, "total_cornices_damaged", 0) or 0
        if qc:
            for field in ["rated_areo_effect", "rated_eps_binding", "rated_wetspots", "rated_dryness", "rated_lines"]:
                s[field].append(getattr(qc, field, None))
            if rec.date_boxed and session and session.started_at:
                time_min = int((rec.date_boxed - session.started_at).total_seconds() / 60)
                s["time_min"].append(time_min)

    profile_stats = []
    for s in stats.values():
        profile_stats.append({
            "profile_code": s["profile_code"],
            "cornices_produced": s["cornices_produced"],
            "damaged": s["damaged"],
            "rated_areo_effect": round(sum(filter(None, s["rated_areo_effect"])) / len(list(filter(None, s["rated_areo_effect"]))) if s["rated_areo_effect"] else 0, 2),
            "rated_eps_binding": round(sum(filter(None, s["rated_eps_binding"])) / len(list(filter(None, s["rated_eps_binding"]))) if s["rated_eps_binding"] else 0, 2),
            "rated_wetspots": round(sum(filter(None, s["rated_wetspots"])) / len(list(filter(None, s["rated_wetspots"]))) if s["rated_wetspots"] else 0, 2),
            "rated_dryness": round(sum(filter(None, s["rated_dryness"])) / len(list(filter(None, s["rated_dryness"]))) if s["rated_dryness"] else 0, 2),
            "rated_lines": round(sum(filter(None, s["rated_lines"])) / len(list(filter(None, s["rated_lines"]))) if s["rated_lines"] else 0, 2),
            "time_min": min(s["time_min"]) if s["time_min"] else None,
        })

    return render_template(
        "blocks/block_detail.html",
        block=block, pre_exp=pre_exp, session=session,
        profile_stats=profile_stats
    )


@blocks_bp.route('/completed_sessions', methods=['GET', 'POST'])
@login_required
def completed_sessions():
    form = BlockSessionFilterForm(request.form)
    block_session_pairs, form, analytics, search_performed, error = get_completed_blocks_and_sessions(form)
    if error:
        flash(f"Could not load completed sessions: {error}", "danger")
    return render_template(
        'blocks/view_blocks.html',
        block_session_pairs=block_session_pairs,
        form=form,
        analytics=analytics,
        search_performed=search_performed
    )
