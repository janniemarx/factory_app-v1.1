
from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from models import db
from models.production import CuttingProductionRecord
from models.qc import QualityControl
from models.operator import Operator
from models.moulded_boxing import MouldedBoxingSession
from .forms import QualityControlForm
from datetime import datetime
from sqlalchemy import or_
from .forms import PR16QualityControlForm
from models.pr16_session import PR16Session, PR16QualityCheck

qc_bp = Blueprint('qc', __name__, template_folder='../../templates/qc')


# 1) PENDING LIST — exclude PR16 from Cutting QC
# blueprints/qc/routes.py (or wherever your qc_bp.pending_qc lives)
from models.boxing import BoxingSession  # add this import

@qc_bp.route('/pending', methods=['GET'])
@login_required
def pending_qc():
    # ⬇️ Exclude PR16 entirely from the cutting QC list
    cutting_records = (
        CuttingProductionRecord.query
        .filter(~CuttingProductionRecord.quality_control.has())
        .filter(CuttingProductionRecord.profile_code != 'PR16')                     # hard exclude
        .filter(or_(CuttingProductionRecord.qc_status == None,                      # and also exclude any
                    ~CuttingProductionRecord.qc_status.ilike('pr16%')))             # pr16_* statuses
        .order_by(CuttingProductionRecord.id.desc())
        .all()
    )

    moulded_pending = (
        MouldedBoxingSession.query
        .filter(MouldedBoxingSession.status == 'pending_qc')
        .order_by(MouldedBoxingSession.end_time.desc())
        .all()
    )

    pr16_pending = (
        PR16Session.query
        .filter(PR16Session.status == 'awaiting_qc')
        .order_by(PR16Session.trimming_end.desc().nullslast())
        .all()
    )

    boxing_pending = (
        BoxingSession.query
        .filter(BoxingSession.status == 'pending_qc')
        .order_by(BoxingSession.end_time.desc())
        .all()
    )

    return render_template('qc/pending_qc.html',
                           cutting_records=cutting_records,
                           pr16_pending=pr16_pending,
                           moulded_pending=moulded_pending,
                           boxing_pending=boxing_pending)



# 2) QC FORM — hard gate PR16 away from cutting QC
@qc_bp.route('/quality_control/<int:cutting_production_id>', methods=['GET', 'POST'])
@login_required
def quality_control(cutting_production_id):
    record = CuttingProductionRecord.query.get_or_404(cutting_production_id)

    # If this record is PR16 or marked as PR16 flow, do NOT allow cutting QC here
    if record.profile_code == 'PR16' or (record.qc_status or '').startswith('pr16_'):
        flash("PR16 QC is done after wrapping & drying, not in Cutting QC.", "info")
        return redirect(url_for('qc.pending_qc'))

    # Already QC’d? Exit gracefully.
    if record.quality_control:
        flash("QC has already been captured for this batch.", "info")
        return redirect(url_for('qc.pending_qc'))

    operator_count = record.cornices_produced or 0
    form = QualityControlForm()
    debug_errors = None

    # Prefill on GET
    if request.method == 'GET':
        form.cutting_production_id.data = record.id
        form.cornices_count_operator.data = operator_count
        form.cornices_count_qc.data = operator_count
        form.bad_cornices_count.data = 0

    if form.validate_on_submit():
        if form.bad_cornices_count.data > form.cornices_count_qc.data:
            flash("Bad Cornices cannot be greater than the total counted.", "danger")
            debug_errors = {"bad_cornices_count": ["Bad Cornices cannot be greater than the total counted."]}
        else:
            try:
                qc_count = form.cornices_count_qc.data or 0
                bad_count = form.bad_cornices_count.data or 0
                good_cornices = max(qc_count - bad_count, 0)

                qc = QualityControl(
                    cutting_production_id=record.id,
                    cornices_count_operator=form.cornices_count_operator.data,
                    cornices_count_qc=qc_count,
                    bad_cornices_count=bad_count,
                    good_cornices_count=good_cornices,
                    rated_areo_effect=form.rated_areo_effect.data,
                    rated_eps_binding=form.rated_eps_binding.data,
                    rated_wetspots=form.rated_wetspots.data,
                    rated_dryness=form.rated_dryness.data,
                    rated_lines=form.rated_lines.data,
                    qc_done_by=current_user.id,
                    timestamp=datetime.utcnow(),
                    is_boxing_ready=True
                )
                db.session.add(qc)

                # extra QC waste roll-up
                extra_qc_waste = max(operator_count - good_cornices, 0)
                seeded_total = record.total_cornices_damaged
                if seeded_total is None:
                    seeded_total = record.wastage or 0
                record.total_cornices_damaged = seeded_total + extra_qc_waste

                # Passed cutting QC → boxable
                record.qc_status = 'passed'
                record.is_boxable = True

                db.session.commit()
                flash("Quality Control completed. Batch is now ready for boxing.", "success")
                return redirect(url_for('qc.pending_qc'))

            except Exception as e:
                db.session.rollback()
                flash("An error occurred while saving QC data.", "danger")
                debug_errors = {"db_commit": [str(e)]}

    elif request.method == "POST":
        debug_errors = form.errors
        flash("There was a problem submitting the form. Please check your entries.", "danger")

    return render_template('qc/quality_control.html', record=record, form=form, debug_errors=debug_errors)


