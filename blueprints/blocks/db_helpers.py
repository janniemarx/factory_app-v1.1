# blueprints/blocks/db_helpers.py

from datetime import datetime, date, timedelta
from sqlalchemy import func, or_
from sqlalchemy.exc import SQLAlchemyError

from models import db
from models.pre_expansion import PreExpansion
from models.block import BlockSession, Block, BlockMaterialConsumption
from models.pr16_stash import PR16Stash

# Re-use your generator so batch numbers remain consistent
from blueprints.pre_expansion.db_helpers import generate_batch_no

CURING_DAYS_BY_DENSITY = {18: 3, 23: 5}



def _curing_end_for(pre_exp, created_at=None):
    """Return created_at + required curing days, based on pre-exp density."""
    created_at = created_at or datetime.utcnow()
    try:
        d = int(round(float(pre_exp.density or 0)))
    except Exception:
        d = 18
    days = CURING_DAYS_BY_DENSITY.get(d, 3)  # default to 3 if not mapped
    return created_at + timedelta(days=days)



def safe_commit():
    try:
        db.session.commit()
        return True, None
    except SQLAlchemyError as e:
        db.session.rollback()
        return False, str(e)


# ----------------------------
# Listing / session lifecycle
# ----------------------------

def get_available_pre_expansions():
    """
    Completed, unused pre-expansions specifically for Blocks.
    """
    try:
        batches = (PreExpansion.query
                   .filter_by(status='completed', is_used=False, purpose='Block')
                   .order_by(PreExpansion.end_time.desc())
                   .all())
        return batches, None
    except SQLAlchemyError as e:
        return [], str(e)


def create_block_session(pre_expansion_id, operator_id):
    session = BlockSession(
        pre_expansion_id=pre_expansion_id,
        operator_id=operator_id,
        status='active',
        started_at=datetime.utcnow(),
    )
    db.session.add(session)
    ok, err = safe_commit()
    return (session if ok else None), err


def get_active_block_sessions():
    try:
        sessions = (BlockSession.query
                    .filter_by(status='active')
                    .order_by(BlockSession.started_at.desc())
                    .all())
        return sessions, None
    except SQLAlchemyError as e:
        return [], str(e)


def get_session_blocks(session_id):
    try:
        blocks = (Block.query
                  .filter_by(block_session_id=session_id)
                  .order_by(Block.created_at.asc())
                  .all())
        return blocks, None
    except SQLAlchemyError as e:
        return [], str(e)


# ----------------------------
# PR16 stash helpers (FIFO)
# ----------------------------
from models.pr16_stash import PR16Stash  # ✅ keep this import

def pr16_total_remaining(density, material_code):
    q = (db.session.query(func.coalesce(func.sum(PR16Stash.kg_remaining), 0.0))
         .filter(PR16Stash.kg_remaining > 0))
    if density is not None:
        q = q.filter(PR16Stash.density == density)
    if material_code:
        q = q.filter(PR16Stash.material_code == material_code)
    return float(q.scalar() or 0.0)

def pr16_rows_fifo(density, material_code):
    q = (PR16Stash.query
         .filter(PR16Stash.kg_remaining > 0)
         .order_by(PR16Stash.created_at.asc(), PR16Stash.id.asc()))
    if density is not None:
        q = q.filter(PR16Stash.density == density)
    if material_code:
        q = q.filter(PR16Stash.material_code == material_code)
    return q.all()

def _stash_leftover_to_pr16(source_pre_exp: PreExpansion, leftover_kg: float):
    """
    Add one PR16 stash row for this leftover.
    NOTE: model has only kg_remaining (no kg_original), so we set kg_remaining only.
    """
    entry = PR16Stash(
        source_pre_expansion_id=source_pre_exp.id,
        density=source_pre_exp.density,
        material_code=source_pre_exp.material_code,
        kg_remaining=float(leftover_kg),
    )
    db.session.add(entry)
    ok, err = safe_commit()
    if not ok:
        raise RuntimeError(err)
    return entry


# ---------------------------------
# Per-block save & consumption rows
# ---------------------------------

def _alloc_from_pr16_fifo(required_kg, density, material_code):
    """
    Consume from PR16 stash FIFO. Returns list of (source_pre_exp_id, kg_taken)
    and the remaining kg still required after PR16 pull.
    """
    allocations = []
    remaining = float(required_kg or 0)
    if remaining <= 0:
        return allocations, 0.0

    for row in pr16_rows_fifo(density, material_code):
        if remaining <= 0:
            break
        take = min(row.kg_remaining, remaining)
        if take <= 0:
            continue
        row.kg_remaining = round(float(row.kg_remaining) - float(take), 3)
        allocations.append((row.source_pre_expansion_id, float(take)))
        remaining = round(remaining - take, 3)

    return allocations, remaining


