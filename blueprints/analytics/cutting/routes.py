from flask import Blueprint, render_template, request, redirect, url_for, abort
from flask_login import login_required
from datetime import datetime, timedelta

from .forms import WireCuttingSessionFilterForm
from .helpers import get_cutting_analytics, get_machines, get_operators

# NEW: extra models needed for the details page
from models.block import Block
from models.cutting import WireCuttingSession, Profile
from models.pre_expansion import PreExpansion
from models.production import CuttingProductionRecord
from models.boxing import BoxingSession, BoxingQualityControl
from models.qc import QualityControl  # adjust module path if different
from models.operator import Operator

cutting_analytics_bp = Blueprint(
    "cutting_analytics",
    __name__,
    template_folder="../../templates/analytics/cutting"
)


def _safe_round(v, n=2):
    try:
        return round(float(v), n)
    except Exception:
        return 0.0


def _estimate_cutting_waste_m(session, profile):
    """
    Cutting waste (meters).

    Priority:
      A) Business rule (preferred): waste = expected - produced
         expected = profile.cornices_per_block * length_per_cornice
         produced = (produced_length_m) or (profiles_cut * length_per_cornice)

      B) If A cannot be computed, fall back to explicit wastage_m

      C) If still missing, derive from model wastage_percent:
         W = P * (w% / (1 - w%))
    """
    length_per = (profile.length_per_cornice if profile else 2.5) or 2.5

    # --- A) Business rule ---
    if profile and getattr(profile, "cornices_per_block", None):
        produced_m = (
            float(session.produced_length_m)
            if session.produced_length_m is not None
            else float(session.profiles_cut or 0) * float(length_per)
        )
        expected_m = float(profile.cornices_per_block) * float(length_per)
        waste_m = max(expected_m - produced_m, 0.0)
        return _safe_round(waste_m)

    # --- B) DB meters ---
    if session.wastage_m is not None:
        return _safe_round(session.wastage_m)

    # --- C) Invert the % (only if we know produced) ---
    produced_m = (
        float(session.produced_length_m)
        if session.produced_length_m is not None
        else float(session.profiles_cut or 0) * float(length_per)
    )
    if produced_m <= 0:
        return 0.0
    w_frac = (getattr(session, "wastage_percent", 0.0) or 0.0) / 100.0
    if w_frac <= 0.0 or w_frac >= 0.999999:
        return 0.0
    return _safe_round(produced_m * (w_frac / (1.0 - w_frac)))


def _parse_positive_int(value):
    try:
        i = int(value)
        return i if i > 0 else None
    except (TypeError, ValueError):
        return None


def _period_range(period: str):
    now = datetime.now()
    period = (period or "day").lower()
    if period == "month":
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end = start.replace(year=start.year + 1, month=1) if start.month == 12 else start.replace(month=start.month + 1)
    elif period == "year":
        start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        end = start.replace(year=start.year + 1)
    else:  # day
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
    return (start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))


