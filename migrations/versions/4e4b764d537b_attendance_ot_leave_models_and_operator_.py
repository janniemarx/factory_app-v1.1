from alembic import op
import sqlalchemy as sa

revision = "4e4b764d537b"
down_revision = "35719fdde263"
branch_labels = None
depends_on = None


def upgrade():
    # ---- leave_requests: replace requested_at with created_at + created_by_id(FK) ----
    with op.batch_alter_table("leave_requests", schema=None) as b:
        b.add_column(sa.Column("created_at", sa.DateTime(), nullable=False,
                               server_default=sa.text("(DATETIME('now'))")))
        b.add_column(sa.Column("created_by_id", sa.Integer(), nullable=True))
        b.create_foreign_key(
            "fk_leave_created_by",
            "operators",
            ["created_by_id"],
            ["id"],
        )
        # remove old column
        b.drop_column("requested_at")

    # ---- overtime_requests: add proposed_hours, created_at, created_by_id(FK), daily_id(FK), source ----
    with op.batch_alter_table("overtime_requests", schema=None) as b:
        b.add_column(sa.Column("proposed_hours", sa.Float(), nullable=False, server_default="0"))
        b.add_column(sa.Column("created_at", sa.DateTime(), nullable=False,
                               server_default=sa.text("(DATETIME('now'))")))
        b.add_column(sa.Column("created_by_id", sa.Integer(), nullable=True))
        b.add_column(sa.Column("daily_id", sa.Integer(), nullable=True))
        b.add_column(sa.Column("source", sa.String(length=16), nullable=False, server_default="manual"))

        b.create_foreign_key(
            "fk_ot_created_by",
            "operators",
            ["created_by_id"],
            ["id"],
        )
        b.create_foreign_key(
            "fk_ot_daily",
            "attendance_daily",
            ["daily_id"],
            ["id"],
        )

        # remove old column
        b.drop_column("requested_at")

    # Optional: drop server defaults after backfill so app controls values going forward
    with op.batch_alter_table("leave_requests", schema=None) as b:
        b.alter_column("created_at", server_default=None)

    with op.batch_alter_table("overtime_requests", schema=None) as b:
        b.alter_column("created_at", server_default=None)
        b.alter_column("proposed_hours", server_default=None)
        b.alter_column("source", server_default=None)


def downgrade():
    # restore overtime_requests to prior state
    with op.batch_alter_table("overtime_requests", schema=None) as b:
        b.add_column(sa.Column("requested_at", sa.DateTime(), nullable=False,
                               server_default=sa.text("(DATETIME('now'))")))
        b.drop_constraint("fk_ot_daily", type_="foreignkey")
        b.drop_constraint("fk_ot_created_by", type_="foreignkey")
        b.drop_column("source")
        b.drop_column("daily_id")
        b.drop_column("created_by_id")
        b.drop_column("created_at")
        b.drop_column("proposed_hours")
        b.alter_column("requested_at", server_default=None)

    # restore leave_requests to prior state
    with op.batch_alter_table("leave_requests", schema=None) as b:
        b.add_column(sa.Column("requested_at", sa.DateTime(), nullable=False,
                               server_default=sa.text("(DATETIME('now'))")))
        b.drop_constraint("fk_leave_created_by", type_="foreignkey")
        b.drop_column("created_by_id")
        b.drop_column("created_at")
        b.alter_column("requested_at", server_default=None)
