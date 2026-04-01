from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from models import db
from models.moulded_cornice import MouldedMachine
from sqlalchemy import exists
from models.pre_expansion import PreExpansion
from models.moulded_cornice import (
    MouldedCorniceSession, MouldedCorniceLine, MouldedCorniceProductionSummary, CORNICE_PROFILE_WEIGHTS
)
from .forms import StartMouldedCorniceSessionForm, FinishMouldedCorniceSessionForm
from datetime import datetime

moulded_cornice_bp = Blueprint(
    'moulded_cornice', __name__, template_folder='../../templates/moulded_cornice'
)

MOULD_PROFILE_CHOICES = {
    1: [('M01', 'M01'), ('M02', 'M02')],
    2: [('M03', 'M03'), ('M04', 'M04'), ('M05', 'M05'), ('M06', 'M06'), ('M07', 'M07'), ('M13', 'M13')],
    3: [('M01', 'M01'), ('M02', 'M02'), ('M08', 'M08'), ('M09', 'M09'), ('M10', 'M10'), ('M11', 'M11'), ('M12', 'M12')],
}

# ---------- Start Session (SETUP ONLY) ----------
@moulded_cornice_bp.route('/start_session', methods=['GET', 'POST'])
@login_required
def start_session():
    # Exclude batches that already have an active/setup moulded session (legacy sessions may not set is_used yet)
    active_exists = (
        db.session.query(MouldedCorniceSession.id)
        .filter(MouldedCorniceSession.pre_expansion_id == PreExpansion.id)
        .filter(MouldedCorniceSession.status.in_(['setup', 'active']))
        .exists()
    )
    batches = (
        PreExpansion.query
        .filter_by(status='completed', is_used=False, purpose='Moulded')
        .filter(~active_exists)
        .all()
    )

    # NEW: load active machines
    machines = MouldedMachine.query.filter_by(is_active=True).order_by(MouldedMachine.id.asc()).all()

    form = StartMouldedCorniceSessionForm()
    form.pre_expansion_id.choices = [
        (b.id, f"{b.batch_no} ({b.density}g/l, {b.planned_kg}kg)") for b in batches
    ]
    form.machine_id.choices = [(m.id, m.name) for m in machines]  # NEW

    error_msgs = []

    if request.method == 'POST':
        try:
            pre_exp_id = int(request.form.get('pre_expansion_id'))
            mould_number = int(request.form.get('mould_number'))
            machine_id = int(request.form.get('machine_id'))  # NEW
        except (ValueError, TypeError):
            error_msgs.append("Please select a valid Pre-Expansion batch, Machine, and Mould.")
            return render_template('moulded_cornice/add_session.html',
                                   form=form, profile_map=MOULD_PROFILE_CHOICES, errors=error_msgs)

        # sanity: ensure machine exists/active
        machine = MouldedMachine.query.get(machine_id)
        if not machine or not machine.is_active:
            error_msgs.append("Selected machine is invalid or inactive.")
            return render_template('moulded_cornice/add_session.html',
                                   form=form, profile_map=MOULD_PROFILE_CHOICES, errors=error_msgs)

        line_count = 5 if mould_number == 1 else 6
        profiles = []
        for i in range(line_count):
            val = request.form.get(f'line_configs-{i}-profile_code')
            if not val:
                error_msgs.append(f"Line {i + 1}: Please select a profile.")
            profiles.append(val)

        if error_msgs:
            return render_template('moulded_cornice/add_session.html',
                                   form=form, profile_map=MOULD_PROFILE_CHOICES, errors=error_msgs)

        # Create session in 'setup' status
        session = MouldedCorniceSession(
            pre_expansion_id=pre_exp_id,
            operator_id=current_user.id,
            mould_number=mould_number,
            machine_id=machine_id,  # NEW
            status='setup',
            start_time=datetime.utcnow(),
            cycles=0
        )
        db.session.add(session)
        db.session.flush()

        # Immediately mark the selected pre-expansion as used to avoid re-selection
        pre = PreExpansion.query.get(pre_exp_id)
        if pre:
            pre.is_used = True

        for i, profile_code in enumerate(profiles):
            config = MouldedCorniceLine(
                session_id=session.id,
                line_number=i + 1,
                profile_code=profile_code
            )
            db.session.add(config)

        db.session.commit()
        flash('Moulded Cornice Session Started.', 'success')
        return redirect(url_for('moulded_cornice.session_detail', session_id=session.id))

    return render_template('moulded_cornice/add_session.html',
                           form=form, profile_map=MOULD_PROFILE_CHOICES, errors=error_msgs)



