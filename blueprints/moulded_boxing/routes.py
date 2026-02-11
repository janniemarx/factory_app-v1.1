from flask import Blueprint, render_template, redirect, url_for, flash, request, session as flask_session
from flask_login import login_required, current_user

from .forms import (
    StartMouldedBoxingForm,
    SaveLineForm,
    PauseResumeForm,
    FinishMouldedBoxingForm,
    MouldedBoxingQCForm,
    ProfileBoxesForm,
)

# Pull in everything you actually call from db_helpers:
from .db_helpers import (
    list_completed_unboxed_sessions,
    create_or_get_active_boxing_session,
    pause_session,
    resume_session,
    force_finish_boxing,
    add_item_save,
    # finish_boxing_if_complete,   # <-- no longer auto-finishing on save
    produced_target_by_profile,
    boxed_so_far_by_profile,
    perform_qc, list_boxing_sessions
)

from models.moulded_cornice import MouldedCorniceSession
from models.moulded_boxing import MouldedBoxingSession, MOULDED_CORNICES_PER_BOX


moulded_boxing_bp = Blueprint(
    "moulded_boxing", __name__, template_folder='../../templates/moulded_boxing'
)


def _qc_state_get(boxing_session_id: int) -> dict:
    return flask_session.get("moulded_qc", {}).get(str(boxing_session_id), {})

def _qc_state_set(boxing_session_id: int, code: str, counted: int, match: bool) -> None:
    store = flask_session.setdefault("moulded_qc", {})
    sid = str(boxing_session_id)
    if sid not in store:
        store[sid] = {}
    store[sid][code] = {"counted": int(counted or 0), "match": bool(match)}
    flask_session.modified = True


# ---------- Start chooser ----------
@moulded_boxing_bp.route("/start", methods=["GET", "POST"])
@login_required
def start():
    form = StartMouldedBoxingForm()

    sessions = list_completed_unboxed_sessions()
    form.moulded_session_id.choices = [
        (
            s.id,
            f"Session #{s.id} | Batch {s.pre_expansion.batch_no if s.pre_expansion else '-'} "
            f"| Ended {s.end_time.strftime('%Y-%m-%d %H:%M') if s.end_time else '-'}"
        )
        for s in sessions
    ]

    if form.validate_on_submit():
        s_id = form.moulded_session_id.data
        return redirect(url_for("moulded_boxing.boxing", moulded_session_id=s_id))

    return render_template("moulded_boxing/start.html", form=form, sessions=sessions)


# ---------- Boxing workbench (per-line save) ----------
@moulded_boxing_bp.route("/start/<int:moulded_session_id>", methods=["GET", "POST"])
@login_required
def boxing(moulded_session_id: int):
    moulded = MouldedCorniceSession.query.get_or_404(moulded_session_id)

    session, err = create_or_get_active_boxing_session(moulded.id, current_user.id)
    if err or not session:
        flash(f"Could not open boxing session: {err}", "danger")
        return redirect(url_for("moulded_boxing.start"))

    # If the session is no longer active, prevent adding new lines here.
    if request.method == "GET" and session.status != "active":
        flash(f"This boxing session is {session.status.replace('_', ' ')}. No more line saves allowed.", "info")

    pause_form = PauseResumeForm()
    finish_form = FinishMouldedBoxingForm()

    if request.method == "POST":
        if "pause" in request.form:
            ok, err = pause_session(session)
            flash("Paused." if ok else f"Pause failed: {err}", "warning" if ok else "danger")
            return redirect(url_for("moulded_boxing.boxing", moulded_session_id=moulded.id))

        if "resume" in request.form:
            ok, err = resume_session(session)
            flash("Resumed." if ok else f"Resume failed: {err}", "success" if ok else "danger")
            return redirect(url_for("moulded_boxing.boxing", moulded_session_id=moulded.id))

        if "finish" in request.form:
            # Manual finish only: set to pending_qc and DO NOT open QC automatically.
            ok, err = force_finish_boxing(session)
            if not ok:
                flash(f"Finish failed: {err}", "danger")
                return redirect(url_for("moulded_boxing.boxing", moulded_session_id=moulded.id))
            flash("Session moved to QC Pending. You can QC it later from the sessions list.", "success")
            return redirect(url_for("moulded_boxing.list_sessions"))

    # Build only the rows we allow them to work on (no produced/remaining shown)
    targets = produced_target_by_profile(moulded)
    progress = boxed_so_far_by_profile(moulded.id)

    rows = []
    for code, target_c in sorted(targets.items()):
        done = progress.get(code, 0)
        remaining = max(target_c - done, 0)
        if remaining <= 0:
            continue
        rows.append({
            "profile_code": code,
            "cornices_per_box": MOULDED_CORNICES_PER_BOX.get(code, 0),
        })

    forms = {
        r["profile_code"]: SaveLineForm(session_id=session.id, profile_code=r["profile_code"])
        for r in rows
    }

    return render_template(
        "moulded_boxing/boxing_session.html",
        session=session,
        moulded=moulded,
        rows=rows,
        forms=forms,
        pause_form=pause_form,
        finish_form=finish_form,
    )


