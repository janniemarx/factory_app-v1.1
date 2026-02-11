"""maintenance module tables

Revision ID: 99284f6723fc
Revises: 2e897a9e0ecc
Create Date: 2025-08-18 08:22:16.758117
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "99284f6723fc"
down_revision = "2e897a9e0ecc"
branch_labels = None
depends_on = None


# ---------- Helpers for idempotent ops ----------
def _insp():
    return sa.inspect(op.get_bind())

def _has_table(name: str) -> bool:
    return name in _insp().get_table_names()

def _has_index(table: str, index_name: str) -> bool:
    try:
        return any(ix.get("name") == index_name for ix in _insp().get_indexes(table))
    except Exception:
        return False

def _column_is_not_null(table: str, col: str) -> bool:
    for c in _insp().get_columns(table):
        if c["name"] == col:
            # SQLAlchemy reports True when nullable; we want NOT NULL
            return not c.get("nullable", True)
    return False  # if unknown, assume nullable so we try to alter


def upgrade():
    # ---------- Maintenance tables ----------
    if not _has_table("maintenance_jobs"):
        op.create_table(
            "maintenance_jobs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("title", sa.String(length=200), nullable=False),
            sa.Column("description", sa.Text()),
            sa.Column("location", sa.String(length=120)),
            sa.Column("asset_code", sa.String(length=50)),
            sa.Column("reported_by_id", sa.Integer(), sa.ForeignKey("operators.id")),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("assigned_to_id", sa.Integer(), sa.ForeignKey("operators.id")),
            sa.Column("assigned_at", sa.DateTime()),
            sa.Column("priority", sa.String(length=10), nullable=False, server_default="normal"),
            sa.Column("category", sa.String(length=20), nullable=False, server_default="general"),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="open"),
            sa.Column("total_work_seconds", sa.Integer(), nullable=False, server_default="0"),
        )

    if not _has_index("maintenance_jobs", "ix_maint_jobs_status"):
        op.create_index("ix_maint_jobs_status", "maintenance_jobs", ["status"])
    if not _has_index("maintenance_jobs", "ix_maint_jobs_priority"):
        op.create_index("ix_maint_jobs_priority", "maintenance_jobs", ["priority"])
    if not _has_index("maintenance_jobs", "ix_maint_jobs_assigned"):
        op.create_index("ix_maint_jobs_assigned", "maintenance_jobs", ["assigned_to_id", "status"])
    if not _has_index("maintenance_jobs", "ix_maint_jobs_created_at"):
        op.create_index("ix_maint_jobs_created_at", "maintenance_jobs", ["created_at"])

    if not _has_table("maintenance_work_sessions"):
        op.create_table(
            "maintenance_work_sessions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("job_id", sa.Integer(), sa.ForeignKey("maintenance_jobs.id"), nullable=False),
            sa.Column("technician_id", sa.Integer(), sa.ForeignKey("operators.id"), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="in_progress"),
            sa.Column("started_at", sa.DateTime(), nullable=False),
            sa.Column("ended_at", sa.DateTime()),
            sa.Column("is_paused", sa.Boolean(), nullable=False, server_default=sa.text("0")),
            sa.Column("pause_start", sa.DateTime()),
            sa.Column("total_work_seconds", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("closing_summary", sa.Text()),
        )

    if not _has_index("maintenance_work_sessions", "ix_maint_sessions_job"):
        op.create_index("ix_maint_sessions_job", "maintenance_work_sessions", ["job_id"])
    if not _has_index("maintenance_work_sessions", "ix_maint_sessions_tech_status"):
        op.create_index("ix_maint_sessions_tech_status", "maintenance_work_sessions", ["technician_id", "status"])
    if not _has_index("maintenance_work_sessions", "ix_maint_sessions_started"):
        op.create_index("ix_maint_sessions_started", "maintenance_work_sessions", ["started_at"])

    if not _has_table("maintenance_work_segments"):
        op.create_table(
            "maintenance_work_segments",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("session_id", sa.Integer(), sa.ForeignKey("maintenance_work_sessions.id"), nullable=False),
            sa.Column("started_at", sa.DateTime(), nullable=False),
            sa.Column("ended_at", sa.DateTime()),
        )

    if not _has_index("maintenance_work_segments", "ix_maint_segments_session"):
        op.create_index("ix_maint_segments_session", "maintenance_work_segments", ["session_id"])
    if not _has_index("maintenance_work_segments", "ix_maint_segments_started"):
        op.create_index("ix_maint_segments_started", "maintenance_work_segments", ["started_at"])

    if not _has_table("maintenance_step_logs"):
        op.create_table(
            "maintenance_step_logs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("session_id", sa.Integer(), sa.ForeignKey("maintenance_work_sessions.id"), nullable=False),
            sa.Column("timestamp", sa.DateTime(), nullable=False),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column("added_by_id", sa.Integer(), sa.ForeignKey("operators.id")),
        )

    if not _has_index("maintenance_step_logs", "ix_maint_steps_session_time"):
        op.create_index("ix_maint_steps_session_time", "maintenance_step_logs", ["session_id", "timestamp"])

    if not _has_table("maintenance_reviews"):
        op.create_table(
            "maintenance_reviews",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("job_id", sa.Integer(), sa.ForeignKey("maintenance_jobs.id"), nullable=False),
            sa.Column("reviewed_by_id", sa.Integer(), sa.ForeignKey("operators.id"), nullable=False),
            sa.Column("reviewed_at", sa.DateTime(), nullable=False),
            sa.Column("decision", sa.String(length=20), nullable=False, server_default="approved"),
            sa.Column("notes", sa.Text()),
        )

    if not _has_index("maintenance_reviews", "ix_maint_reviews_job"):
        op.create_index("ix_maint_reviews_job", "maintenance_reviews", ["job_id"])
    if not _has_index("maintenance_reviews", "ix_maint_reviews_when"):
        op.create_index("ix_maint_reviews_when", "maintenance_reviews", ["reviewed_at"])

    # ---------- Fix for NOT NULL extruder_id on extruded_profile_settings ----------
    conn = op.get_bind()
    # Ensure at least one extruder exists
    conn.execute(sa.text("""
        INSERT INTO extruders (code, name, is_active)
        SELECT 'EXTR-1','Extruder 1',1
        WHERE NOT EXISTS (SELECT 1 FROM extruders)
    """))

    # Backfill any NULL extruder_id
    ex2 = conn.execute(sa.text(
        "SELECT id FROM extruders WHERE code IN ('EXTR-2','Extruder 2') ORDER BY id LIMIT 1"
    )).fetchone()
    if not ex2:
        ex2 = conn.execute(sa.text("SELECT id FROM extruders ORDER BY id LIMIT 1")).fetchone()
    if ex2:
        conn.execute(
            sa.text("UPDATE extruded_profile_settings SET extruder_id = :eid WHERE extruder_id IS NULL"),
            {"eid": ex2[0]},
        )

    # Enforce NOT NULL only if currently nullable
    if not _column_is_not_null("extruded_profile_settings", "extruder_id"):
        with op.batch_alter_table("extruded_profile_settings", schema=None) as batch_op:
            batch_op.alter_column("extruder_id", existing_type=sa.Integer(), nullable=False)


def downgrade():
    # Roll back maintenance module (drop indexes if present, then tables)
    for name in ("ix_maint_reviews_when", "ix_maint_reviews_job"):
        if _has_index("maintenance_reviews", name):
            op.drop_index(name, table_name="maintenance_reviews")
    if _has_table("maintenance_reviews"):
        op.drop_table("maintenance_reviews")

    if _has_index("maintenance_step_logs", "ix_maint_steps_session_time"):
        op.drop_index("ix_maint_steps_session_time", table_name="maintenance_step_logs")
    if _has_table("maintenance_step_logs"):
        op.drop_table("maintenance_step_logs")

    for name in ("ix_maint_segments_started", "ix_maint_segments_session"):
        if _has_index("maintenance_work_segments", name):
            op.drop_index(name, table_name="maintenance_work_segments")
    if _has_table("maintenance_work_segments"):
        op.drop_table("maintenance_work_segments")

    for name in ("ix_maint_sessions_started", "ix_maint_sessions_tech_status", "ix_maint_sessions_job"):
        if _has_index("maintenance_work_sessions", name):
            op.drop_index(name, table_name="maintenance_work_sessions")
    if _has_table("maintenance_work_sessions"):
        op.drop_table("maintenance_work_sessions")

    for name in ("ix_maint_jobs_created_at", "ix_maint_jobs_assigned", "ix_maint_jobs_priority", "ix_maint_jobs_status"):
        if _has_index("maintenance_jobs", name):
            op.drop_index(name, table_name="maintenance_jobs")
    if _has_table("maintenance_jobs"):
        op.drop_table("maintenance_jobs")

    # We intentionally leave extruded_profile_settings.extruder_id as NOT NULL on downgrade.
