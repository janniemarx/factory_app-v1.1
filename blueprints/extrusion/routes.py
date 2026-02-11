# blueprints/extrusion/routes.py
from __future__ import annotations

import json
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from urllib.parse import urlparse

from models import db
from models.extrusion import (
    ExtrusionSession, ExtrudedProfile,
    MaterialType, UsageUnit, ReadingType, ExtrusionProfileSettings, Extruder
)
from models.operator import Operator

# -------- Forms (with safe fallbacks for any you might not have) --------
from .forms import (
    StartExtrusionSessionForm, AddRatePlanForm, MaterialUsageForm,
    CycleLogForm, PrestartChecklistForm, ProfileSettingsForm,
)
try:
    from .forms import ProfileForm  # expects: code, length_m, pieces_per_box
except Exception:
    from flask_wtf import FlaskForm
    from wtforms import StringField, FloatField, IntegerField, SubmitField
    from wtforms.validators import InputRequired, NumberRange, DataRequired
    class ProfileForm(FlaskForm):
        code = StringField("Code", validators=[DataRequired()])
        length_m = FloatField("Length (m)", validators=[InputRequired(), NumberRange(min=0.01)])
        pieces_per_box = IntegerField("Pieces per Box", validators=[InputRequired(), NumberRange(min=1)])
        submit = SubmitField("Save Profile")

try:
    from .forms import BoxesClosedForm  # optional in your build
except Exception:
    BoxesClosedForm = None  # noqa: N816

# -------- DB helpers --------
from .db_helpers import (
    get_extruders, get_profiles, list_sessions,
    start_extrusion_session, pause_session, resume_session, complete_session,
    add_rate_plan, log_material_usage, log_cycle, save_prestart_checklist,
    recompute_session_metrics,
)
try:
    from .db_helpers import ensure_seed_master_data  # optional
except Exception:
    ensure_seed_master_data = None  # noqa: N816


extrusion_bp = Blueprint("extrusion", __name__, template_folder='../../templates/extrusion')


DEFAULT_CHECKLIST = {"guards": "ok", "oil_level": "ok", "cooling": "ok"}


def _is_safe_next(url: str | None) -> bool:
    if not url:
        return False
    p = urlparse(url)
    # only allow same-site relative paths
    return (not p.netloc) and p.path.startswith('/')



# ---------- One-off seeding route (optional; protected) ----------
@extrusion_bp.route("/seed_master", methods=["POST"])
@login_required
def seed_master():
    if ensure_seed_master_data is None:
        flash("Seeding helper not available in this build.", "warning")
        return redirect(url_for("extrusion.profiles_list"))
    ok, err = ensure_seed_master_data()
    flash("Seeded master data." if ok else f"Seed error: {err}", "success" if ok else "danger")
    return redirect(url_for("extrusion.profiles_list"))


# ---------------- Sessions list ----------------
@extrusion_bp.route("/sessions")
@login_required
def sessions_list():
    status = request.args.get("status")
    extruder_id = request.args.get("extruder_id", type=int)
    profile_id = request.args.get("profile_id", type=int)

    sessions = list_sessions(status=status, extruder_id=extruder_id, profile_id=profile_id)
    return render_template(
        "extrusion/sessions.html",
        sessions=sessions,
        filters={"status": status, "extruder_id": extruder_id, "profile_id": profile_id},
    )


