from models import db
import pandas as pd
import math
from models.production import CuttingProductionRecord
from models.cutting import (
    WireCuttingSession, Machine, Profile, MachineProfileAssignment, WireCuttingSessionSegment
)
from models.block import Block
from models.operator import Operator
from models.pre_expansion import PreExpansion
from sqlalchemy.exc import SQLAlchemyError
from datetime import datetime

def safe_commit():
    try:
        db.session.commit()
        return True, None
    except SQLAlchemyError as e:
        db.session.rollback()
        return False, str(e)

def get_machines():
    try:
        machines = Machine.query.order_by(Machine.name).all()
        return machines, None
    except SQLAlchemyError as e:
        return [], str(e)

def get_operators():
    try:
        operators = Operator.query.order_by(Operator.full_name).all()
        return operators, None
    except SQLAlchemyError as e:
        return [], str(e)

def get_profiles_for_machine(machine_id):
    try:
        # Uncut assignments for this machine
        qs = (MachineProfileAssignment.query
              .filter_by(machine_id=machine_id, cut=False)
              .all())

        # De-duplicate by profile_code
        profiles_by_code = {}
        for a in qs:
            if a.profile and a.profile_code not in profiles_by_code:
                profiles_by_code[a.profile_code] = a.profile

        # Exclude any profile already being cut on this machine (active session)
        active_codes = set(
            code for (code,) in db.session.query(WireCuttingSession.profile_code)
            .filter(WireCuttingSession.machine_id == machine_id,
                    WireCuttingSession.status == 'active')
            .all()
        )
        for code in list(profiles_by_code.keys()):
            if code in active_codes:
                del profiles_by_code[code]

        return list(profiles_by_code.values()), None
    except SQLAlchemyError as e:
        return [], str(e)

def get_oldest_block_for_profile(profile_code):
    try:
        from models.block import Block
        from models.pre_expansion import PreExpansion
        from models.cutting import Profile
        from datetime import datetime

        profile = Profile.query.filter_by(code=profile_code).first()
        now = datetime.utcnow()
        if not profile:
            return None, "Profile not found."

        # === PR16: prefer reserved PR16 blocks; else fall back to any 18-density standard block ===
        if profile_code == "PR16":
            # 1) Try reserved PR16 block (keeps your current rule)
            reserved = (
                Block.query
                .join(PreExpansion, Block.pre_expansion_id == PreExpansion.id)
                .filter(Block.is_cut == False)
                .filter(Block.is_profile16 == True)
                .filter(PreExpansion.density == profile.density)  # usually 18
                .filter(Block.curing_end <= now)
                .order_by(Block.created_at.asc())
                .first()
            )
            if reserved:
                return reserved, None

            # 2) Fallback: any 18-density standard block (not reserved for PR16)
            fallback_density = 18  # per requirement
            fallback = (
                Block.query
                .join(PreExpansion, Block.pre_expansion_id == PreExpansion.id)
                .filter(Block.is_cut == False)
                .filter((Block.is_profile16 == False) | (Block.is_profile16 == None))
                .filter(PreExpansion.density == fallback_density)
                .filter(Block.curing_end <= now)
                .order_by(Block.created_at.asc())
                .first()
            )
            if fallback:
                return fallback, None

            return None, "No suitable PR16-reserved or 18-density fallback block available."

        # === Other profiles: keep excluding PR16-reserved blocks ===
        block = (
            Block.query
            .join(PreExpansion, Block.pre_expansion_id == PreExpansion.id)
            .filter(Block.is_cut == False)
            .filter((Block.is_profile16 == False) | (Block.is_profile16 == None))
            .filter(PreExpansion.density == profile.density)
            .filter(Block.curing_end <= now)
            .order_by(Block.created_at.asc())
            .first()
        )
        if not block:
            return None, "No suitable block available."
        return block, None

    except Exception as e:
        return None, str(e)


def start_wire_cutting_session(form, current_user_id):
    try:
        block = Block.query.get(form.block_id.data)
        if not block or block.is_cut:
            return None, "Selected block is invalid or already cut."
        block.is_cut = True

        # Mark ALL assignments for this machine/profile as cut
        (MachineProfileAssignment.query
            .filter_by(machine_id=form.machine_id.data, profile_code=form.profile_code.data, cut=False)
            .update({"cut": True}, synchronize_session=False))

        session = WireCuttingSession(
            block_id=block.id,
            machine_id=form.machine_id.data,
            profile_code=form.profile_code.data,
            operator_id=current_user_id,
            status='active',
            start_time=datetime.utcnow()
        )
        db.session.add(session)

        success, error = safe_commit()
        return session if success else None, error
    except SQLAlchemyError as e:
        db.session.rollback()
        return None, str(e)


