from __future__ import annotations

"""Pre-expansion routes (v3).

Goals:
- Keep the same URLs and templates as the legacy app.
- Move orchestration + DB writes into a service layer.
- Keep the very cross-domain `pastel_capture` endpoint delegated to legacy for now
  (it touches blocks + moulding + PR16 stash data).
"""

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from models.pre_expansion import PreExpansion

from blueprints.pre_expansion.forms import (
	DensityCheckForm,
	MarkPastelForm,
	PreExpansionChecklistForm,
	PreExpansionForm,
)

from . import service


pre_expansion_bp = Blueprint(
	"pre_expansion",
	__name__,
	template_folder="../../templates/pre_expansion",
)


@pre_expansion_bp.route("/start_session", methods=["GET", "POST"])
@login_required
def start_pre_expansion_session():
	checklist_id = request.args.get("checklist_id", type=int)
	form = PreExpansionForm()

	if form.validate_on_submit():
		# Legacy rule: density 18 can only be used for Block purpose
		if form.density.data == 18 and form.purpose.data == "Moulded":
			flash("For 18 g/l density, only 'Block' purpose is allowed.", "warning")
			return render_template("pre_expansion/start_pre_expansion.html", form=form)

		pre_exp, err = service.create_session(
			material_code=form.material_type.data,
			density=form.density.data,
			planned_kg=form.planned_kg.data,
			purpose=form.purpose.data,
			operator_id=current_user.id,
		)
		if err or not pre_exp:
			flash(f"Database error: {err}", "danger")
			return render_template("pre_expansion/start_pre_expansion.html", form=form)

		# ---- Option 4 gate (legacy behaviour) ----
		precheck_mode = (request.form.get("precheck_mode") or "").strip().lower()
		if precheck_mode == "skip":
			flash(
				"Pre-Expansion session started without a pre-start checklist (Option 4).",
				"info",
			)
		else:
			checks = {f"check{i}": (request.form.get(f"check{i}") == "y") for i in range(1, 11)}
			for i in range(11, 14):
				checks[f"check{i}"] = False

			_checklist, c_err = service.add_checklist(
				operator=current_user,
				ip_address=request.remote_addr,
				checks=checks,
				pre_expansion_id=pre_exp.id,
			)
			if c_err:
				flash(f"Saved session but failed to log checklist audit: {c_err}", "warning")

		if checklist_id:
			ok, link_err = service.link_checklist_to_session(
				checklist_id=checklist_id,
				pre_expansion_id=pre_exp.id,
			)
			if not ok:
				flash(link_err or "Could not link checklist.", "warning")

		flash("Pre-Expansion session started! Now begin density checks.", "success")
		return redirect(url_for("pre_expansion.active_session", session_id=pre_exp.id))

	return render_template("pre_expansion/start_pre_expansion.html", form=form)


@pre_expansion_bp.route("/active_session/<int:session_id>", methods=["GET", "POST"])
@login_required
def active_session(session_id: int):
	pre_exp = PreExpansion.query.get_or_404(session_id)
	form = DensityCheckForm()

	if form.validate_on_submit():
		_check, err = service.add_density_check(
			pre_expansion_id=pre_exp.id,
			measured_density=form.measured_density.data,
			measured_weight=form.measured_weight.data,
			operator_id=current_user.id,
		)
		if err:
			flash(f"Could not record density check: {err}", "danger")
		else:
			flash("Density check recorded!", "success")
		return redirect(url_for("pre_expansion.active_session", session_id=pre_exp.id))

	return render_template("pre_expansion/active_session.html", pre_exp=pre_exp, form=form)


@pre_expansion_bp.route("/finish_session/<int:session_id>", methods=["GET", "POST"])
@login_required
def finish_session(session_id: int):
	pre_exp = PreExpansion.query.get_or_404(session_id)
	if pre_exp.operator_id != current_user.id:
		flash("You are not allowed to finish this session.", "danger")
		return redirect(url_for("pre_expansion.dashboard"))

	if request.method == "POST":
		total_kg_used = request.form.get("total_kg_used", type=float)
		post_checks = {
			"check11": bool(request.form.get("check11")),
			"check12": bool(request.form.get("check12")),
			"check13": bool(request.form.get("check13")),
		}
		ok, err = service.finish_session(
			pre_exp=pre_exp,
			total_kg_used=total_kg_used,
			operator=current_user,
			ip_address=request.remote_addr,
			post_checks=post_checks,
		)
		if not ok:
			flash(f"Could not finish session: {err}", "danger")
			return render_template("pre_expansion/finish_session.html", pre_exp=pre_exp)

		flash("Pre-Expansion session finished!", "success")
		return redirect(url_for("pre_expansion.view_pre_expansions"))

	return render_template("pre_expansion/finish_session.html", pre_exp=pre_exp)


