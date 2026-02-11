"""added_attendance_management_imported

Revision ID: 35719fdde263
Revises: 15312881ade3
Create Date: 2025-08-18 10:43:08.393754
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "35719fdde263"
down_revision = "15312881ade3"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    insp = sa.inspect(conn)

    def has_table(name: str) -> bool:
        try:
            return insp.has_table(name)
        except Exception:
            return False

    def has_index(table: str, idx: str) -> bool:
        try:
            return any(ix.get("name") == idx for ix in insp.get_indexes(table))
        except Exception:
            return False

    # --- attendance_sync_runs ---
    if not has_table("attendance_sync_runs"):
        op.create_table(
            "attendance_sync_runs",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("started_at", sa.DateTime(), nullable=False),
            sa.Column("ended_at", sa.DateTime(), nullable=True),
            sa.Column("status", sa.String(length=8), nullable=False),
            sa.Column("from_date", sa.Date(), nullable=False),
            sa.Column("to_date", sa.Date(), nullable=False),
            sa.Column("fetched_events", sa.Integer(), nullable=False),
            sa.Column("inserted_events", sa.Integer(), nullable=False),
            sa.Column("errors", sa.Text(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
    if not has_index("attendance_sync_runs", "ix_sync_from_to"):
        op.create_index("ix_sync_from_to", "attendance_sync_runs", ["from_date", "to_date"])

    # --- attendance_daily ---
    if not has_table("attendance_daily"):
        op.create_table(
            "attendance_daily",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("operator_id", sa.Integer(), nullable=False),
            sa.Column("emp_no", sa.String(length=64), nullable=True),
            sa.Column("day", sa.Date(), nullable=False),
            sa.Column("first_in", sa.DateTime(), nullable=True),
            sa.Column("last_out", sa.DateTime(), nullable=True),
            sa.Column("worked_seconds", sa.Integer(), nullable=False),
            sa.Column("segment_count", sa.Integer(), nullable=False),
            sa.Column("missing_in", sa.Boolean(), nullable=False),
            sa.Column("missing_out", sa.Boolean(), nullable=False),
            sa.Column("normal_seconds", sa.Integer(), nullable=False),
            sa.Column("ot1_seconds", sa.Integer(), nullable=False),
            sa.Column("ot2_seconds", sa.Integer(), nullable=False),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("computed_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["operator_id"], ["operators.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("operator_id", "day", name="uq_att_daily_operator_day"),
        )
    if not has_index("attendance_daily", "ix_att_daily_day"):
        op.create_index("ix_att_daily_day", "attendance_daily", ["day"])
    if not has_index("attendance_daily", "ix_att_daily_operator_day"):
        op.create_index("ix_att_daily_operator_day", "attendance_daily", ["operator_id", "day"])

    # --- attendance_events ---
    if not has_table("attendance_events"):
        op.create_table(
            "attendance_events",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("operator_id", sa.Integer(), nullable=True),
            sa.Column("emp_no", sa.String(length=64), nullable=True),
            sa.Column("timestamp", sa.DateTime(), nullable=False),
            sa.Column("event_type", sa.String(length=16), nullable=False),
            sa.Column("room_number", sa.Integer(), nullable=True),
            sa.Column("source", sa.String(length=32), nullable=False),
            sa.Column("source_uid", sa.String(length=64), nullable=True),
            sa.Column("ingested_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["operator_id"], ["operators.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("source", "emp_no", "timestamp", "event_type", name="uq_att_event_natural"),
        )
    if not has_index("attendance_events", "ix_att_events_operator_ts"):
        op.create_index("ix_att_events_operator_ts", "attendance_events", ["operator_id", "timestamp"])
    if not has_index("attendance_events", "ix_att_events_ts"):
        op.create_index("ix_att_events_ts", "attendance_events", ["timestamp"])

    # --- leave_requests ---
    if not has_table("leave_requests"):
        op.create_table(
            "leave_requests",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("operator_id", sa.Integer(), nullable=False),
            sa.Column("leave_type", sa.String(length=20), nullable=False),
            sa.Column("start_date", sa.Date(), nullable=False),
            sa.Column("end_date", sa.Date(), nullable=False),
            sa.Column("hours_per_day", sa.Float(), nullable=True),
            sa.Column("status", sa.String(length=16), nullable=False),
            sa.Column("requested_at", sa.DateTime(), nullable=False),
            sa.Column("approved_by_id", sa.Integer(), nullable=True),
            sa.Column("approved_at", sa.DateTime(), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.ForeignKeyConstraint(["approved_by_id"], ["operators.id"]),
            sa.ForeignKeyConstraint(["operator_id"], ["operators.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    if not has_index("leave_requests", "ix_leave_operator_start"):
        op.create_index("ix_leave_operator_start", "leave_requests", ["operator_id", "start_date"])
    if not has_index("leave_requests", "ix_leave_status"):
        op.create_index("ix_leave_status", "leave_requests", ["status"])

    # --- overtime_requests ---
    if not has_table("overtime_requests"):
        op.create_table(
            "overtime_requests",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("operator_id", sa.Integer(), nullable=False),
            sa.Column("day", sa.Date(), nullable=False),
            sa.Column("ot_type", sa.String(length=8), nullable=False),
            sa.Column("hours", sa.Float(), nullable=False),
            sa.Column("reason", sa.Text(), nullable=True),
            sa.Column("status", sa.String(length=16), nullable=False),
            sa.Column("requested_at", sa.DateTime(), nullable=False),
            sa.Column("approved_by_id", sa.Integer(), nullable=True),
            sa.Column("approved_at", sa.DateTime(), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.ForeignKeyConstraint(["approved_by_id"], ["operators.id"]),
            sa.ForeignKeyConstraint(["operator_id"], ["operators.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("operator_id", "day", "ot_type", name="uq_ot_operator_day_type"),
        )
    if not has_index("overtime_requests", "ix_ot_operator_day"):
        op.create_index("ix_ot_operator_day", "overtime_requests", ["operator_id", "day"])
    if not has_index("overtime_requests", "ix_ot_status_day"):
        op.create_index("ix_ot_status_day", "overtime_requests", ["status", "day"])

    # --- work_schedules ---
    if not has_table("work_schedules"):
        op.create_table(
            "work_schedules",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=80), nullable=False),
            sa.Column("is_default", sa.Boolean(), nullable=False),
            sa.Column("room_number", sa.Integer(), nullable=True),
            sa.Column("operator_id", sa.Integer(), nullable=True),
            sa.Column("day_start", sa.Time(), nullable=False),
            sa.Column("day_end", sa.Time(), nullable=False),
            sa.Column("lunch_minutes", sa.Integer(), nullable=False),
            sa.Column("weekly_normal_seconds", sa.Integer(), nullable=False),
            sa.Column("ot_round_minutes", sa.Integer(), nullable=False),
            sa.Column("round_15_to_zero", sa.Boolean(), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["operator_id"], ["operators.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    if not has_index("work_schedules", "ix_sched_default"):
        op.create_index("ix_sched_default", "work_schedules", ["is_default"])
    if not has_index("work_schedules", "ix_sched_room_enabled"):
        op.create_index("ix_sched_room_enabled", "work_schedules", ["room_number", "enabled"])

    # --- DO NOT drop unnamed FK on SQLite; drop only if named elsewhere ---
    if conn.dialect.name != "sqlite":
        for fk in sa.inspect(conn).get_foreign_keys("leftover_cornices"):
            if (
                set(fk.get("constrained_columns", [])) == {"profile_code"}
                and fk.get("referred_table") == "profiles"
                and fk.get("name")
            ):
                op.drop_constraint(fk["name"], "leftover_cornices", type_="foreignkey")


def downgrade():
    # (Standard drops; no guards needed if you don’t plan to downgrade on SQLite)
    with op.batch_alter_table("work_schedules", schema=None) as batch_op:
        batch_op.drop_index("ix_sched_room_enabled")
        batch_op.drop_index("ix_sched_default")
    op.drop_table("work_schedules")

    with op.batch_alter_table("overtime_requests", schema=None) as batch_op:
        batch_op.drop_index("ix_ot_status_day")
        batch_op.drop_index("ix_ot_operator_day")
    op.drop_table("overtime_requests")

    with op.batch_alter_table("leave_requests", schema=None) as batch_op:
        batch_op.drop_index("ix_leave_status")
        batch_op.drop_index("ix_leave_operator_start")
    op.drop_table("leave_requests")

    with op.batch_alter_table("attendance_events", schema=None) as batch_op:
        batch_op.drop_index("ix_att_events_ts")
        batch_op.drop_index("ix_att_events_operator_ts")
    op.drop_table("attendance_events")

    with op.batch_alter_table("attendance_daily", schema=None) as batch_op:
        batch_op.drop_index("ix_att_daily_operator_day")
        batch_op.drop_index("ix_att_daily_day")
    op.drop_table("attendance_daily")

    with op.batch_alter_table("attendance_sync_runs", schema=None) as batch_op:
        batch_op.drop_index("ix_sync_from_to")
    op.drop_table("attendance_sync_runs")