def get_session_detail(session_id):
    try:
        session = WireCuttingSession.query.get(session_id)
        return session, None
    except SQLAlchemyError as e:
        return None, str(e)

def pause_session(session):
    try:
        segment = session.segments[-1] if session.segments and session.segments[-1].end_time is None else None
        if segment:
            segment.end_time = datetime.utcnow()
        session.is_paused = True
        return safe_commit()
    except Exception as e:
        db.session.rollback()
        return False, str(e)

def resume_session(session):
    try:
        new_segment = WireCuttingSessionSegment(session_id=session.id, start_time=datetime.utcnow())
        db.session.add(new_segment)
        session.is_paused = False
        return safe_commit()
    except Exception as e:
        db.session.rollback()
        return False, str(e)

def complete_session(session, form):
    try:
        # close current open segment
        segment = session.segments[-1] if session.segments and session.segments[-1].end_time is None else None
        if segment:
            segment.end_time = datetime.utcnow()

        profile = session.profile
        cornices_per_block = profile.cornices_per_block if profile else 0
        cornices_cut = form.profiles_cut.data
        wastage = max(cornices_per_block - cornices_cut, 0)

        session.profiles_cut = cornices_cut
        session.status = 'completed'
        session.end_time = datetime.utcnow()
        session.is_paused = False
        session.block.is_cut = True

        actual_time_min = calculate_actual_cut_time(session)
        db.session.flush()  # ensure session.id exists

        is_pr16 = (session.profile_code == 'PR16')

        # NEW: compute pre-exp and block-making durations if available
        pre_exp_min = None
        block_make_min = None
        b = session.block
        if b and b.pre_expansion and b.pre_expansion.start_time and b.pre_expansion.end_time:
            pre_exp_min = int((b.pre_expansion.end_time - b.pre_expansion.start_time).total_seconds() / 60)
        if b and b.block_session and b.block_session.started_at and b.block_session.ended_at:
            block_make_min = int((b.block_session.ended_at - b.block_session.started_at).total_seconds() / 60)

        prod_record = CuttingProductionRecord(
            profile_code=session.profile_code,
            block_id=session.block.id,
            block_number=session.block.block_number,
            pre_exp_batch_no=session.block.pre_expansion.batch_no if session.block.pre_expansion else '',
            cornices_produced=cornices_cut,
            wastage=wastage,  # cut waste (before QC)
            total_cornices_damaged=wastage,  # start running total here 👈
            date_boxed=None,
            actual_production_time_min=actual_time_min,
            cutting_time_min=actual_time_min,
            pre_expansion_time_min=pre_exp_min,
            block_making_time_min=block_make_min,
            boxes_made=None,
            waste_boxing=None,
            is_boxable=False,  # blocked until QC
            qc_status=('pr16_qc_pending' if is_pr16 else 'pending')
        )

        # Partial total; will be finalized after boxing/QC
        prod_record.total_production_time_min = sum(
            t or 0 for t in [
                pre_exp_min, block_make_min, actual_time_min  # boxing + qc added later
            ]
        )

        db.session.add(prod_record)
        return safe_commit()
    except Exception as e:
        db.session.rollback()
        return False, str(e)


def calculate_actual_cut_time(session):
    total = 0
    for seg in session.segments:
        if seg.end_time:
            total += (seg.end_time - seg.start_time).total_seconds()
        else:
            total += (datetime.utcnow() - seg.start_time).total_seconds()
    return round(total / 60, 2)

def parse_cutting_excel(filepath):
    """
    Reads the given Excel file and extracts PR profiles from Stock to Make worksheet.
    Returns a list of dicts:
    [
      {'profile_code': 'PR16', 'boxes_needed': 10, 'urgent_boxes': 3},
      ...
    ]
    """
    df = pd.read_excel(filepath, sheet_name='Stock to Make', header=None)
    result = []
    # Start from row 17 (zero-indexed is 16)
    for idx in range(16, len(df)):
        profile = str(df.iloc[idx, 0]).strip()
        if not profile.startswith("PR"):
            continue
        try:
            boxes = int(df.iloc[idx, 1])
        except Exception:
            boxes = 0
        try:
            urgent = int(df.iloc[idx, 2])
        except Exception:
            urgent = 0
        # **Filter: Only show if we need to make something**
        if boxes == 0 and urgent == 0:
            continue
        result.append({
            'profile_code': profile,
            'boxes_needed': boxes,
            'urgent_boxes': urgent
        })
    return result


# ---------- 2. CALCULATE BLOCK REQUIREMENTS PER PROFILE ----------

