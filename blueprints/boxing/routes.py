# blueprints/boxing/routes.py

from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from .forms import (
    BoxingSessionStartForm,
    BoxingSessionFinishForm,
    BoxingPauseForm,
    BoxingQualityControlForm,
    UseLeftoversForm,
)
from .db_helpers import (
    get_ready_for_boxing, create_boxing_session, get_boxing_session,
    pause_boxing_session, resume_boxing_session, finish_boxing_session,
    save_boxing_qc, get_all_boxing_sessions, get_sessions_ready_for_stock,
    get_unused_leftovers, mark_leftovers_as_used, qty_ready_to_box, get_ready_for_boxing_sources
)

from models.production import CuttingProductionRecord
from models.cutting import Profile

from datetime import datetime

boxing_bp = Blueprint('boxing', __name__, template_folder='../../templates/boxing')

# -------------------- 1. Start Boxing Session --------------------
@boxing_bp.route('/start', methods=['GET', 'POST'])
@login_required
def start_boxing_session():
    items, error = get_ready_for_boxing_sources()
    if error:
        flash(f"Error loading records: {error}", "danger")
        items = []

    form = BoxingSessionStartForm()
    form.source.choices = [(i["key"], i["label"]) for i in items]

    if form.validate_on_submit():
        choice = form.source.data or ""
        try:
            kind, raw_id = choice.split(":", 1)
            if kind == "cut":
                session, err = create_boxing_session(
                    operator_id=current_user.id,
                    cutting_production_id=int(raw_id),
                )
            elif kind == "ext":
                session, err = create_boxing_session(
                    operator_id=current_user.id,
                    extrusion_session_id=int(raw_id),
                )
            else:
                raise ValueError("Unknown source kind")
        except Exception as ex:
            flash(f"Invalid selection: {ex}", "danger")
            return redirect(url_for('boxing.start_boxing_session'))

        if err or not session:
            flash(f"Could not start boxing session: {err}", "danger")
            return redirect(url_for('boxing.start_boxing_session'))

        flash("Boxing session started! Remember to ZERO the machine counter before boxing.", "success")
        return redirect(url_for('boxing.session_detail', session_id=session.id))

    return render_template('boxing/start_boxing_session.html', form=form)



# -------------------- 2. Boxing Session Detail / Actions --------------------
@boxing_bp.route('/session/<int:session_id>', methods=['GET', 'POST'])
@login_required
def session_detail(session_id):
    session = get_boxing_session(session_id)
    if not session:
        flash("Session not found.", "danger")
        return redirect(url_for('boxing.view_sessions'))

    finish_form = BoxingSessionFinishForm()
    pause_form = BoxingPauseForm()

    # Resolve pieces-per-box and “received” quantity
    if session.source_type == 'cutting':
        record = session.cutting_production
        from models.cutting import Profile
        profile = Profile.query.filter_by(code=record.profile_code).first() if record else None
        cornices_per_box = profile.cornices_per_box if profile else 4
        received_qty = qty_ready_to_box(record) if record else 0
        leftovers = get_unused_leftovers(record.profile_code) if record else []
    else:
        record = None
        extr = session.extrusion_session
        profile = None  # cutting Profile not used; cpb comes from extrusion profile
        cornices_per_box = extr.profile.pieces_per_box if extr and extr.profile else 4
        received_qty = int(extr.pieces_produced or 0) if extr else 0
        leftovers = get_unused_leftovers(extr.profile.code) if extr and extr.profile else []

    total_cornices = (session.boxes_packed or 0) * cornices_per_box + (session.leftovers or 0)
    producing_cycles = session.producing_cycles if session.producing_cycles is not None else None
    actual_producing_cycles = session.actual_producing_cycles if session.actual_producing_cycles is not None else None
    time_per_box_min = session.time_per_box_min if session.time_per_box_min is not None else None

    use_leftovers_form = UseLeftoversForm()
    if use_leftovers_form.validate_on_submit() and 'mark_leftovers' in request.form:
        leftover_ids = [l.id for l in leftovers]
        mark_leftovers_as_used(leftover_ids, used_in_session_id=session.id)
        flash("Leftovers marked as used. You can continue boxing.", "success")
        return redirect(url_for('boxing.session_detail', session_id=session.id))

    if request.method == 'POST' and 'mark_leftovers' not in request.form:

        if 'pause' in request.form:
            success, error = pause_boxing_session(session)
            flash(("Pause failed: " + error) if error else "Boxing session paused.", "danger" if error else "warning")
            return redirect(url_for('boxing.session_detail', session_id=session.id))

        if 'resume' in request.form:
            success, error = resume_boxing_session(session)
            flash(("Resume failed: " + error) if error else "Boxing session resumed.", "danger" if error else "success")
            return redirect(url_for('boxing.session_detail', session_id=session.id))

        if 'complete' in request.form:
            if finish_form.validate_on_submit():
                def boxing_fields_cb(rec, sess):
                    if rec and rec.profile_code == 'PR16':
                        from models.pr16_session import PR16Session
                        pr16 = (PR16Session.query
                                .filter_by(block_id=rec.block_id)
                                .order_by(PR16Session.id.desc())
                                .first())
                        if pr16:
                            pr16.boxed_cornices = int(sess.boxes_packed or 0)

                success, error = finish_boxing_session(session, finish_form, record, boxing_fields_cb)
                if not success:
                    flash(f"Could not complete session: {error}", "danger")
                    return redirect(url_for('boxing.session_detail', session_id=session.id))

                flash("Boxing session completed. Awaiting QC.", "success")
                return redirect(url_for('boxing.view_sessions'))
            else:
                flash("Please complete all required fields to finish the session.", "danger")
                return redirect(url_for('boxing.session_detail', session_id=session.id))

        return redirect(url_for('boxing.session_detail', session_id=session.id))

    if session.status == "active" and finish_form.cycle_end.data is None:
        finish_form.cycle_end.data = session.cycle_start or 0

    return render_template(
        'boxing/boxing_session_detail.html',
        session=session,
        record=record,
        finish_form=finish_form,
        pause_form=pause_form,
        profile=profile,  # may be None for extrusion; template should rely on session.cornices_per_box if needed
        total_cornices=total_cornices,
        producing_cycles=producing_cycles,
        actual_producing_cycles=actual_producing_cycles,
        time_per_box_min=time_per_box_min,
        leftovers=leftovers,
        use_leftovers_form=use_leftovers_form,
        received_qty=received_qty,
    )



