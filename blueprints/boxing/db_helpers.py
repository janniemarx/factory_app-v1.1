# blueprints/boxing/db_helpers.py

from datetime import datetime
from sqlalchemy.exc import SQLAlchemyError

from models import db
from models.production import CuttingProductionRecord
from models.qc import QualityControl
from models.boxing import BoxingSession, BoxingQualityControl, LeftoverCornice
from models.extrusion import ExtrusionSession  # NEW

# ----------------------- utils -----------------------

def safe_commit():
    try:
        db.session.commit()
        return True, None
    except SQLAlchemyError as e:
        db.session.rollback()
        return False, str(e)

# ----------------------- ready-to-box queries -----------------------

# blueprints/boxing/db_helpers.py

def get_ready_for_boxing_cutting():
    try:
        ready_records = (
            CuttingProductionRecord.query
            .join(QualityControl)
            .filter(QualityControl.is_boxing_ready.is_(True))
            .filter(CuttingProductionRecord.is_boxable.is_(True))
            .outerjoin(
                BoxingSession,
                (BoxingSession.source_type == 'cutting') &
                (BoxingSession.cutting_production_id == CuttingProductionRecord.id) &
                (BoxingSession.status.in_(['active', 'paused', 'pending_qc']))   # <-- only open sessions block
            )
            .filter(BoxingSession.id.is_(None))
            .all()
        )
        return ready_records, None
    except SQLAlchemyError as e:
        return [], str(e)

def get_ready_for_boxing_extrusion():
    try:
        ready_sessions = (
            ExtrusionSession.query
            .filter(ExtrusionSession.status == 'completed')
            .outerjoin(
                BoxingSession,
                (BoxingSession.source_type == 'extrusion') &
                (BoxingSession.extrusion_session_id == ExtrusionSession.id) &
                (BoxingSession.status.in_(['active', 'paused', 'pending_qc']))   # <-- only open sessions block
            )
            .filter(BoxingSession.id.is_(None))
            .order_by(ExtrusionSession.started_at.desc())
            .all()
        )
        return ready_sessions, None
    except SQLAlchemyError as e:
        return [], str(e)

def get_ready_for_boxing_sources():
    items = []
    cutting, err1 = get_ready_for_boxing_cutting()
    extrusion, err2 = get_ready_for_boxing_extrusion()

    for r in cutting:
        qty = qty_ready_to_box(r)
        label = f"{r.profile_code} | Block {getattr(r, 'block_number', '-') } | {qty} to box"
        items.append({
            "key": f"cut:{r.id}",                 # <-- add key
            "source": "cutting",
            "id": r.id,
            "profile_code": r.profile_code,
            "label": label,
            "qty_to_box": qty,
        })

    for s in extrusion:
        code = s.profile.code if s.profile else "-"
        qty = qty_ready_to_box(s)
        label = f"{code} | Extrusion #{s.id} | {qty} to box"
        items.append({
            "key": f"ext:{s.id}",                 # <-- add key
            "source": "extrusion",
            "id": s.id,
            "profile_code": code,
            "label": label,
            "qty_to_box": qty,
        })

    return items, (err1 or err2)

# Backwards-compatible alias (legacy callers will still only see cutting)
def get_ready_for_boxing():
    return get_ready_for_boxing_cutting()

# ----------------------- lifecycle -----------------------

def create_boxing_session(*, operator_id, cutting_production_id=None, extrusion_session_id=None, cycle_start=0):
    """
    Create a boxing session from either a CuttingProductionRecord or an ExtrusionSession.
    Exactly one of cutting_production_id / extrusion_session_id must be provided.
    """
    try:
        provided = [x is not None for x in (cutting_production_id, extrusion_session_id)]
        if sum(provided) != 1:
            return None, "Provide exactly one of cutting_production_id or extrusion_session_id."

        source_type = 'cutting' if cutting_production_id is not None else 'extrusion'

        session = BoxingSession(
            source_type=source_type,
            cutting_production_id=cutting_production_id,
            extrusion_session_id=extrusion_session_id,
            operator_id=operator_id,
            start_time=datetime.utcnow(),
            cycle_start=cycle_start or 0,
            status='active'
        )
        db.session.add(session)
        success, error = safe_commit()
        return (session if success else None), error
    except Exception as e:
        db.session.rollback()
        return None, str(e)


def get_boxing_session(session_id):
    return BoxingSession.query.get(session_id)


def pause_boxing_session(session):
    if not session.is_paused:
        session.is_paused = True
        session.pause_start = datetime.utcnow()
        session.status = 'paused'
        return safe_commit()
    return True, None


def resume_boxing_session(session):
    if session.is_paused:
        pause_duration = (datetime.utcnow() - session.pause_start).total_seconds()
        session.total_paused_seconds += int(pause_duration)
        session.is_paused = False
        session.pause_start = None
        session.status = 'active'
        return safe_commit()
    return True, None

# ----------------------- QC / finish -----------------------