def get_profile_block_requirements(parsed_rows):
    """
    For each parsed profile, compute total blocks needed and urgent flag.
    Returns:
    [
      {
        'profile_code': 'PR16',
        'boxes_needed': 10,
        'urgent_boxes': 3,
        'total_cornices': ...,
        'blocks_needed': ...,
        'urgent': True/False
      },
      ...
    ]
    """
    profiles = {p.code: p for p in Profile.query.all()}
    results = []
    for row in parsed_rows:
        code = row['profile_code']
        p = profiles.get(code)
        if not p:
            continue  # Profile not found in DB
        boxes = row['boxes_needed']
        urgent = row['urgent_boxes']
        # Only skip if both boxes and urgent are zero (handled already in parse_cutting_excel)
        total_cornices = (boxes + abs(urgent)) * p.cornices_per_box
        blocks_needed = math.ceil(abs(total_cornices) / p.cornices_per_block) if p.cornices_per_block else 0
        is_urgent = urgent != 0
        results.append({
            'profile_code': code,
            'boxes_needed': boxes,
            'urgent_boxes': urgent,
            'cornices_per_box': p.cornices_per_box,
            'cornices_per_block': p.cornices_per_block,
            'total_cornices': total_cornices,
            'blocks_needed': blocks_needed,
            'urgent': is_urgent
        })
    return results


# ---------- 3. AUTO-ASSIGN BLOCKS TO MACHINES ----------

def auto_assign_profiles_to_machines(
    blocks_needed_per_profile,
    max_blocks_per_machine=2,
    max_blocks_per_machine_overtime=3,
    allow_overtime=False
):
    """
    Assign as many blocks of the same profile to one machine as possible before using the next machine.
    Returns a dict: { machine_id: [ {profile_code, blocks_assigned, urgent}, ... ] }
    """
    machines = Machine.query.order_by(Machine.id).all()
    if not machines:
        return {}, "No machines found"

    assignment = {m.id: [] for m in machines}
    machine_count = len(machines)
    max_blocks = max_blocks_per_machine_overtime if allow_overtime else max_blocks_per_machine

    # Keep track of how many blocks each machine has in total
    machine_block_counter = {m.id: 0 for m in machines}

    # Sort urgent profiles first
    sorted_profiles = sorted(blocks_needed_per_profile, key=lambda r: not r['urgent'])

    machine_idx = 0  # Start from the first machine

    for prof in sorted_profiles:
        blocks_left = prof['blocks_needed']
        profile_code = prof['profile_code']

        # For each profile, try to fill up a machine before moving to next
        while blocks_left > 0 and machine_idx < machine_count:
            m = machines[machine_idx]
            used = machine_block_counter[m.id]
            space = max_blocks - used
            if space <= 0:
                machine_idx += 1
                continue
            to_assign = min(blocks_left, space)
            assignment[m.id].append({
                'profile_code': profile_code,
                'blocks_assigned': to_assign,
                'urgent': prof['urgent']
            })
            machine_block_counter[m.id] += to_assign
            blocks_left -= to_assign
            # If this machine is full, go to the next
            if machine_block_counter[m.id] == max_blocks:
                machine_idx += 1

        # Reset machine_idx if we ran out, so next profile continues filling from next available machine
        if machine_idx >= machine_count:
            machine_idx = 0

    return assignment, None





# ---------- 4. ASSIGNMENTS TO DB ----------

def save_machine_profile_assignments(assignments_dict):
    """
    Given {machine_id: [{profile_code, blocks_assigned, urgent}], ...}, save to DB.
    """
    # Clear previous
    MachineProfileAssignment.query.delete()
    db.session.commit()
    for machine_id, profile_list in assignments_dict.items():
        for item in profile_list:
            for _ in range(item['blocks_assigned']):
                a = MachineProfileAssignment(
                    machine_id=machine_id,
                    profile_code=item['profile_code'],
                )
                db.session.add(a)
    db.session.commit()
    return True, None

# ---------- 5. UTILITY TO FLAG URGENT ASSIGNMENTS FOR UI ----------

def get_machine_assignments_with_urgency():
    assignments = MachineProfileAssignment.query.all()
    profiles = {p.code: p for p in Profile.query.all()}
    result = []
    for a in assignments:
        urgent = False
        # You may want to store urgency as a field or infer based on current logic
        # For now, let's set all assignments of urgent profiles as urgent
        p = profiles.get(a.profile_code)
        if p:
            # ...You may want to link to current urgent plan or keep a log
            pass
        result.append({
            "machine_id": a.machine_id,
            "profile_code": a.profile_code,
            "urgent": urgent
        })
    return result