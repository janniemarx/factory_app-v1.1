from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
import os
import tempfile
from datetime import datetime
from .forms import (
    StartWireCuttingSessionForm,
    CaptureWireCuttingProductionForm,
    WireCuttingSessionFilterForm, UploadCutPlanForm
)
from blueprints.cutting.db_helpers import (
    get_machines, get_profiles_for_machine, get_oldest_block_for_profile,
    start_wire_cutting_session, get_session_detail, pause_session, resume_session,
    complete_session, calculate_actual_cut_time, parse_cutting_excel, auto_assign_profiles_to_machines, save_machine_profile_assignments, get_profile_block_requirements
)
from models.cutting import (
    WireCuttingSession, Machine, MachineProfileAssignment, Profile
)
from models.production import CuttingProductionRecord
from models.operator import Operator

cutting_bp = Blueprint('cutting', __name__, template_folder='../../templates/cutting')

# ---------- Start a Wire Cutting Session ----------
@cutting_bp.route('/start_session', methods=['GET', 'POST'])
@login_required
def start_session():
    form = StartWireCuttingSessionForm()
    machines, m_err = get_machines()
    form.machine_id.choices = [(0, 'Select Machine...')] + [(m.id, m.name) for m in machines]

    # On GET or first load, empty profiles and blocks (dynamic via JS)
    form.profile_code.choices = []
    form.block_id.choices = []

    if request.method == 'POST':
        # Dynamically populate profile and block choices for validation
        machine_id = form.machine_id.data or request.form.get('machine_id', type=int)
        profiles, _ = get_profiles_for_machine(machine_id)
        form.profile_code.choices = [(p.code, p.code) for p in profiles]
        profile_code = form.profile_code.data or request.form.get('profile_code')
        block = None
        if profile_code:
            block, _ = get_oldest_block_for_profile(profile_code)
            if block:
                form.block_id.choices = [(block.id, block.block_number)]
        # On POST: process form
        if form.validate_on_submit():
            session, error = start_wire_cutting_session(form, current_user.id)
            if error:
                flash(error, "danger")
                return redirect(url_for('cutting.start_session'))
            flash("Wire cutting session started.", "success")
            return redirect(url_for('cutting.session_detail', session_id=session.id))
        else:
            flash("Please correct errors in the form.", "danger")
    return render_template('cutting/start_session.html', form=form)

# ---------- Cutting Session Detail & Capture Production ----------
@cutting_bp.route('/session/<int:session_id>', methods=['GET', 'POST'])
@login_required
def session_detail(session_id):
    session, error = get_session_detail(session_id)
    if not session:
        flash(error or "Session not found.", "danger")
        return redirect(url_for('cutting.view_sessions'))

    block = session.block
    machine = session.machine
    operator = session.operator
    profile = session.profile
    form = CaptureWireCuttingProductionForm(obj=session)
    actual_cut_time = calculate_actual_cut_time(session)

    if request.method == 'POST' and session.status == 'active':
        # PAUSE
        if "pause" in request.form:
            success, err = pause_session(session)
            if not success:
                flash(f"Pause error: {err}", "danger")
            else:
                flash("Session paused.", "warning")
            return redirect(url_for('cutting.session_detail', session_id=session.id))

        # RESUME
        elif "resume" in request.form:
            success, err = resume_session(session)
            if not success:
                flash(f"Resume error: {err}", "danger")
            else:
                flash("Session resumed.", "success")
            return redirect(url_for('cutting.session_detail', session_id=session.id))

        # COMPLETE & RECORD PRODUCTION
        elif "complete" in request.form:
            if form.validate_on_submit():
                success, err = complete_session(session, form)
                if not success:
                    flash(f"Could not complete session: {err}", "danger")
                    return redirect(url_for('cutting.session_detail', session_id=session.id))
                flash("Wire cutting session completed and production recorded.", "success")
                return redirect(url_for('cutting.view_sessions'))
            else:
                flash("Please enter the number of cornices cut.", "danger")

    # Ensure at least one segment exists for active sessions
    if session.status == 'active' and not session.segments:
        from models.cutting import WireCuttingSessionSegment
        seg = WireCuttingSessionSegment(session_id=session.id, start_time=datetime.utcnow())
        from models import db
        db.session.add(seg)
        db.session.commit()

    return render_template(
        'cutting/session_detail.html',
        session=session,
        block=block,
        machine=machine,
        operator=operator,
        profile=profile,
        form=form,
        actual_cut_time=actual_cut_time
    )

# ---------- View All Cutting Sessions ----------
@cutting_bp.route('/view_sessions', methods=['GET', 'POST'])
@login_required
def view_sessions():
    form = WireCuttingSessionFilterForm(request.form)
    form.machine_id.choices = [(0, '--All Machines--')] + [
        (m.id, m.name) for m in Machine.query.order_by(Machine.name).all()
    ]
    form.operator_id.choices = [(0, '--All Operators--')] + [
        (o.id, o.full_name or o.username) for o in Operator.query.order_by(Operator.full_name).all()
    ]
    # Add all known profile codes (can be improved by querying your Profile model)
    form.profile_code.choices = [('', '--All Profiles--')] + [
        (p.code, p.code) for p in Profile.query.order_by(Profile.code).all()
    ]

    query = WireCuttingSession.query.order_by(WireCuttingSession.start_time.desc())
    if form.validate_on_submit():
        if form.machine_id.data and form.machine_id.data != 0:
            query = query.filter_by(machine_id=form.machine_id.data)
        if form.profile_code.data:
            query = query.filter_by(profile_code=form.profile_code.data)
        if form.operator_id.data and form.operator_id.data != 0:
            query = query.filter_by(operator_id=form.operator_id.data)
    sessions = query.all()
    return render_template('cutting/view_cutting_sessions.html', sessions=sessions, form=form)