# ---------- View Sessions (Active and Completed) ----------
@moulded_cornice_bp.route('/view_sessions')
@login_required
def view_sessions():
    sessions = MouldedCorniceSession.query.order_by(MouldedCorniceSession.start_time.desc()).all()
    return render_template('moulded_cornice/view_sessions.html', sessions=sessions)

# ---------- Active Sessions (setup/active) ----------
@moulded_cornice_bp.route('/active_sessions')
@login_required
def active_sessions():
    sessions = (MouldedCorniceSession.query
                .filter(MouldedCorniceSession.status.in_(['setup', 'active']))
                .order_by(MouldedCorniceSession.start_time.desc())
                .all())
    return render_template('moulded_cornice/view_active_moulded.html', sessions=sessions)

# ---------- Session Detail / Add Cycles ----------
@moulded_cornice_bp.route('/session/<int:session_id>', methods=['GET', 'POST'])
@login_required
def session_detail(session_id):
    session = MouldedCorniceSession.query.get_or_404(session_id)
    pre_exp = session.pre_expansion
    configs = session.lines  # List of MouldedCorniceLine
    finish_form = FinishMouldedCorniceSessionForm()
    error_msg = None

    if request.method == 'POST' and 'finish_session' in request.form and session.status in ('active', 'setup'):
        try:
            cycles = int(request.form.get('total_cycles'))
            if cycles <= 0:
                raise ValueError()
        except (TypeError, ValueError):
            error_msg = "Please enter a valid positive number of cycles."
        else:
            session.cycles = cycles
            session.status = 'completed'
            session.end_time = datetime.utcnow()
            session.pre_expansion.is_used = True

            # --- Calculate actual production per profile ---
            total_weight = 0.0
            # Delete previous summaries if any (in case of resubmit)
            MouldedCorniceProductionSummary.query.filter_by(session_id=session.id).delete()
            db.session.flush()

            for line in configs:
                profile_code = line.profile_code
                qty = cycles  # Each line runs every cycle
                weight_per_cornice = CORNICE_PROFILE_WEIGHTS.get(profile_code, 0)
                profile_total_weight = qty * weight_per_cornice / 1000.0  # in kg
                total_weight += profile_total_weight

                summary = MouldedCorniceProductionSummary(
                    session_id=session.id,
                    profile_code=profile_code,
                    quantity=qty,
                    total_weight_kg=round(profile_total_weight, 3)
                )
                db.session.add(summary)

            session.actual_produced_kg = round(total_weight, 3)
            # Compare against actual beads produced for the pre-expansion; fallback to planned if unknown
            actual_beads_kg = float(session.pre_expansion.total_kg_used or 0.0)
            planned_beads_kg = float(session.pre_expansion.planned_kg or 0.0)
            session.planned_kg = actual_beads_kg if actual_beads_kg > 0 else planned_beads_kg
            session.loss_kg = round((session.planned_kg or 0) - (session.actual_produced_kg or 0), 3)

            db.session.commit()
            flash(f'Session completed. {cycles} cycles recorded.', 'success')
            return redirect(url_for('moulded_cornice.session_detail', session_id=session.id))

    return render_template(
        'moulded_cornice/session_detail.html',
        session=session, pre_exp=pre_exp, configs=configs,
        finish_form=finish_form, error_msg=error_msg
    )