@cutting_analytics_bp.route("/analytics", methods=["GET", "POST"])
@login_required
def dashboard():
    machines = get_machines()
    operators = get_operators()
    profiles = Profile.query.order_by(Profile.code).all()

    form = WireCuttingSessionFilterForm()
    form.machine_id.choices = [(0, '--All Machines--')] + [(m.id, m.name) for m in machines]
    form.operator_id.choices = [(0, '--All Operators--')] + [(o.id, o.full_name or o.username) for o in operators]
    form.profile_code.choices = [('', '--All Profiles--')] + [(p.code, p.code) for p in profiles]

    period = (request.args.get("period") or "day").lower()
    if period not in {"day", "month", "year"}:
        period = "day"
    dash_from, dash_to = _period_range(period)

    if form.validate_on_submit():
        machine_id = form.machine_id.data or 0
        operator_id = form.operator_id.data or 0
        profile_code = form.profile_code.data or ""
        date_from = (request.form.get("date_from") or "").strip()
        date_to = (request.form.get("date_to") or "").strip()

        has_filters_submitted = (
            (machine_id and int(machine_id) != 0) or
            (operator_id and int(operator_id) != 0) or
            (profile_code != "") or
            (date_from != "") or
            (date_to != "")
        )

        args = dict(
            period=period,
            machine_id=machine_id,
            operator_id=operator_id,
            profile_code=profile_code,
            date_from=date_from,
            date_to=date_to,
        )
        if not has_filters_submitted:
            args["open_filters"] = 1
            args["show_all"] = 1
        return redirect(url_for("cutting_analytics.dashboard", **args))

    q_machine_id = _parse_positive_int(request.args.get("machine_id"))
    q_operator_id = _parse_positive_int(request.args.get("operator_id"))
    q_profile_code = request.args.get("profile_code") or None
    date_from = request.args.get("date_from") or None
    date_to = request.args.get("date_to") or None
    show_all = (request.args.get("show_all") == "1")
    open_filters = (request.args.get("open_filters") == "1")

    form.machine_id.data = q_machine_id or 0
    form.operator_id.data = q_operator_id or 0
    form.profile_code.data = q_profile_code or ""

    analytics_global = get_cutting_analytics(
        machine_id=None, operator_id=None, profile_code=None,
        date_from=dash_from, date_to=dash_to
    )
    analytics_filtered = get_cutting_analytics(
        machine_id=q_machine_id,
        operator_id=q_operator_id,
        profile_code=q_profile_code,
        date_from=date_from,
        date_to=date_to,
    )

    return render_template(
        "analytics/cutting/dashboard.html",
        form=form,
        period=period,
        date_from=date_from,
        date_to=date_to,
        analytics_global=analytics_global,
        analytics_filtered=analytics_filtered,
        open_filters=open_filters,
        show_all=show_all,
        now=datetime.now()
    )


# ---------- NEW: Session detail route ----------

def _find_cutting_record_for_session(session: WireCuttingSession):
    """
    Heuristics to locate the CuttingProductionRecord tied to this session.
    1) session_id match (if your schema has it)
    2) block_id match (fallback)
    """
    cpr = None
    try:
        cpr = CuttingProductionRecord.query.filter_by(session_id=session.id).first()
    except Exception:
        cpr = None
    if not cpr and session.block_id:
        try:
            cpr = CuttingProductionRecord.query.filter_by(block_id=session.block_id).order_by(CuttingProductionRecord.id.desc()).first()
        except Exception:
            cpr = None
    return cpr