# ---------------- Start session (checklist REQUIRED) ----------------
@extrusion_bp.route("/start", methods=["GET", "POST"])
@login_required
def start_session():
    """
    Start an extrusion session.
    - Uses the LOGGED-IN user as operator (no dropdown).
    - Shows latest active recommended settings for the selected profile + machine.
    - Requires a pre-start checklist.
    """
    form = StartExtrusionSessionForm()

    # --- Populate dropdowns ---
    extruders = get_extruders(active_only=True) or []
    form.extruder_id.choices = [(e.id, e.code or f"Extruder {e.id}") for e in extruders]

    profiles = get_profiles() or []
    form.profile_id.choices = [
        (p.id, f"{p.code} ({float(p.length_m):.0f}m / {int(p.pieces_per_box)}/box)") for p in profiles
    ]

    # --- Resolve current selections (URL param -> form -> first available) ---
    selected_pid = (
        request.args.get("profile_id", type=int)
        or form.profile_id.data
        or (profiles[0].id if profiles else None)
    )
    form.profile_id.data = selected_pid

    selected_eid = (
        request.args.get("extruder_id", type=int)
        or form.extruder_id.data
        or (extruders[0].id if extruders else None)
    )
    form.extruder_id.data = selected_eid

    selected_profile = ExtrudedProfile.query.get(selected_pid) if selected_pid else None
    selected_extruder = Extruder.query.get(selected_eid) if selected_eid else None

    # Latest active settings for THIS profile + THIS machine
    latest_settings = (
        ExtrusionProfileSettings.query
        .filter_by(profile_id=selected_pid, extruder_id=selected_eid, is_active=True)
        .order_by(ExtrusionProfileSettings.effective_from.desc())
        .first()
    )

    if form.validate_on_submit():
        # Parse checklist (allow blank/invalid -> default)
        raw = (form.checklist_answers_json.data or "").strip()
        if not raw:
            checklist_answers = DEFAULT_CHECKLIST.copy()
        else:
            try:
                checklist_answers = json.loads(raw)
            except json.JSONDecodeError:
                # Graceful fallback instead of blocking start
                checklist_answers = DEFAULT_CHECKLIST.copy()
                flash("Checklist text wasn't valid JSON — using default checklist.", "warning")

        operator_id = getattr(current_user, "id", None)

        initial_rate_plan = {
            k: v for k, v in dict(
                rpm=getattr(form, "rpm", None) and form.rpm.data,
                gpps_kg_h=getattr(form, "gpps_kg_h", None) and form.gpps_kg_h.data,
                talc_kg_h=getattr(form, "talc_kg_h", None) and form.talc_kg_h.data,
                fire_retardant_kg_h=getattr(form, "fire_retardant_kg_h", None) and form.fire_retardant_kg_h.data,
                recycling_kg_h=getattr(form, "recycling_kg_h", None) and form.recycling_kg_h.data,
                co2_kg_h=getattr(form, "co2_kg_h", None) and form.co2_kg_h.data,
                alcohol_l_h=getattr(form, "alcohol_l_h", None) and form.alcohol_l_h.data,
            ).items() if v is not None
        }

        sess, err = start_extrusion_session(
            extruder_id=form.extruder_id.data,
            profile_id=form.profile_id.data,
            operator_id=operator_id,
            snapshot_setpoints=None,
            snapshot_heat_table=None,
            initial_rate_plan=initial_rate_plan or None,
            checklist_answers=checklist_answers,
            checklist_approved=form.checklist_approved.data,
            checklist_notes=form.checklist_notes.data,
            start_time=form.started_at.data or None,
        )
        if err:
            flash(f"Start error: {err}", "danger")
            return redirect(url_for(
                "extrusion.start_session",
                profile_id=form.profile_id.data,
                extruder_id=form.extruder_id.data
            ))

        flash("Extrusion session started.", "success")
        return redirect(url_for("extrusion.session_detail", session_id=sess.id))

    return render_template(
        "extrusion/start_session.html",
        form=form,
        selected_profile=selected_profile,
        latest_settings=latest_settings,
        current_user=current_user,
        selected_extruder_id=selected_eid,   # used by template for links
        selected_extruder=selected_extruder, # used by template to show only that machine’s fields/heat table
    )


