from datetime import datetime
from models.maintenance import MaintenanceJob, MaintenanceWorkSession, MaintenanceWorkSegment

def _segment_seconds(seg: MaintenanceWorkSegment) -> int:
    start = seg.started_at
    end = seg.ended_at or datetime.utcnow()
    if start and end and end > start:
        return int((end - start).total_seconds())
    return 0

def _session_active_seconds(sess: MaintenanceWorkSession) -> int:
    return sum(_segment_seconds(seg) for seg in sess.segments)

def get_maintenance_analytics(technician_id=None, status=None, date_from=None, date_to=None):
    q = MaintenanceJob.query
    if status:
        q = q.filter(MaintenanceJob.status == status)
    if date_from:
        q = q.filter(MaintenanceJob.created_at >= date_from)
    if date_to:
        q = q.filter(MaintenanceJob.created_at < date_to)
    jobs = q.all()
    if technician_id:
        jobs = [j for j in jobs if any(s.technician_id == technician_id for s in j.sessions)]
    total = len(jobs)
    status_counts = {}
    mttr_seconds = []
    backlog_age_days = []
    from datetime import datetime as _dt
    now = _dt.utcnow()
    for job in jobs:
        status_counts[job.status] = status_counts.get(job.status, 0) + 1
        if job.status == 'closed' and job.sessions:
            # MTTR: first accept/started to closed (ended_at of last session or updated_at if later)
            first_start = min(s.started_at for s in job.sessions if s.started_at)
            last_end = max((s.ended_at or now) for s in job.sessions)
            mttr_seconds.append(int((last_end - first_start).total_seconds()))
        if job.status not in ('closed','rejected'):
            age = (now - job.created_at).total_seconds()/86400.0
            backlog_age_days.append(age)
    mttr_h = (sum(mttr_seconds)/3600.0/len(mttr_seconds)) if mttr_seconds else 0
    avg_backlog_age = (sum(backlog_age_days)/len(backlog_age_days)) if backlog_age_days else 0
    status_list = sorted([{'status':k,'count':v} for k,v in status_counts.items()], key=lambda x: x['status'])
    return {
        'total_jobs': total,
        'status_breakdown': status_list,
        'mttr_h': round(mttr_h,2),
        'avg_backlog_age_d': round(avg_backlog_age,2),
    }