# ---------- AJAX: Get profiles for a machine ----------
@cutting_bp.route('/get_profiles_for_machine', methods=['POST'])
@login_required
def api_get_profiles_for_machine():
    machine_id = request.json.get('machine_id')
    profiles, error = get_profiles_for_machine(machine_id)
    if error:
        return jsonify({'error': error}), 500
    data = [{'code': p.code, 'label': p.code} for p in profiles]
    return jsonify({'profiles': data})

# ---------- AJAX: Get oldest block for profile ----------
@cutting_bp.route('/get_oldest_block_for_profile', methods=['POST'])
@login_required
def api_get_oldest_block_for_profile():
    profile_code = request.json.get('profile_code')
    block, error = get_oldest_block_for_profile(profile_code)
    if not block:
        return jsonify({'error': error or "No suitable block found"}), 404
    return jsonify({'block_id': block.id, 'block_number': block.block_number})

# ---------- Assign profiles to machines (admin) ----------


@cutting_bp.route('/upload_cut_plan', methods=['GET', 'POST'])
@login_required
def upload_cut_plan():
    """
    Step 1: Manager uploads the Excel. We parse, compute, and show plan for confirmation.
    """
    form = UploadCutPlanForm()
    if form.validate_on_submit():
        file = form.file.data
        if not file:
            flash("Please upload a file", "danger")
            return redirect(request.url)

        # Save using tempfile (works on all platforms)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as temp_file:
            file.save(temp_file.name)
            path = temp_file.name

        # Process the file
        try:
            rows = parse_cutting_excel(path)
        finally:
            # Always clean up the file
            os.remove(path)

        if not rows:
            flash("No valid PR profiles found in file.", "danger")
            return redirect(request.url)

        requirements = get_profile_block_requirements(rows)

        # STEP 1: Fetch profiles and pass to template
        profiles = {p.code: p for p in Profile.query.all()}

        return render_template(
            'cutting/preview_assignment.html',
            requirements=requirements,
            profiles=profiles
        )
    # GET or invalid POST: show form again
    return render_template('cutting/upload_cut_plan.html', form=form)


@cutting_bp.route('/auto_assign', methods=['POST'])
@login_required
def auto_assign():
    """
    Step 2: Auto-assign based on parsed requirements and save assignments.
    """
    data = request.json
    print("DEBUG: /auto_assign received data:", data)
    requirements = data.get('requirements')
    allow_overtime = data.get('allow_overtime', False)

    # Defensive filter for valid requirements
    if not isinstance(requirements, list):
        print("DEBUG: requirements is not a list!", requirements)
        return jsonify({"error": "Invalid requirements."}), 400

    requirements = [r for r in requirements if isinstance(r.get('blocks_needed'), int) and r['blocks_needed'] > 0]

    if not requirements:
        print("DEBUG: No valid requirements after filter.", requirements)
        return jsonify({"error": "No profiles to assign."}), 400

    assignment, err = auto_assign_profiles_to_machines(requirements, allow_overtime=allow_overtime)
    if err:
        print("DEBUG: Assignment error:", err)
        return jsonify({"error": err}), 400
    success, err = save_machine_profile_assignments(assignment)
    if not success:
        print("DEBUG: Save error:", err)
        return jsonify({"error": err}), 400
    return jsonify({"success": True})


@cutting_bp.route('/assign_profiles', methods=['GET', 'POST'])
@login_required
def assign_profiles():
    """
    Allows review/edit of machine assignments and saving.
    """
    if not getattr(current_user, "is_manager", False):
        flash("Unauthorized.", "danger")
        return redirect(url_for('cutting.view_sessions'))

    machines = Machine.query.order_by(Machine.name).all()
    profiles = Profile.query.order_by(Profile.code).all()
    assignments = MachineProfileAssignment.query.all()

    # === FIX: BUILD assignment_counts ===
    assignment_counts = {}
    for a in assignments:
        key = (a.machine_id, a.profile_code)
        assignment_counts[key] = assignment_counts.get(key, 0) + 1

    if request.method == 'POST':
        from models import db
        try:
            MachineProfileAssignment.query.delete()
            db.session.commit()
            for machine in machines:
                for profile in profiles:
                    key = f'profile_count_{machine.id}_{profile.code}'
                    count = int(request.form.get(key, 0))
                    for _ in range(count):
                        db.session.add(MachineProfileAssignment(
                            machine_id=machine.id,
                            profile_code=profile.code
                        ))
            db.session.commit()
            flash("Profile assignments updated!", "success")
        except Exception as e:
            db.session.rollback()
            flash(f"Could not update assignments: {e}", "danger")
        return redirect(url_for('cutting.assign_profiles'))

    return render_template(
        'cutting/assign_profiles.html',
        machines=machines,
        profiles=profiles,
        assignments=assignments,
        assignment_counts=assignment_counts  # <-- Pass this!
    )