@pre_expansion_bp.route("/active_sessions")
@login_required
def view_active_sessions():
	sessions, err = service.get_active_sessions()
	if err:
		flash(f"Could not load active sessions: {err}", "danger")
		sessions = []
	return render_template("pre_expansion/view_active_sessions.html", sessions=sessions)


@pre_expansion_bp.route("/view")
@login_required
def view_pre_expansions():
	sessions, err = service.get_completed_sessions()
	if err:
		flash(f"Could not load completed sessions: {err}", "danger")
		sessions = []
	return render_template("pre_expansion/view_pre_expansions.html", pre_expansions=sessions)


@pre_expansion_bp.route("/detail/<int:pre_expansion_id>", methods=["GET", "POST"])
@login_required
def view_pre_expansion_detail(pre_expansion_id: int):
	pre_exp = PreExpansion.query.get_or_404(pre_expansion_id)
	form = DensityCheckForm()
	if form.validate_on_submit():
		_check, err = service.add_density_check(
			pre_expansion_id=pre_exp.id,
			measured_density=form.measured_density.data,
			measured_weight=form.measured_weight.data,
			operator_id=current_user.id,
		)
		if err:
			flash(f"Could not add density check: {err}", "danger")
		else:
			flash("Density check added!", "success")
		return redirect(url_for("pre_expansion.view_pre_expansion_detail", pre_expansion_id=pre_exp.id))

	return render_template("pre_expansion/view_pre_expansion_detail.html", pre_exp=pre_exp, form=form)


@pre_expansion_bp.route("/pre_start_checklist", methods=["GET", "POST"])
@login_required
def pre_start_checklist():
	form = PreExpansionChecklistForm()
	if form.validate_on_submit():
		checks = {f"check{i}": bool(getattr(form, f"check{i}").data) for i in range(1, 14)}
		checklist, err = service.add_checklist(
			operator=current_user,
			ip_address=request.remote_addr,
			checks=checks,
			pre_expansion_id=None,
		)
		if err or not checklist:
			flash(f"Could not save checklist: {err}", "danger")
			return render_template("pre_expansion/pre_start_checklist.html", form=form)
		return redirect(url_for("pre_expansion.start_pre_expansion_session", checklist_id=checklist.id))

	return render_template("pre_expansion/pre_start_checklist.html", form=form)


@pre_expansion_bp.route("/dashboard")
@login_required
def dashboard():
	counts, err = service.get_dashboard_counts()
	if err:
		flash(f"Could not load dashboard stats: {err}", "danger")
	return render_template(
		"pre_expansion/dashboard.html",
		active_count=counts.active_count,
		completed_today=counts.completed_today,
		overdue_count=counts.overdue_count,
		total_completed=counts.total_completed,
	)


@pre_expansion_bp.route("/pastel_pending")
@login_required
def pastel_pending():
	candidates = (
		PreExpansion.query.filter_by(status="completed", is_pastel_captured=False)
		.order_by(PreExpansion.end_time.desc())
		.all()
	)
	sessions = [s for s in candidates if service.is_pastel_captureable(s)]
	return render_template("pre_expansion/pastel_pending.html", sessions=sessions)


@pre_expansion_bp.route("/pastel_capture/<int:pre_exp_id>", methods=["GET", "POST"])
@login_required
def pastel_capture(pre_exp_id: int):
	# This endpoint aggregates across blocks and moulding.
	# We keep it delegated to legacy until those domains are refactored too.
	from blueprints.pre_expansion.routes import pastel_capture as legacy_pastel_capture  # type: ignore

	return legacy_pastel_capture(pre_exp_id)


__all__ = ["pre_expansion_bp"]