# Save line POST
@moulded_boxing_bp.route("/save_line", methods=["POST"])
@login_required
def save_line():
    form = SaveLineForm()
    if not form.validate_on_submit():
        flash("Invalid input for save.", "danger")
        try:
            bs = MouldedBoxingSession.query.get(int(request.form.get("session_id", "0")))
            return redirect(url_for("moulded_boxing.boxing", moulded_session_id=(bs.moulded_session_id if bs else 0)))
        except Exception:
            return redirect(url_for("moulded_boxing.start"))

    boxing_session_id = int(form.session_id.data)
    bs = MouldedBoxingSession.query.get_or_404(boxing_session_id)

    # HARD BLOCK while paused
    if bs.is_paused or bs.status == "paused":
        flash("Session is paused. Resume before adding boxes.", "warning")
        return redirect(url_for("moulded_boxing.boxing", moulded_session_id=bs.moulded_session_id))

    # Also block if not active (e.g., pending_qc or stock_ready)
    if bs.status != "active":
        flash(f"Cannot save lines while session is {bs.status.replace('_', ' ')}.", "warning")
        return redirect(url_for("moulded_boxing.boxing", moulded_session_id=bs.moulded_session_id))

    profile_code = form.profile_code.data
    boxes = form.boxes_packed.data or 0
    leftovers = form.leftovers.data or 0

    ok, err = add_item_save(boxing_session_id, profile_code, boxes, leftovers)
    if not ok:
        flash(f"Save failed: {err}", "danger")
        return redirect(url_for("moulded_boxing.boxing", moulded_session_id=bs.moulded_session_id))

    flash(f"Saved {boxes} boxes + {leftovers} leftovers for {profile_code}.", "success")

    # Do NOT auto-finish. Just hint if everything is boxed.
    produced = produced_target_by_profile(bs.moulded_session)
    boxed = boxed_so_far_by_profile(bs.moulded_session_id)
    remaining = sum(max(produced.get(k, 0) - boxed.get(k, 0), 0) for k in produced)
    if remaining <= 0:
        flash("All profiles are boxed. Click ‘Finish Boxing’ to move to QC Pending.", "info")

    return redirect(url_for("moulded_boxing.boxing", moulded_session_id=bs.moulded_session_id))