def save_boxing_qc(session, qc_form, operator_id):
    """
    Save QC for a boxing session and compute 'boxing waste' vs upstream good quantity:
      - Cutting: use QualityControl.good_cornices_count (fallback: produced - wastage)
      - Extrusion: use ExtrusionSession.pieces_produced
    Also writes back durations/damage to CuttingProductionRecord. For ExtrusionSession,
    updates 'actual_boxes_boxed' to support damage estimation there.
    """
    from models.cutting import Profile

    # Establish upstream context
    cutting_rec: CuttingProductionRecord | None = session.cutting_production if session.source_type == 'cutting' else None
    extru_sess: ExtrusionSession | None = session.extrusion_session if session.source_type == 'extrusion' else None

    # Cornices/box
    if session.source_type == 'cutting' and cutting_rec:
        profile = Profile.query.filter_by(code=cutting_rec.profile_code).first()
        cornices_per_box = profile.cornices_per_box if profile else 4
        upstream_good = (cutting_rec.quality_control.good_cornices_count
                         if cutting_rec.quality_control else
                         max((cutting_rec.cornices_produced or 0) - (cutting_rec.wastage or 0), 0))
        profile_code_for_leftovers = cutting_rec.profile_code
    else:
        # extrusion
        prof = extru_sess.profile if (extru_sess and extru_sess.profile) else None
        cornices_per_box = (prof.pieces_per_box if prof else 4)
        upstream_good = int(extru_sess.pieces_produced or 0) if extru_sess else 0
        profile_code_for_leftovers = prof.code if prof else None

    boxes_packed = int(session.boxes_packed or 0)
    leftovers = int(session.leftovers or 0)
    boxed_total = boxes_packed * int(cornices_per_box) + leftovers

    try:
        # Save a QC row (we keep good_cornices_count as boxed_total = stock-ready after boxing)
        qc = BoxingQualityControl(
            boxing_session_id=session.id,
            qc_operator_id=operator_id,
            timestamp=datetime.utcnow(),
            boxes_checked=qc_form.boxes_checked.data,
            good_cornices_count=boxed_total,
            notes=qc_form.notes.data,
            actions_taken=qc_form.actions_taken.data,
            is_stock_ready=True,
        )
        db.session.add(qc)

        # Mark session status
        session.status = 'stock_ready'

        # Compute 'boxing waste' (shortfall vs what we received)
        boxing_waste = max(int(upstream_good) - int(boxed_total), 0)

        # Write back to upstream entities
        if cutting_rec:
            cutting_rec.waste_boxing = boxing_waste
            cutting_rec.total_cornices_damaged = (cutting_rec.total_cornices_damaged or 0) + boxing_waste

            # For non-PR16, keep status as passed
            if getattr(cutting_rec, 'profile_code', None) != 'PR16':
                cutting_rec.qc_status = 'passed'

            if not cutting_rec.date_boxed:
                cutting_rec.date_boxed = session.end_time

            # durations (same logic as before)
            pre = cutting_rec.block.pre_expansion if getattr(cutting_rec, 'block', None) else None
            if pre and pre.start_time and pre.end_time:
                cutting_rec.pre_expansion_time_min = int((pre.end_time - pre.start_time).total_seconds() / 60)

            bsess = cutting_rec.block.block_session if getattr(cutting_rec, 'block', None) else None
            if bsess and bsess.started_at and bsess.ended_at:
                cutting_rec.block_making_time_min = int((bsess.ended_at - bsess.started_at).total_seconds() / 60)

            if getattr(cutting_rec, 'actual_production_time_min', None) is not None:
                cutting_rec.cutting_time_min = int(cutting_rec.actual_production_time_min)

            if cutting_rec.boxing_time_min is None and session.start_time and session.end_time:
                paused_sec = session.total_paused_seconds or 0
                raw_min = (session.end_time - session.start_time).total_seconds() / 60
                cutting_rec.boxing_time_min = int(max(raw_min - (paused_sec / 60.0), 0))

            if session.end_time and qc.timestamp:
                cutting_rec.qc_time_min = int(max((qc.timestamp - session.end_time).total_seconds() / 60, 0))

            parts = [
                cutting_rec.pre_expansion_time_min,
                cutting_rec.block_making_time_min,
                cutting_rec.cutting_time_min if hasattr(cutting_rec, 'cutting_time_min') else None,
                cutting_rec.boxing_time_min,
                cutting_rec.qc_time_min
            ]
            cutting_rec.total_production_time_min = sum(p for p in parts if isinstance(p, (int, float)))

        if extru_sess:
            # Persist 'boxes actually boxed' back to the extrusion session
            extru_sess.actual_boxes_boxed = int(session.boxes_packed or 0)
            # (Damage for extrusion can be derived as pieces_produced - (actual_boxes_boxed * pieces_per_box);
            #  leftovers are tracked separately via LeftoverCornice.)

        # Persist and return
        success, error = safe_commit()
        return (qc if success else None), error
    except Exception as e:
        db.session.rollback()
        return None, str(e)