# ---------------- Session detail (settings read-only, logs, rate plans) ----------------
@extrusion_bp.route("/session/<int:session_id>", methods=["GET", "POST"])
@login_required
def session_detail(session_id: int):
    session = ExtrusionSession.query.get_or_404(session_id)

    # Forms (no rate plan editing on this page)
    usage_form = MaterialUsageForm()
    cycle_form = CycleLogForm()          # used only for CSRF/hidden_tag in the modal
    checklist_form = PrestartChecklistForm()

    if request.method == "POST":
        # Pause
        if "pause" in request.form and session.status == "running" and not session.is_paused:
            ok, err = pause_session(session)
            flash("Session paused." if ok else f"Pause error: {err}", "warning" if ok else "danger")
            return redirect(url_for("extrusion.session_detail", session_id=session.id))

        # Resume
        if "resume" in request.form and session.status == "running" and session.is_paused:
            ok, err = resume_session(session)
            flash("Session resumed." if ok else f"Resume error: {err}", "success" if ok else "danger")
            return redirect(url_for("extrusion.session_detail", session_id=session.id))

        # Complete — capture final cuts (pieces) as a DELTA cycle log, then close session
        if "complete" in request.form and session.status == "running":
            cuts = request.form.get("cuts", type=int)
            if cuts is None or cuts < 0:
                flash("Please enter how many cuts (pieces) were made.", "danger")
                return redirect(url_for("extrusion.session_detail", session_id=session.id))

            ok_log, err_log = log_cycle(
                session_id=session.id,
                reading_value=cuts,
                reading_type=ReadingType.DELTA,
                note="Final cuts logged at completion",
            )
            if not ok_log:
                flash(f"Could not save final cuts: {err_log}", "danger")
                return redirect(url_for("extrusion.session_detail", session_id=session.id))

            ok, err = complete_session(session)
            flash("Session completed." if ok else f"Complete error: {err}", "success" if ok else "danger")
            return redirect(url_for("extrusion.session_detail", session_id=session.id))

        # Log material usage
        if "log_usage" in request.form and usage_form.validate_on_submit():
            ok, err = log_material_usage(
                session_id=session.id,
                material=usage_form.material.data,
                unit=usage_form.unit.data,
                quantity=usage_form.quantity.data,
                note=usage_form.note.data,
            )
            flash("Usage logged." if ok else f"Usage error: {err}", "info" if ok else "danger")
            return redirect(url_for("extrusion.session_detail", session_id=session.id))

        # Save checklist (update)
        if "save_checklist" in request.form and checklist_form.validate_on_submit():
            try:
                answers = json.loads(checklist_form.answers_json.data or "{}")
            except json.JSONDecodeError as je:
                flash(f"Checklist JSON error: {je}", "danger")
                return redirect(url_for("extrusion.session_detail", session_id=session.id))

            ok, err = save_prestart_checklist(
                session_id=session.id,
                completed_by_id=getattr(current_user, "id", None),
                answers=answers,
                approved=checklist_form.approved.data,
                notes=checklist_form.notes.data,
            )
            flash("Checklist saved." if ok else f"Checklist error: {err}", "success" if ok else "danger")
            return redirect(url_for("extrusion.session_detail", session_id=session.id))

        # Validation fallthrough
        if "log_usage" in request.form and not usage_form.validate():
            flash("Please correct the material usage fields.", "danger")
        elif "save_checklist" in request.form and not checklist_form.validate():
            flash("Please correct the checklist fields.", "danger")
        return redirect(url_for("extrusion.session_detail", session_id=session.id))

    # Recompute metrics for display (hours, expected vs actual, pieces, boxes)
    _, _, metrics = recompute_session_metrics(session)

    # Latest active settings for read-only modal (for this profile + machine)
    latest_settings = (
        ExtrusionProfileSettings.query
        .filter_by(
            profile_id=session.profile_id,
            extruder_id=session.extruder_id,
            is_active=True
        )
        .order_by(ExtrusionProfileSettings.effective_from.desc())
        .first()
    )

    extruder_label = session.extruder.code or f"Extruder {session.extruder_id}"
    profile_label = session.profile.code if session.profile else str(session.profile_id)
    settings_manage_url = url_for(
        "extrusion.profile_settings_manage",
        profile_id=session.profile_id,
        extruder_id=session.extruder_id,
        next=url_for("extrusion.session_detail", session_id=session.id)  # return here after save
    )

    prestart_checklist = session.checklist

    return render_template(
        "extrusion/session_detail.html",
        session=session,
        extruder_label=extruder_label,
        profile_label=profile_label,
        metrics=metrics,
        usage_form=usage_form,
        cycle_form=cycle_form,
        checklist_form=checklist_form,
        MaterialType=MaterialType, UsageUnit=UsageUnit, ReadingType=ReadingType,
        latest_settings=latest_settings,
        settings_manage_url=settings_manage_url,
        prestart_checklist=prestart_checklist,
    )


# ---------------- Profiles list ----------------
@extrusion_bp.route("/profiles")
@login_required
def profiles_list():
    profiles = get_profiles()
    return render_template("extrusion/profiles.html", profiles=profiles)


# ---------------- Add Profile ----------------
@extrusion_bp.route("/profiles/new", methods=["GET", "POST"])
@login_required
def profile_new():
    form = ProfileForm()
    if form.validate_on_submit():
        p = ExtrudedProfile(
            code=form.code.data.strip(),
            length_m=form.length_m.data,
            pieces_per_box=form.pieces_per_box.data,
        )
        db.session.add(p)
        db.session.commit()
        flash("Profile created.", "success")
        return redirect(url_for("extrusion.profiles_list"))
    return render_template("extrusion/profile_edit.html", form=form, mode="new")