# ---------- QC ----------
@moulded_boxing_bp.route("/qc/<int:boxing_session_id>", methods=["GET", "POST"])
@login_required
def qc(boxing_session_id):
    sess = MouldedBoxingSession.query.get_or_404(boxing_session_id)

    # Allow read-only view after completion
    read_only = (sess.status == "stock_ready")

    if not read_only and sess.status != "pending_qc":
        flash("QC is only available after finishing boxing.", "warning")
        return redirect(url_for("moulded_boxing.boxing", moulded_session_id=sess.moulded_session_id))

    # Expected BOXES per profile for THIS boxing session
    expected_boxes = {}
    for it in sess.items:
        expected_boxes[it.profile_code] = expected_boxes.get(it.profile_code, 0) + int(it.boxes_packed or 0)

    # Pull saved per-row QC state from the user's session
    def _qc_state_get_all():
        return flask_session.get("moulded_qc", {}).get(str(boxing_session_id), {})  # {code: {counted, match}}

    def _qc_state_set(code, counted, match):
        store = flask_session.setdefault("moulded_qc", {})
        sid = str(boxing_session_id)
        store.setdefault(sid, {})
        store[sid][code] = {"counted": int(counted or 0), "match": bool(match)}
        flask_session.modified = True

    qc_state = _qc_state_get_all()

    # Build the WTForms container
    form = MouldedBoxingQCForm()

    # Prefill rows for GET or first render
    if request.method == "GET" and not form.rows.entries:
        for code in sorted(expected_boxes.keys()):
            row = ProfileBoxesForm()
            row.profile_code.data = code
            row.counted_boxes.data = qc_state.get(code, {}).get("counted", 0)
            form.rows.append_entry(row.data)

    # Helper: compute matches + needs_reason flag from qc_state
    def _matches_and_flag_from_state():
        matches_map = {}
        for code in expected_boxes.keys():
            matches_map[code] = qc_state.get(code, {}).get("match", None)
        needs_reason_flag = any(v is False for v in matches_map.values())
        return matches_map, needs_reason_flag

    matches, needs_reason = _matches_and_flag_from_state()

    # READ-ONLY VIEW: just render
    if read_only:
        return render_template(
            "moulded_boxing/qc.html",
            session=sess, form=form,
            matches=matches, needs_reason=False, read_only=True
        )

    # ------- FINAL SUBMIT -------
    if form.validate_on_submit():
        # If the rows weren’t posted (because each row is saved via its own form),
        # reconstruct counts from saved qc_state.
        counted_by_profile = {}

        if form.rows.entries:
            # We got rows in this POST — use them and update state
            for sub in form.rows.entries:
                code = sub.form.profile_code.data
                counted = int(sub.form.counted_boxes.data or 0)
                counted_by_profile[code] = counted
                _qc_state_set(code, counted, counted == expected_boxes.get(code, 0))
        else:
            # No rows posted: fall back entirely to saved state
            for code in expected_boxes.keys():
                counted_by_profile[code] = int(qc_state.get(code, {}).get("counted", 0))

        # Re-evaluate mismatches now
        mismatches = {
            c: {"expected": expected_boxes.get(c, 0), "counted": counted_by_profile.get(c, 0)}
            for c in expected_boxes.keys()
            if counted_by_profile.get(c, 0) != expected_boxes.get(c, 0)
        }

        if mismatches and not (form.discrepancy_reason.data and form.discrepancy_reason.data.strip()):
            flash("Counts don’t match. Please provide a reason.", "danger")
            # Force-enable textarea on rerender
            forced_matches = {c: (False if c in mismatches else True) for c in expected_boxes.keys()}
            return render_template(
                "moulded_boxing/qc.html",
                session=sess, form=form,
                matches=forced_matches, needs_reason=True, read_only=False
            )

        if not form.confirm_all_boxes_complete.data:
            flash("Please confirm all boxes are complete and ready for selling.", "danger")
            matches, needs_reason = _matches_and_flag_from_state()
            return render_template(
                "moulded_boxing/qc.html",
                session=sess, form=form,
                matches=matches, needs_reason=needs_reason, read_only=False
            )

        # Totals (still stored on QC record)
        total_boxes_checked = sum(counted_by_profile.values())
        total_cornices_checked = sum(
            (counted_by_profile.get(code, 0) or 0) * MOULDED_CORNICES_PER_BOX.get(code, 0)
            for code in expected_boxes.keys()
        )

        notes = (
            f"[QC PROFILE BOXES] {counted_by_profile} | "
            f"[EXPECTED] {expected_boxes} | "
            f"[MISMATCH] {mismatches if mismatches else 'NONE'} | "
            f"[REASON] {form.discrepancy_reason.data or ''}"
        )

        ok, err = perform_qc(
            sess, current_user.id,
            boxes_checked=total_boxes_checked,
            good_cornices_count=total_cornices_checked,
            notes=notes,
            actions=form.discrepancy_reason.data or None
        )
        if ok:
            # Clear transient per-session QC state
            try:
                flask_session.get("moulded_qc", {}).pop(str(boxing_session_id), None)
                flask_session.modified = True
            except Exception:
                pass
            flash("QC complete. Stock ready.", "success")
            return redirect(url_for("moulded_boxing.list_sessions"))

        flash(f"QC failed: {err}", "danger")
        matches, needs_reason = _matches_and_flag_from_state()
        return render_template(
            "moulded_boxing/qc.html",
            session=sess, form=form,
            matches=matches, needs_reason=needs_reason, read_only=False
        )

    # POST but invalid form (e.g., forgot the checkbox)
    if request.method == "POST":
        if not form.confirm_all_boxes_complete.data:
            flash("Please confirm all boxes are complete and ready for selling.", "danger")
        else:
            flash("There was a problem submitting the form. Please check your entries.", "danger")

    # Initial GET / fallback render
    return render_template(
        "moulded_boxing/qc.html",
        session=sess, form=form,
        matches=matches, needs_reason=needs_reason, read_only=False
    )


# ---------- List ----------
@moulded_boxing_bp.route("/sessions", methods=["GET"], endpoint="list_sessions")
@login_required
def list_sessions_view():
    sessions = list_boxing_sessions()
    return render_template("moulded_boxing/list.html", sessions=sessions)


@moulded_boxing_bp.route("/qc/save_row/<int:boxing_session_id>", methods=["POST"])
@login_required
def qc_save_row(boxing_session_id):
    sess = MouldedBoxingSession.query.get_or_404(boxing_session_id)
    if sess.status != "pending_qc":
        flash("QC is only available after finishing boxing.", "warning")
        return redirect(url_for("moulded_boxing.boxing", moulded_session_id=sess.moulded_session_id))

    f = ProfileBoxesForm()  # CSRF ON
    if not f.validate_on_submit():
        flash("Invalid row input.", "danger")
        return redirect(url_for("moulded_boxing.qc", boxing_session_id=boxing_session_id))

    # Expected boxes this session (per profile)
    expected_boxes = {}
    for it in sess.items:
        expected_boxes[it.profile_code] = expected_boxes.get(it.profile_code, 0) + int(it.boxes_packed or 0)

    code = f.profile_code.data
    counted = int(f.counted_boxes.data or 0)
    match = (counted == expected_boxes.get(code, 0))

    # Persist row state
    store = flask_session.setdefault("moulded_qc", {})
    sid = str(boxing_session_id)
    store.setdefault(sid, {})
    store[sid][code] = {"counted": counted, "match": match}
    flask_session.modified = True

    return redirect(url_for("moulded_boxing.qc", boxing_session_id=boxing_session_id))