from sqlalchemy import or_

def add_block_to_session(session, pre_exp, form, operator_id):
    ...
    now = datetime.utcnow()
    density = int(pre_exp.density)
    year = datetime.now().strftime('%y')
    prefix = f"{density}/{year}"

    # All pre-expansions with this density for sequential numbering
    pre_exp_ids = [pe.id for pe in PreExpansion.query.filter_by(density=density).all()]

    # ✅ Count BOTH plain and PR16-prefixed numbers for this density/year
    existing_count = (
        Block.query
        .filter(Block.pre_expansion_id.in_(pre_exp_ids))
        .filter(or_(
            Block.block_number.like(f"{prefix}%"),
            Block.block_number.like(f"PR16-{prefix}%")
        ))
        .count()
    )

    # Build next number and ensure uniqueness (handles rare races too)
    n = existing_count + 1

    def make_base(num: int) -> str:
        return f"{density}/{year}{str(num).zfill(3)}"

    def make_candidate(num: int, is_pr16: bool) -> str:
        base = make_base(num)
        return f"PR16-{base}" if is_pr16 else base

    candidate_block_number = make_candidate(n, bool(form.is_profile16.data))
    while Block.query.filter_by(block_number=candidate_block_number).first() is not None:
        n += 1
        candidate_block_number = make_candidate(n, bool(form.is_profile16.data))

    # Now create the block with the unique number
    block = Block(
        block_session_id=session.id,
        pre_expansion_id=session.pre_expansion_id,
        operator_id=operator_id,
        block_number=candidate_block_number,
        weight=form.weight.data,
        heating1_time=form.heating1_time.data,
        heating2_time=form.heating2_time.data,
        heating3_time=form.heating3_time.data,
        cooling_time=form.cooling_time.data,
        is_profile16=form.is_profile16.data,
        created_at=now,
    )
    block.curing_end = _curing_end_for(pre_exp, created_at=now)
    db.session.add(block)
    ok, err = safe_commit()
    if not ok:
        return None, err, None

    # --- per-source consumption stays the same ---
    required = float(block.weight or 0)
    allocations = []

    if form.is_profile16.data:
        pull, remaining = _alloc_from_pr16_fifo(required, pre_exp.density, pre_exp.material_code)
        allocations.extend(pull)
        if remaining > 0:
            allocations.append((pre_exp.id, remaining))
    else:
        allocations.append((pre_exp.id, required))

    for src_pre_exp_id, kg in allocations:
        db.session.add(BlockMaterialConsumption(
            block_id=block.id,
            source_pre_expansion_id=src_pre_exp_id,
            kg_from_source=float(kg),
        ))

    ok, err = safe_commit()
    return (block if ok else None), err, candidate_block_number



# ----------------------------
# Finish session + leftovers
# ----------------------------

def _consumed_kg_for_batch(pre_exp_id):
    """
    Amount REALLY taken from this batch (sum of per-source allocations).
    This ignores any KG that came from the PR16 stash or other batches.
    """
    from models.block import BlockMaterialConsumption  # local import to avoid cycles
    total = (db.session.query(func.coalesce(func.sum(BlockMaterialConsumption.kg_from_source), 0.0))
             .filter(BlockMaterialConsumption.source_pre_expansion_id == pre_exp_id)
             .scalar()) or 0.0
    return float(total)


def _create_leftover_preexp_for_moulded(source_pre_exp: PreExpansion, leftover_kg: float, operator_id: int) -> PreExpansion:
    """
    Create a *completed* PreExpansion representing leftover beads re-assigned to Moulded.
    This batch will appear in the Moulded start list (status=completed, is_used=False).
    """
    batch_no = generate_batch_no(date.today(), source_pre_exp.density, 'Moulded')
    now = datetime.utcnow()
    new_pre = PreExpansion(
        batch_no=batch_no,
        pre_exp_date=date.today(),
        density=source_pre_exp.density,
        planned_kg=float(leftover_kg),
        total_kg_used=float(leftover_kg),  # treat as fully usable amount
        purpose='Moulded',
        operator_id=operator_id,
        material_code=source_pre_exp.material_code,
        status='completed',
        start_time=now,
        end_time=now,
        is_used=False,
        is_pastel_captured=False,
    )
    db.session.add(new_pre)
    ok, err = safe_commit()
    if not ok:
        raise RuntimeError(err)
    return new_pre