@cutting_analytics_bp.route("/analytics/session/<int:session_id>", methods=["GET"])
@login_required
def session_detail(session_id: int):
    s = WireCuttingSession.query.get_or_404(session_id)

    block = s.block
    profile = s.profile
    pre = block.pre_expansion if block else None

    # Curing info
    created_at = block.created_at if block else None
    curing_end = None
    if block:
        curing_end = block.curing_end
        if not curing_end and block.pre_expansion:
            if block.pre_expansion.density == 18:
                curing_end = block.created_at + timedelta(days=3)
            elif block.pre_expansion.density == 23:
                curing_end = block.created_at + timedelta(days=10)
            else:
                curing_end = block.created_at
    curing_duration = (curing_end - created_at) if (created_at and curing_end) else None

    # Produced meters
    length_per_cornice = (profile.length_per_cornice if profile else 2.5) or 2.5
    if s.produced_length_m is not None:
        produced_m_calc = float(s.produced_length_m)
    else:
        produced_m_calc = float(s.profiles_cut or 0) * float(length_per_cornice)

    # --- NEW: lengths (pieces) view ---
    expected_lengths = profile.cornices_per_block if (profile and getattr(profile, "cornices_per_block", None)) else None
    produced_lengths = s.profiles_cut if s.profiles_cut is not None else None

    # Expected meters, waste %, damaged pieces (BUSINESS RULE)
    expected_m = None
    waste_pct_rule = None
    if expected_lengths is not None:
        expected_m = float(expected_lengths) * float(length_per_cornice)
        waste_m_rule = max(expected_m - produced_m_calc, 0.0)
        waste_pct_rule = round(100.0 * waste_m_rule / expected_m, 2) if expected_m > 0 else None
    else:
        # fall back to estimating waste meters from session data
        waste_m_rule = _estimate_cutting_waste_m(s, profile)

    # Use rule-based waste (meters) for the card
    cutting_damage_m = _safe_round(waste_m_rule)

    # Derive damage in lengths:
    damage_lengths_rule = None
    if (expected_lengths is not None) and (produced_lengths is not None):
        damage_lengths_rule = max(int(expected_lengths) - int(produced_lengths), 0)

    damage_lengths_from_m = None
    if length_per_cornice:
        damage_lengths_from_m = int(round((cutting_damage_m or 0.0) / float(length_per_cornice)))

    cutting_damage_lengths = damage_lengths_rule if damage_lengths_rule is not None else damage_lengths_from_m

    # Back-compat alias (if your template still references this name)
    damaged_pieces = cutting_damage_lengths

    # Boxing info / damage
    cpr = _find_cutting_record_for_session(s)
    qc = QualityControl.query.filter_by(cutting_production_id=cpr.id).first() if cpr else None
    qc_scores, qc_avg = {}, None
    if qc:
        keys = ["rated_areo_effect", "rated_eps_binding", "rated_wetspots", "rated_dryness", "rated_lines"]
        vals = [getattr(qc, k) for k in keys if getattr(qc, k, None) is not None]
        if vals:
            qc_avg = round(sum(map(float, vals)) / len(vals), 2)
        qc_scores = {
            k.replace("rated_", "").replace("_", " ").title(): getattr(qc, k)
            for k in keys if getattr(qc, k, None) is not None
        }

    boxing_sessions = BoxingSession.query.filter_by(cutting_production_id=cpr.id).all() if cpr else []
    status_rank = {"stock_ready": 5, "completed": 4, "pending_qc": 3, "active": 2, "paused": 1}
    boxing_status = max((bs.status for bs in boxing_sessions), key=lambda st: status_rank.get(st, 0)) if boxing_sessions else None

    boxing_damage_cornices = 0
    cornices_per_box = profile.cornices_per_box if profile else 4
    for bs in boxing_sessions:
        if bs.qc:
            total_cornices = (bs.boxes_packed or 0) * cornices_per_box + (bs.leftovers or 0)
            good = bs.qc.good_cornices_count or 0
            dmg = max(total_cornices - good, 0)
            boxing_damage_cornices += dmg
    boxing_damage_m = _safe_round(boxing_damage_cornices * float(length_per_cornice))

    # Density checks summary
    density_checks = []
    if pre and getattr(pre, "density_checks", None):
        for d in sorted(pre.density_checks, key=lambda x: x.check_time):
            density_checks.append({
                "time": d.check_time,
                "measured_density": d.measured_density,
                "measured_weight": d.measured_weight,
                "operator": d.operator.full_name if getattr(d, "operator", None) else None
            })

    return render_template(
        "analytics/cutting/session_detail.html",
        session=s,
        block=block,
        profile=profile,
        pre=pre,
        created_at=created_at,
        curing_end=curing_end,
        curing_duration=curing_duration,

        # meters
        produced_m_calc=_safe_round(produced_m_calc),
        expected_m=_safe_round(expected_m) if expected_m is not None else None,
        cutting_damage_m=_safe_round(cutting_damage_m),

        # lengths (pieces)
        expected_lengths=expected_lengths,
        produced_lengths=produced_lengths,
        cutting_damage_lengths=cutting_damage_lengths,
        damaged_pieces=damaged_pieces,  # alias for older template bits

        waste_pct_rule=waste_pct_rule,
        boxing_status=boxing_status,
        boxing_damage_m=_safe_round(boxing_damage_m),
        boxing_sessions=boxing_sessions,
        qc=qc,
        qc_avg=qc_avg,
        qc_scores=qc_scores,
        density_checks=density_checks,
    )