# ---------------- Edit Profile ----------------
@extrusion_bp.route("/profiles/<int:profile_id>/edit", methods=["GET", "POST"])
@login_required
def profile_edit(profile_id: int):
    p = ExtrudedProfile.query.get_or_404(profile_id)
    form = ProfileForm(obj=p)
    if form.validate_on_submit():
        p.code = form.code.data.strip()
        p.length_m = form.length_m.data
        p.pieces_per_box = form.pieces_per_box.data
        db.session.commit()
        flash("Profile updated.", "success")
        return redirect(url_for("extrusion.profiles_list"))
    return render_template("extrusion/profile_edit.html", form=form, mode="edit", profile=p)


# ---------------- Settings manage (SINGLE ACTIVE ROW per profile) ----------------
# ---------------- Settings manage: single current settings per profile (UPSERT) ----------------
@extrusion_bp.route("/profiles/<int:profile_id>/settings", methods=["GET", "POST"])
@login_required
def profile_settings_manage(profile_id: int):
    """
    Manage a profile's settings for a specific machine.

    • If a `next` query param is supplied (e.g. when opened from a session detail page),
      redirect back to it after saving. Otherwise fall back to the profiles list.

    • Preserves `next` on error redirects.
    """
    from urllib.parse import urlparse

    def _is_safe_next(u: str | None) -> bool:
        if not u:
            return False
        p = urlparse(u)
        # allow only same-origin relative paths
        return (not p.netloc) and p.path.startswith('/')

    # Carry `next` across GET/POST
    next_url = request.args.get("next") or request.form.get("next")

    profile = ExtrudedProfile.query.get_or_404(profile_id)
    form = ProfileSettingsForm()

    # choices for machine
    extruders = get_extruders(active_only=True)
    form.extruder_id.choices = [(e.id, e.code or f"Extruder {e.id}") for e in extruders]

    # current selection
    selected_eid = (
        request.args.get("extruder_id", type=int)
        or form.extruder_id.data
        or (extruders[0].id if extruders else None)
    )
    form.extruder_id.data = selected_eid

    # load existing settings (single row policy)
    current = (
        ExtrusionProfileSettings.query
        .filter_by(profile_id=profile.id, extruder_id=selected_eid)
        .order_by(ExtrusionProfileSettings.effective_from.desc())
        .first()
    )

    if request.method == "GET" and current:
        # prefill
        form.rpm.data = current.rpm
        form.gpps_kg_h.data = current.gpps_kg_h
        form.talc_kg_h.data = current.talc_kg_h
        form.fire_retardant_kg_h.data = current.fire_retardant_kg_h
        form.recycling_kg_h.data = current.recycling_kg_h
        form.co2_kg_h.data = current.co2_kg_h
        form.alcohol_l_h.data = current.alcohol_l_h

        form.extruder_hz.data = current.extruder_hz
        form.co2_hz.data = current.co2_hz
        form.alcohol_hz.data = current.alcohol_hz
        form.oil_hz.data = current.oil_hz

        form.heat_table_json.data = json.dumps(current.heat_table or {}, indent=2)
        form.notes.data = current.notes or ""

    if form.validate_on_submit():
        # Parse heat table JSON safely; don't clobber existing data with {}
        raw_ht = (form.heat_table_json.data or "").strip()
        heat_table = None
        if raw_ht:
            try:
                heat_table = json.loads(raw_ht)
            except json.JSONDecodeError as je:
                flash(f"Heat table JSON error: {je}", "danger")
                return redirect(url_for(
                    "extrusion.profile_settings_manage",
                    profile_id=profile.id,
                    extruder_id=form.extruder_id.data,
                    next=next_url  # preserve where we came from
                ))

        if current:
            # UPDATE existing
            current.rpm = form.rpm.data
            current.gpps_kg_h = form.gpps_kg_h.data
            current.talc_kg_h = form.talc_kg_h.data
            current.fire_retardant_kg_h = form.fire_retardant_kg_h.data
            current.recycling_kg_h = form.recycling_kg_h.data
            current.co2_kg_h = form.co2_kg_h.data
            current.alcohol_l_h = form.alcohol_l_h.data

            current.extruder_hz = form.extruder_hz.data
            current.co2_hz = form.co2_hz.data
            current.alcohol_hz = form.alcohol_hz.data
            current.oil_hz = form.oil_hz.data

            if heat_table is not None:          # only replace if client actually sent JSON
                current.heat_table = heat_table
            current.notes = form.notes.data
        else:
            # INSERT new for (profile, extruder)
            s = ExtrusionProfileSettings(
                profile_id=profile.id,
                extruder_id=form.extruder_id.data,
                rpm=form.rpm.data,
                gpps_kg_h=form.gpps_kg_h.data,
                talc_kg_h=form.talc_kg_h.data,
                fire_retardant_kg_h=form.fire_retardant_kg_h.data,
                recycling_kg_h=form.recycling_kg_h.data,
                co2_kg_h=form.co2_kg_h.data,
                alcohol_l_h=form.alcohol_l_h.data,
                extruder_hz=form.extruder_hz.data,
                co2_hz=form.co2_hz.data,
                alcohol_hz=form.alcohol_hz.data,
                oil_hz=form.oil_hz.data,
                heat_table=(heat_table or {}),   # use parsed JSON if present
                notes=form.notes.data,
                is_active=True,
                created_by_id=getattr(current_user, "id", None),
            )
            db.session.add(s)

        db.session.commit()
        flash("Settings saved.", "success")

        # Redirect back to `next` (e.g., session detail) if supplied and safe; else profiles list
        if _is_safe_next(next_url):
            return redirect(next_url)
        return redirect(url_for("extrusion.profiles_list"))

    return render_template(
        "extrusion/profile_settings.html",
        profile=profile,
        form=form,
        selected_extruder_id=selected_eid,
        next=next_url,  # available to the template if you want to persist it in links/forms
    )