# 3. Optional: List all batches that have passed QC and are ready for boxing
@qc_bp.route('/ready_for_boxing', methods=['GET'])
@login_required
def ready_for_boxing():
    ready_records = (
        CuttingProductionRecord.query
        .join(QualityControl)
        .filter(QualityControl.is_boxing_ready == True)
        .order_by(CuttingProductionRecord.id.desc())
        .all()
    )
    return render_template('qc/ready_for_boxing.html', records=ready_records)


@qc_bp.route('/pr16/<int:session_id>', methods=['GET', 'POST'])
@login_required
def pr16_quality_control(session_id):
    from models.production import CuttingProductionRecord
    from models.pr16_session import PR16Session, PR16QualityCheck
    from .forms import PR16QualityControlForm
    from flask import flash, redirect, render_template, request, url_for
    from flask_login import current_user
    from models import db

    session = PR16Session.query.get_or_404(session_id)

    if session.status != 'awaiting_qc':
        flash("This PR16 session is not awaiting QC.", "info")
        return redirect(url_for('qc.pending_qc'))

    rec = (CuttingProductionRecord.query
           .filter_by(block_id=session.block_id, profile_code='PR16')
           .order_by(CuttingProductionRecord.id.desc())
           .first())
    if not rec:
        flash("No cutting production record found for this PR16 block.", "danger")
        return redirect(url_for('qc.pending_qc'))

    operator_count = int(session.trimmed_cornices or session.wrapped_cornices or (rec.cornices_produced or 0))

    form = PR16QualityControlForm()
    if request.method == 'GET':
        form.session_id.data = session.id
        form.cornices_count_operator.data = operator_count
        form.cornices_count_qc.data = operator_count
        form.bad_cornices_count.data = 0

    if form.validate_on_submit():
        if form.bad_cornices_count.data > form.cornices_count_qc.data:
            flash("Bad Cornices cannot be greater than the QC count.", "danger")
        else:
            try:
                qc_count  = int(form.cornices_count_qc.data or 0)
                bad_count = int(form.bad_cornices_count.data or 0)
                good      = max(qc_count - bad_count, 0)

                # Save PR16 QC
                pr = PR16QualityCheck(
                    session_id=session.id,
                    qc_operator_id=current_user.id,
                    # the following four fields require columns on PR16QualityCheck (see Fix 3)
                    cornices_count_operator=operator_count,
                    cornices_count_qc=qc_count,
                    bad_cornices_count=bad_count,
                    good_cornices_count=good,
                    passed=True,
                    is_boxing_ready=True,
                    notes=form.notes.data
                )
                db.session.add(pr)

                # Waste roll-up on the production record
                seeded_total = rec.total_cornices_damaged if rec.total_cornices_damaged is not None else (rec.wastage or 0)
                extra_qc_waste = max(operator_count - good, 0)
                rec.total_cornices_damaged = int(seeded_total) + int(session.wrapping_damage or 0) + int(session.trimming_damage or 0) + int(extra_qc_waste)

                # Mark as passed + boxable
                rec.qc_status = 'passed'
                rec.is_boxable = True

                # Reflect on PR16 session
                session.status = 'qc_passed'
                session.boxed_cornices = good  # qty that flows to boxing

                db.session.commit()
                flash("PR16 QC completed. Batch is now ready for boxing.", "success")
                return redirect(url_for('qc.pending_qc'))
            except Exception as e:
                db.session.rollback()
                flash(f"Error saving PR16 QC: {e}", "danger")

    return render_template('qc/pr16_quality_control.html', session=session, rec=rec, form=form)