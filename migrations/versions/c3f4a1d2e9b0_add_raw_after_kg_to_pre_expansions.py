"""Add raw_after_kg to pre_expansions (idempotent)"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "c3f4a1d2e9b0"
down_revision = "246898935dd4"
branch_labels = None
depends_on = None


def _insp():
    bind = op.get_bind()
    return sa.inspect(bind)


def _has_column(table: str, column: str) -> bool:
    cols = [c["name"] for c in _insp().get_columns(table)]
    return column in cols


def upgrade():
    with op.batch_alter_table("pre_expansions") as batch:
        if not _has_column("pre_expansions", "raw_after_kg"):
            batch.add_column(sa.Column("raw_after_kg", sa.Float(), nullable=True))


def downgrade():
    # Best-effort only; SQLite may not support DROP COLUMN depending on version.
    try:
        with op.batch_alter_table("pre_expansions") as batch:
            if _has_column("pre_expansions", "raw_after_kg"):
                batch.drop_column("raw_after_kg")
    except Exception:
        pass