# -------------------- 3. List All Boxing Sessions --------------------
@boxing_bp.route('/sessions', methods=['GET'])
@login_required
def view_sessions():
    sessions, error = get_all_boxing_sessions()
    if error:
        flash(f"Could not load sessions: {error}", "danger")
        sessions = []
    return render_template('boxing/view_boxing_sessions.html', sessions=sessions)

# -------------------- 4. Quality Control on Boxed Cornices --------------------
@boxing_bp.route('/qc/<int:session_id>', methods=['GET', 'POST'])
@login_required
def boxing_qc(session_id):
    session = get_boxing_session(session_id)
    if not session:
        flash("Session not found.", "danger")
        return redirect(url_for('boxing.view_sessions'))
    if session.status != 'pending_qc':
        flash("QC can only be performed on sessions pending QC.", "danger")
        return redirect(url_for('boxing.view_sessions'))

    qc_form = BoxingQualityControlForm()

    # unify totals for both sources
    cpb = session.cornices_per_box
    total_cornices = (session.boxes_packed or 0) * cpb + (session.leftovers or 0)
    damage = None

    if qc_form.validate_on_submit():
        qc, error = save_boxing_qc(session, qc_form, current_user.id)
        if error:
            flash(f"Could not complete QC: {error}", "danger")
            return render_template('boxing/boxing_qc.html', session=session, qc_form=qc_form,
                                   total_cornices=total_cornices, damage=damage)

        # for display only: recompute damage from QC perspective
        if session.source_type == 'cutting' and session.cutting_production and session.cutting_production.quality_control:
            good_from_source = session.cutting_production.quality_control.good_cornices_count
        elif session.source_type == 'extrusion' and session.extrusion_session:
            good_from_source = int(session.extrusion_session.pieces_produced or 0)
        else:
            good_from_source = total_cornices

        damage = max(good_from_source - total_cornices, 0)
        flash("QC complete! Stock is now ready.", "success")
        return redirect(url_for('boxing.view_sessions'))

    return render_template(
        'boxing/boxing_qc.html',
        session=session,
        qc_form=qc_form,
        total_cornices=total_cornices,
        damage=damage
    )

# -------------------- 5. List Sessions Ready for Stock Controller --------------------
@boxing_bp.route('/ready_for_stock', methods=['GET'])
@login_required
def ready_for_stock():
    sessions, error = get_sessions_ready_for_stock()
    if error:
        flash(f"Could not load ready sessions: {error}", "danger")
        sessions = []
    return render_template('boxing/ready_for_stock.html', sessions=sessions)

# (Optional) Legacy page-based flow, can be removed:
@boxing_bp.route('/use_leftovers/<profile_code>', methods=['GET', 'POST'])
@login_required
def use_leftovers(profile_code):
    leftovers = get_unused_leftovers(profile_code)
    if not leftovers:
        flash("No leftovers to use for this profile.", "info")
        return redirect(url_for('boxing.start_boxing_session'))

    form = UseLeftoversForm()

    if form.validate_on_submit():
        leftover_ids = [l.id for l in leftovers]
        mark_leftovers_as_used(leftover_ids, used_in_session_id=None)
        flash("Leftovers marked as used. You can now start boxing new cornices.", "success")
        return redirect(url_for('boxing.start_boxing_session'))

    return render_template(
        'boxing/use_leftovers.html',
        leftovers=leftovers,
        profile_code=profile_code,
        form=form
    )