# ---------------- Settings edit (kept for direct /edit links; also returns to profiles) ----------------
@extrusion_bp.route("/profiles/<int:profile_id>/settings/<int:settings_id>/edit", methods=["GET", "POST"])
@login_required
def profile_settings_edit(profile_id: int, settings_id: int):
    """Redirect legacy edit to the new Manage UI for the row's machine."""
    s = (ExtrusionProfileSettings.query
         .filter_by(id=settings_id, profile_id=profile_id)
         .first_or_404())
    return redirect(url_for(
        "extrusion.profile_settings_manage",
        profile_id=profile_id,
        extruder_id=s.extruder_id
    ))


@extrusion_bp.route("/profiles/<int:profile_id>/settings/<int:settings_id>/deactivate", methods=["POST"])
@login_required
def profile_settings_deactivate(profile_id: int, settings_id: int):
    s = ExtrusionProfileSettings.query.filter_by(id=settings_id, profile_id=profile_id).first_or_404()
    s.is_active = False
    db.session.commit()
    flash("Settings deactivated.", "warning")
    return redirect(url_for("extrusion.profile_settings_manage", profile_id=profile_id))


# ---------------- Convenience shortcuts (for index tiles) ----------------
@extrusion_bp.route("/sessions/active")
@login_required
def active_sessions():
    return redirect(url_for("extrusion.sessions_list", status="running"))

@extrusion_bp.route("/sessions/completed")
@login_required
def completed_sessions():
    return redirect(url_for("extrusion.sessions_list", status="completed"))

@extrusion_bp.route("/settings")
@login_required
def settings_list():
    return redirect(url_for("extrusion.profiles_list"))

@extrusion_bp.route("/settings/new")
@login_required
def settings_new():
    flash("Select a profile to create new settings.", "info")
    return redirect(url_for("extrusion.profiles_list"))

@extrusion_bp.get("/session/<int:session_id>/settings_snippet")
@login_required
def session_settings_snippet(session_id: int):
    session = ExtrusionSession.query.get_or_404(session_id)

    latest_settings = (
        ExtrusionProfileSettings.query
        .filter_by(profile_id=session.profile_id,
                   extruder_id=session.extruder_id,
                   is_active=True)
        .order_by(ExtrusionProfileSettings.effective_from.desc())
        .first()
    )

    # when opened from session detail, send users back there after saving
    next_url = url_for("extrusion.session_detail", session_id=session.id)
    settings_manage_url = url_for(
        "extrusion.profile_settings_manage",
        profile_id=session.profile_id,
        extruder_id=session.extruder_id,
        next=next_url,
    )

    return render_template(
        "extrusion/_settings_modal_body.html",
        latest_settings=latest_settings,
        settings_manage_url=settings_manage_url,
    )