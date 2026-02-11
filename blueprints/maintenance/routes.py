from __future__ import annotations

from flask import Blueprint, render_template, redirect, url_for, flash, request, abort
from flask_login import login_required, current_user

from .forms import (
    JobCreateForm, AcceptJobForm, StepLogForm, PauseResumeForm,
    SessionCloseForm, SubmitForReviewForm, ReviewForm
)
from .db_helpers import (
    create_job, list_jobs, get_job, accept_job,
    pause_session, resume_session, add_step, complete_session,
    submit_job_for_review, review_job
)
from models.maintenance import MaintenanceJob, MaintenanceWorkSession

maintenance_bp = Blueprint("maintenance", __name__, template_folder='../../templates/maintenance')

# -------------------- Jobs: create + list --------------------

@maintenance_bp.route("/jobs/new", methods=["GET", "POST"])
@login_required
def job_new():
    form = JobCreateForm()
    if form.validate_on_submit():
        job, err = create_job(
            title=form.title.data,
            description=form.description.data,
            reported_by_id=getattr(current_user, "id", None),
            location=form.location.data,
            asset_code=form.asset_code.data,
            priority=form.priority.data,
            category=form.category.data,
        )
        if err:
            flash(f"Could not create job: {err}", "danger")
            return redirect(url_for("maintenance.job_new"))
        flash("Job created.", "success")
        return redirect(url_for("maintenance.jobs_list", status="open"))
    return render_template("maintenance/job_new.html", form=form)

@maintenance_bp.route("/jobs")
@login_required
def jobs_list():
    status = request.args.get("status")  # open / assigned / in_progress / in_review / rework_requested / closed
    my = request.args.get("mine", type=int) == 1
    tech_id = getattr(current_user, "id", None) if my else None

    jobs = list_jobs(status=status, assigned_to_id=tech_id)
    return render_template("maintenance/jobs_list.html", jobs=jobs, filters={"status": status, "mine": my})

# -------------------- Job detail & accept --------------------

@maintenance_bp.route("/jobs/<int:job_id>")
@login_required
def job_detail(job_id: int):
    job = get_job(job_id)
    if not job:
        flash("Job not found.", "danger")
        return redirect(url_for("maintenance.jobs_list"))
    accept_form = AcceptJobForm()
    submit_for_review_form = SubmitForReviewForm()
    return render_template("maintenance/job_detail.html", job=job,
                           accept_form=accept_form, submit_for_review_form=submit_for_review_form)

@maintenance_bp.route("/jobs/<int:job_id>/accept", methods=["POST"])
@login_required
def job_accept(job_id: int):
    job = get_job(job_id)
    if not job:
        abort(404)
    form = AcceptJobForm()
    if not form.validate_on_submit():
        flash("Please confirm acceptance.", "danger")
        return redirect(url_for("maintenance.job_detail", job_id=job.id))

    ok, err, sess = accept_job(job, technician_id=getattr(current_user, "id", None))
    if not ok:
        flash(f"Could not accept job: {err}", "danger")
        return redirect(url_for("maintenance.job_detail", job_id=job.id))

    flash("Job accepted. Work session started.", "success")
    return redirect(url_for("maintenance.session_detail", session_id=sess.id))

@maintenance_bp.route("/jobs/<int:job_id>/submit_for_review", methods=["POST"])
@login_required
def job_submit_for_review(job_id: int):
    job = get_job(job_id)
    if not job:
        abort(404)
    form = SubmitForReviewForm()
    if not form.validate_on_submit():
        flash("Invalid request.", "danger")
        return redirect(url_for("maintenance.job_detail", job_id=job.id))
    ok, err = submit_job_for_review(job)
    flash("Job submitted for review." if ok else f"Submit failed: {err}", "success" if ok else "danger")
    return redirect(url_for("maintenance.jobs_review_queue"))

# -------------------- Session detail (steps / pause / resume / complete) --------------------

@maintenance_bp.route("/sessions/<int:session_id>", methods=["GET", "POST"])
@login_required
def session_detail(session_id: int):
    session = MaintenanceWorkSession.query.get_or_404(session_id)
    job = session.job

    step_form = StepLogForm()
    pr_form = PauseResumeForm()
    close_form = SessionCloseForm()

    if request.method == "POST":
        # Add step
        if "add_step" in request.form and step_form.validate_on_submit():
            step, err = add_step(session, step_form.description.data, getattr(current_user, "id", None))
            flash("Step added." if step else f"Could not add step: {err}", "info" if step else "danger")
            return redirect(url_for("maintenance.session_detail", session_id=session.id))

        # Pause
        if "pause" in request.form and not session.is_paused and session.status == "in_progress":
            ok, err = pause_session(session)
            flash("Session paused." if ok else f"Pause failed: {err}", "warning" if ok else "danger")
            return redirect(url_for("maintenance.session_detail", session_id=session.id))

        # Resume
        if "resume" in request.form and session.is_paused and session.status == "in_progress":
            ok, err = resume_session(session)
            flash("Session resumed." if ok else f"Resume failed: {err}", "success" if ok else "danger")
            return redirect(url_for("maintenance.session_detail", session_id=session.id))

        # Complete
        if "complete" in request.form and close_form.validate_on_submit():
            ok, err = complete_session(session, closing_summary=close_form.closing_summary.data)
            flash("Session completed." if ok else f"Complete failed: {err}", "success" if ok else "danger")
            return redirect(url_for("maintenance.job_detail", job_id=job.id))

        # Validation fallthrough
        if "add_step" in request.form and not step_form.validate():
            flash("Please describe the step.", "danger")
        elif "complete" in request.form and not close_form.validate():
            flash("Please provide a closing summary (optional but the form must be valid).", "danger")
        return redirect(url_for("maintenance.session_detail", session_id=session.id))

    return render_template(
        "maintenance/session_detail.html",
        session=session, job=job,
        step_form=step_form, pr_form=pr_form, close_form=close_form
    )

# -------------------- Review queue & review --------------------

@maintenance_bp.route("/jobs/review_queue")
@login_required
def jobs_review_queue():
    jobs = list_jobs(status="in_review")
    return render_template("maintenance/jobs_review_queue.html", jobs=jobs)

@maintenance_bp.route("/jobs/<int:job_id>/review", methods=["GET", "POST"])
@login_required
def job_review(job_id: int):
    job = get_job(job_id)
    if not job:
        abort(404)
    if job.status != "in_review":
        flash("Job is not awaiting review.", "warning")
        return redirect(url_for("maintenance.jobs_list"))

    form = ReviewForm()
    if form.validate_on_submit():
        ok, err, _ = review_job(
            job,
            reviewed_by_id=getattr(current_user, "id", None),
            decision=form.decision.data,
            notes=form.notes.data
        )
        flash("Review saved." if ok else f"Review failed: {err}", "success" if ok else "danger")
        return redirect(url_for("maintenance.jobs_list", status="closed" if ok and form.decision.data=="approved" else None))

    return render_template("maintenance/job_review.html", job=job, form=form)
