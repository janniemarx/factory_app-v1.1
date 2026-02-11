from models import db
from models.pre_expansion import PreExpansion
from models.block import Block, BlockSession
from models.moulded_cornice import MouldedCorniceSession
from datetime import datetime

def get_batch_numbers():
    # Return distinct batch numbers for filter dropdown
    return [(pe.batch_no, pe.batch_no) for pe in PreExpansion.query.distinct(PreExpansion.batch_no).all()]

def filter_pre_expansions(batch_no=None, usage_type=None, date_from=None, date_to=None):
    query = PreExpansion.query.filter(PreExpansion.status == 'completed')

    if batch_no:
        query = query.filter(PreExpansion.batch_no == batch_no)
    if usage_type:
        query = query.filter(PreExpansion.purpose == usage_type)
    if date_from:
        start_dt = datetime.combine(date_from, datetime.min.time())
        query = query.filter(PreExpansion.start_time >= start_dt)
    if date_to:
        end_dt = datetime.combine(date_to, datetime.max.time())
        query = query.filter(PreExpansion.start_time <= end_dt)

    return query.all()

def calculate_analytics(pre_expansions):
    analytics_data = []

    for pe in pre_expansions:
        troubleshoot = []

        batch_no = pe.batch_no
        used_kg = pe.total_kg_used or 0.0
        purpose = pe.purpose
        material_code = getattr(pe, "material_code", None)
        operator_name = (
            pe.operator.full_name if getattr(pe, "operator", None) and pe.operator.full_name
            else (pe.operator.username if getattr(pe, "operator", None) else "-")
        )
        start_time = pe.start_time.strftime("%Y-%m-%d %H:%M") if pe.start_time else "-"
        end_time = pe.end_time.strftime("%Y-%m-%d %H:%M") if pe.end_time else "-"
        pre_exp_time = (pe.end_time - pe.start_time).total_seconds()/60 if pe.start_time and pe.end_time else 0.0

        # ---- shared accumulators
        total_items_produced = 0           # blocks count OR moulded cornices
        total_weight_produced = 0.0        # sum of block weights OR moulded weights
        block_session_time = 0.0
        cornice_session_time = 0.0
        session_id = None

        # ---- charts/aux
        block_numbers = []
        profiles = []
        produced = []
        cutting_damaged = []
        qc_damaged = []
        boxing_damaged = []
        block_weights = []
        block_weights_sum = 0.0
        block_profile_xlabels = []
        block_profile_counts = {}

        avg_block_weight = None
        avg_block_time = None
        avg_cut_time_per_block = None
        avg_boxing_time_per_block = None
        avg_cornices_per_cycle = None
        avg_cycle_time = None

        cornice_profiles = []
        cornice_quantities = []

        # QC
        qc_ratings = []
        qc_ratings_per_block = []
        avg_block_qc_rating = None

        # donut comparison
        block_time_comparison_labels = []
        block_time_comparison_values = []

        if purpose == 'Block':
            from models.production import CuttingProductionRecord
            from models.cutting import WireCuttingSession
            from models.boxing import BoxingSession

            block_sessions = BlockSession.query.filter_by(pre_expansion_id=pe.id).all()
            if block_sessions:
                session_id = block_sessions[0].id

            # ✅ Count ALL blocks for this batch (even if not cut yet)
            all_blocks = [b for s in block_sessions for b in s.blocks]
            troubleshoot.append(f"Found {len(all_blocks)} blocks for batch {batch_no}")

            total_items_produced = len(all_blocks)  # ✅ number of blocks
            block_weights = [(b.weight or 0.0) for b in all_blocks]
            block_weights_sum = round(sum(block_weights), 3)
            total_weight_produced = block_weights_sum  # ✅ show in table

            # block molding time
            for s in block_sessions:
                if s.started_at and s.ended_at:
                    block_session_time += (s.ended_at - s.started_at).total_seconds()/60

            # cut/boxing time buckets
            cut_times = []
            boxing_times = []

            for block in all_blocks:
                # Build labels regardless of cutting record
                block_numbers.append(block.block_number)

                # Cutting record is optional; default zeros if absent
                rec = CuttingProductionRecord.query.filter_by(block_id=block.id).first()

                label = f"{block.block_number} - {rec.profile_code}" if rec and rec.profile_code else block.block_number
                block_profile_xlabels.append(label)

                profiles.append(rec.profile_code if rec else None)
                produced.append(rec.cornices_produced or 0 if rec else 0)
                cutting_damaged.append(rec.wastage or 0 if rec else 0)

                if rec and rec.quality_control and hasattr(rec.quality_control, 'bad_cornices_count'):
                    qc_damaged.append(rec.quality_control.bad_cornices_count or 0)
                else:
                    qc_damaged.append(0)

                boxing_damaged.append(rec.waste_boxing or 0 if rec else 0)

                if rec and rec.profile_code:
                    block_profile_counts.setdefault(rec.profile_code, 0)
                    block_profile_counts[rec.profile_code] += rec.cornices_produced or 0

                # QC rating per block (optional)
                if rec and rec.quality_control and all([
                    rec.quality_control.rated_areo_effect,
                    rec.quality_control.rated_eps_binding,
                    rec.quality_control.rated_wetspots,
                    rec.quality_control.rated_dryness,
                    rec.quality_control.rated_lines
                ]):
                    block_avg = (
                        rec.quality_control.rated_areo_effect +
                        rec.quality_control.rated_eps_binding +
                        rec.quality_control.rated_wetspots +
                        rec.quality_control.rated_dryness +
                        rec.quality_control.rated_lines
                    ) / 5.0
                    qc_ratings.append(block_avg)
                    qc_ratings_per_block.append(round(block_avg, 2))
                else:
                    qc_ratings_per_block.append(None)

                # Cut time (segments or start/end)
                from models.cutting import WireCuttingSessionSegment  # only for typing; not used directly
                from models.cutting import WireCuttingSession as WCS
                cutting_sessions = WCS.query.filter_by(block_id=block.id).all()
                for cs in cutting_sessions:
                    total_cut = 0
                    if cs.segments:
                        for seg in cs.segments:
                            if seg.start_time and seg.end_time:
                                total_cut += (seg.end_time - seg.start_time).total_seconds()
                    elif cs.start_time and cs.end_time:
                        total_cut += (cs.end_time - cs.start_time).total_seconds()
                    if total_cut > 0:
                        cut_times.append(total_cut/60.0)

                # Boxing time (only if we have a cutting record id)
                if rec:
                    boxing_sessions = BoxingSession.query.filter_by(cutting_production_id=rec.id).all()
                    for bs in boxing_sessions:
                        if bs.start_time and bs.end_time:
                            t = (bs.end_time - bs.start_time).total_seconds() - (bs.total_paused_seconds or 0)
                            if t > 0:
                                boxing_times.append(t/60.0)

            # Averages for charts
            if total_items_produced > 0:
                w_nonzero = [w for w in block_weights if w > 0]
                avg_block_weight = round(sum(w_nonzero)/len(w_nonzero), 2) if w_nonzero else None
                avg_block_time = round(block_session_time/total_items_produced, 2) if block_session_time else None
                avg_cut_time_per_block = round(sum(cut_times)/len(cut_times), 2) if cut_times else None
                avg_boxing_time_per_block = round(sum(boxing_times)/len(boxing_times), 2) if boxing_times else None

            block_time_comparison_labels = ["Block Cycle", "Cut", "Boxing"]
            block_time_comparison_values = [
                avg_block_time or 0,
                avg_cut_time_per_block or 0,
                avg_boxing_time_per_block or 0
            ]

            if qc_ratings:
                avg_block_qc_rating = round(sum(qc_ratings)/len(qc_ratings), 2)

        elif purpose == 'Moulded':
            from models.moulded_cornice import MouldedCorniceSession
            sessions = MouldedCorniceSession.query.filter_by(pre_expansion_id=pe.id).all()
            if sessions:
                session_id = sessions[0].id

            cornice_profile_counter = {}
            total_weight_produced_m = 0.0   # ✅ accumulate across sessions

            for s in sessions:
                if s.start_time and s.end_time:
                    cornice_session_time += (s.end_time - s.start_time).total_seconds()/60

                summaries = s.production_summaries or []
                for summary in summaries:
                    qty = summary.quantity or 0
                    total_items_produced += qty
                    cornice_profile_counter[summary.profile_code] = cornice_profile_counter.get(summary.profile_code, 0) + qty
                    total_weight_produced_m += (summary.total_weight_kg or 0)  # ✅ accumulate weight

            total_weight_produced = round(total_weight_produced_m, 3)

            if s and s.cycles:
                avg_cornices_per_cycle = round(total_items_produced / s.cycles, 2)
                avg_cycle_time = round((cornice_session_time) / s.cycles, 2) if cornice_session_time else None

            cornice_profiles = list(cornice_profile_counter.keys())
            cornice_quantities = list(cornice_profile_counter.values())

        # ---- totals / averages
        total_production_time = pre_exp_time + block_session_time + cornice_session_time
        avg_preexp_time = round(pre_exp_time / total_items_produced, 2) if total_items_produced else 0
        avg_total_time = round(total_production_time / total_items_produced, 2) if total_items_produced else 0

        # Wasted = used - produced (never negative)
        wasted_material = round(max((used_kg or 0) - (total_weight_produced or 0), 0), 3)

        analytics_data.append({
            'pre_expansion_id': pe.id,
            'session_id': session_id,
            'batch_no': batch_no,
            'purpose': purpose,
            'used_kg': used_kg,
            'total_weight_produced': total_weight_produced,     # ✅ now correct
            'block_weights_sum': block_weights_sum,
            'total_items_produced': total_items_produced,       # ✅ blocks count OR moulded cornices
            'wasted_material': wasted_material,
            'pre_exp_time': round(pre_exp_time, 2),
            'block_session_time': round(block_session_time, 2),
            'cornice_session_time': round(cornice_session_time, 2),
            'total_time_minutes': round(total_production_time, 2),
            'avg_preexp_time': avg_preexp_time,
            'avg_block_weight': avg_block_weight,
            'avg_block_time': avg_block_time,
            'avg_cut_time_per_block': avg_cut_time_per_block,
            'avg_boxing_time_per_block': avg_boxing_time_per_block,
            'avg_time_per_item': avg_total_time,
            'material_code': material_code,
            'operator_name': operator_name,
            'start_time': start_time,
            'end_time': end_time,

            # charts
            'block_numbers': block_numbers,
            'block_profiles': profiles,
            'block_profile_xlabels': block_profile_xlabels,
            'block_produced': produced,
            'block_cutting_damaged': cutting_damaged,
            'block_qc_damaged': qc_damaged,
            'block_boxing_damaged': boxing_damaged,
            'block_weights': block_weights,
            'block_profile_labels': list(block_profile_counts.keys()) if purpose == 'Block' else [],
            'block_profile_qtys': list(block_profile_counts.values()) if purpose == 'Block' else [],
            'cornice_profiles': cornice_profiles if purpose == 'Moulded' else [],
            'cornice_quantities': cornice_quantities if purpose == 'Moulded' else [],
            'avg_cornices_per_cycle': avg_cornices_per_cycle,
            'avg_cycle_time': avg_cycle_time,
            'avg_block_qc_rating': avg_block_qc_rating,
            'block_qc_ratings_per_block': qc_ratings_per_block if purpose == 'Block' else [],
            'block_time_comparison_labels': block_time_comparison_labels,
            'block_time_comparison_values': block_time_comparison_values,
            'troubleshoot': troubleshoot,
        })

    return analytics_data