def get_all_boxing_sessions():
    try:
        return BoxingSession.query.order_by(BoxingSession.start_time.desc()).all(), None
    except SQLAlchemyError as e:
        return [], str(e)


def get_sessions_ready_for_stock():
    try:
        return (BoxingSession.query
                .filter_by(status='stock_ready')
                .order_by(BoxingSession.end_time.desc())
                .all(), None)
    except SQLAlchemyError as e:
        return [], str(e)


def get_unused_leftovers(profile_code=None):
    """Return all unused leftovers, optionally filtered by profile_code."""
    query = LeftoverCornice.query.filter_by(used=False)
    if profile_code:
        query = query.filter_by(profile_code=profile_code)
    return query.order_by(LeftoverCornice.created_at.asc()).all()


def finish_boxing_session(session, finish_form, record, boxing_fields_cb=None):
    """
    Finish a boxing session (both sources). For 'record', legacy callers pass the CuttingProductionRecord;
    for extrusion boxing, we ignore that arg and derive the upstream session from `session.extrusion_session`.
    """
    try:
        # Persist end stats
        session.boxes_packed = finish_form.boxes_packed.data
        session.leftovers = finish_form.leftovers.data or 0
        session.cycle_end = finish_form.cycle_end.data
        session.end_time = datetime.utcnow()
        session.status = 'pending_qc'

        # Analytics on session
        session.producing_cycles = (session.boxes_packed or 0) / 4 if session.boxes_packed is not None else 0
        if session.cycle_start is not None and session.cycle_end is not None:
            session.actual_producing_cycles = (session.cycle_end - session.cycle_start) - (session.producing_cycles or 0)
        else:
            session.actual_producing_cycles = None
        if session.end_time and session.start_time and session.boxes_packed:
            total_min = (session.end_time - session.start_time).total_seconds() / 60
            session.time_per_box_min = round(total_min / max(session.boxes_packed, 1), 2)
        else:
            session.time_per_box_min = None

        # Leftover record
        profile_code = None
        if session.source_type == 'cutting' and session.cutting_production:
            profile_code = session.cutting_production.profile_code
        elif session.source_type == 'extrusion' and session.extrusion_session and session.extrusion_session.profile:
            profile_code = session.extrusion_session.profile.code

        if session.leftovers > 0 and profile_code:
            db.session.add(LeftoverCornice(
                profile_code=profile_code,
                quantity=session.leftovers,
                boxing_session_id=session.id
            ))

        # --- Write back to upstream ---
        if session.source_type == 'cutting':
            rec = record or session.cutting_production
            if rec:
                paused_min = (session.total_paused_seconds or 0) / 60.0
                if session.start_time and session.end_time:
                    rec.boxing_time_min = round(
                        (session.end_time - session.start_time).total_seconds() / 60.0 - paused_min, 2
                    )
                rec.date_boxed = session.end_time
                rec.boxes_made = session.boxes_packed or 0
                rec.waste_boxing = rec.waste_boxing or 0  # computed later at QC

                rec.total_production_time_min = sum(
                    t or 0 for t in [
                        getattr(rec, 'pre_expansion_time_min', 0),
                        getattr(rec, 'block_making_time_min', 0),
                        (getattr(rec, 'cutting_time_min', None) or getattr(rec, 'actual_production_time_min', 0)),
                        getattr(rec, 'boxing_time_min', 0),
                        getattr(rec, 'qc_time_min', 0),
                    ]
                )

            # PR16 back-link (legacy)
            if rec and boxing_fields_cb:
                boxing_fields_cb(rec, session)

        else:
            # extrusion: reflect boxes boxed to the upstream extrusion session
            extru = session.extrusion_session
            if extru:
                extru.actual_boxes_boxed = int(session.boxes_packed or 0)

        return safe_commit()
    except Exception as e:
        db.session.rollback()
        return False, str(e)

# ----------------------- leftovers -----------------------

def mark_leftovers_as_used(leftover_ids, used_in_session_id=None):
    now = datetime.utcnow()
    leftovers = (LeftoverCornice.query
                 .filter(LeftoverCornice.id.in_(leftover_ids), LeftoverCornice.used.is_(False))
                 .all())
    for l in leftovers:
        l.used = True
        l.used_in_session_id = used_in_session_id
        l.used_at = now
    return safe_commit()

# ----------------------- qty helper -----------------------

def qty_ready_to_box(rec_or_session):
    """
    Quantity that may move to boxing.
      - Cutting record: prefer QC good count; fallback to cut - total damaged.
      - Extrusion session: use pieces produced.
    """
    # Extrusion path
    if isinstance(rec_or_session, ExtrusionSession):
        return max(int(rec_or_session.pieces_produced or 0), 0)

    # Cutting path (legacy)
    rec = rec_or_session
    qc = getattr(rec, "quality_control", None)
    if qc and isinstance(getattr(qc, "good_cornices_count", None), int):
        return max(qc.good_cornices_count, 0)

    cut = rec.cornices_produced or 0
    damaged = rec.total_cornices_damaged or 0
    return max(cut - damaged, 0)
