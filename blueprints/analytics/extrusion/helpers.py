from datetime import datetime
from sqlalchemy import func
from models.extrusion import ExtrusionSession, ExtrusionRunSegment
from models import db

def _session_runtime_seconds(session: ExtrusionSession) -> int:
    secs = 0
    for seg in session.run_segments:
        start = seg.started_at
        end = seg.ended_at or datetime.utcnow()
        if start and end and end > start:
            secs += int((end - start).total_seconds())
    return secs

def get_extrusion_analytics(extruder_id=None, profile_id=None, date_from=None, date_to=None):
    q = ExtrusionSession.query
    if extruder_id:
        q = q.filter(ExtrusionSession.extruder_id == extruder_id)
    if profile_id:
        q = q.filter(ExtrusionSession.profile_id == profile_id)
    if date_from:
        q = q.filter(ExtrusionSession.started_at >= date_from)
    if date_to:
        q = q.filter(ExtrusionSession.started_at < date_to)
    sessions = q.all()
    total_pieces = 0
    total_runtime = 0
    per_profile = {}
    damage_pieces = 0
    for s in sessions:
        rt = _session_runtime_seconds(s)
        total_runtime += rt
        pieces = int(s.pieces_produced or 0)
        total_pieces += pieces
        damage_pieces += s.estimated_damage_pieces
        code = getattr(s.profile, 'code', 'UNK')
        d = per_profile.setdefault(code, {'pieces':0,'sessions':0,'runtime':0})
        d['pieces'] += pieces
        d['sessions'] += 1
        d['runtime'] += rt
    avg_rate = (total_pieces / (total_runtime/3600.0)) if total_runtime>0 else 0
    damage_pct = (damage_pieces/total_pieces*100.0) if total_pieces>0 else 0
    per_profile_list = []
    for code, stats in per_profile.items():
        rate = stats['pieces'] / (stats['runtime']/3600.0) if stats['runtime']>0 else 0
        per_profile_list.append({
            'profile_code': code,
            'pieces': stats['pieces'],
            'sessions': stats['sessions'],
            'runtime_h': round(stats['runtime']/3600.0,2),
            'avg_rate': round(rate,2)
        })
    per_profile_list.sort(key=lambda x: x['pieces'], reverse=True)
    return {
        'total_sessions': len(sessions),
        'total_pieces': total_pieces,
        'runtime_h': round(total_runtime/3600.0,2),
        'avg_rate': round(avg_rate,2),
        'damage_pieces': damage_pieces,
        'damage_pct': round(damage_pct,2),
        'per_profile': per_profile_list
    }