def finish_block_session_with_leftover(session: BlockSession,
                                       assignment: str | None,
                                       operator_id: int | None):
    """
    Close session; if batch has leftover KG, require an assignment:
      - assignment == 'moulded' -> create new leftover PreExpansion for Moulded
      - assignment == 'pr16'    -> move to PR16 stash

    IMPORTANT: We do NOT mark the session completed until the assignment is provided
    (or there is no leftover).
    Returns: (ok: bool, err: str|None, leftover_kg: float, created_target: PreExpansion|None)
    """
    try:
        pre_exp = session.pre_expansion

        # Compute current consumption & leftover
        consumed = _consumed_kg_for_batch(pre_exp.id)
        entered_used = float(pre_exp.total_kg_used or 0.0)
        planned = float(pre_exp.planned_kg or 0.0)
        batch_available = max(entered_used, planned)
        leftover = round(max(batch_available - consumed, 0.0), 3)

        created_target = None

        # If leftover exists and no assignment was provided, just ask the caller to prompt the user.
        if leftover > 0 and not assignment:
            # DO NOT change session status/ended_at yet.
            return False, "LEFTOVER_NEEDS_ASSIGNMENT", leftover, None

        # Handle leftover disposition if needed
        if leftover > 0 and assignment:
            if assignment == 'moulded':
                new_pre = _create_leftover_preexp_for_moulded(pre_exp, leftover, operator_id)
                created_target = new_pre
                pre_exp.leftover_kg = leftover
                pre_exp.leftover_disposition = 'moulded'
                pre_exp.leftover_target_pre_expansion_id = new_pre.id
                pre_exp.is_used = True
            elif assignment == 'pr16':
                _stash_leftover_to_pr16(pre_exp, leftover)
                pre_exp.leftover_kg = leftover
                pre_exp.leftover_disposition = 'pr16'
                pre_exp.leftover_target_pre_expansion_id = None
                pre_exp.is_used = True
            else:
                return False, "Invalid leftover assignment.", leftover, None
        elif leftover <= 0:
            # no leftover; mark as fully used
            pre_exp.leftover_kg = 0.0
            pre_exp.leftover_disposition = None
            pre_exp.leftover_target_pre_expansion_id = None
            pre_exp.is_used = True

        # Only now finalize the session
        session.status = 'completed'
        session.ended_at = datetime.utcnow()

        ok, err = safe_commit()
        return ok, err, leftover, created_target

    except Exception as e:
        db.session.rollback()
        return False, str(e), 0.0, None


# ----------------------------
# Query helpers for reporting
# ----------------------------

def get_completed_blocks_and_sessions(form):
    """
    (unchanged from your version – keep your existing search/analytics)
    Kept here for completeness if you were importing from this module.
    """
    from models.production import CuttingProductionRecord
    from models.block import Block, BlockSession
    from models.pre_expansion import PreExpansion

    try:
        all_densities = db.session.query(PreExpansion.density).distinct().order_by(PreExpansion.density).all()
        density_choices = [('', 'Any')] + [(str(d[0]), str(d[0])) for d in all_densities if d[0] is not None]
        form.density.choices = density_choices

        block_session_pairs = []
        filtered_blocks = []
        profile_code = form.profile_code.data.strip() if form.profile_code.data else None
        density = form.density.data if form.density.data else None
        date_from = form.date_from.data
        date_to = form.date_to.data
        search_performed = False

        if form.is_submitted() and form.validate():
            search_performed = True
            blocks_query = Block.query.join(BlockSession).filter(BlockSession.status == 'completed')
            if density:
                blocks_query = blocks_query.join(PreExpansion, Block.pre_expansion_id == PreExpansion.id)
                blocks_query = blocks_query.filter(PreExpansion.density == float(density))
            if profile_code:
                prods = CuttingProductionRecord.query.filter(
                    CuttingProductionRecord.profile_code.ilike(f"%{profile_code}%")
                ).all()
                block_ids = set(prod.block_id for prod in prods)
                blocks_query = blocks_query.filter(Block.id.in_(block_ids))
            if date_from:
                blocks_query = blocks_query.filter(Block.created_at >= date_from)
            if date_to:
                blocks_query = blocks_query.filter(Block.created_at <= date_to)
            blocks = blocks_query.order_by(Block.created_at.desc()).all()
        else:
            blocks = (Block.query
                      .join(BlockSession)
                      .filter(BlockSession.status == 'completed')
                      .order_by(Block.created_at.desc())
                      .all())

        for block in blocks:
            session = block.block_session
            block_session_pairs.append((block, session))
            filtered_blocks.append(block)

        total_blocks = len(filtered_blocks)
        total_weight = sum(block.weight for block in filtered_blocks)
        avg_weight = round(total_weight / total_blocks, 2) if total_blocks else 0

        analytics = {
            "total_blocks": total_blocks,
            "total_weight": total_weight,
            "avg_weight": avg_weight,
        }

        return block_session_pairs, form, analytics, search_performed, None
    except Exception as e:
        return [], form, {}, False, str(e)
