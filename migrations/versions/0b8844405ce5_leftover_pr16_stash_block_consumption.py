"""leftover + pr16 stash + block consumption (idempotent, named constraints)"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.exc import OperationalError

# revision identifiers, used by Alembic.
revision = "0b8844405ce5"
down_revision = "482e51842123"
branch_labels = None
depends_on = None


def _insp():
    bind = op.get_bind()
    return sa.inspect(bind)


def _has_table(name: str) -> bool:
    return name in _insp().get_table_names()


def _has_column(table: str, column: str) -> bool:
    cols = [c["name"] for c in _insp().get_columns(table)]
    return column in cols


def _safe_create_index(ix_name: str, table: str, cols: list[str]):
    try:
        op.create_index(ix_name, table, cols)
    except OperationalError as e:
        # SQLite: ignore "already exists"
        if "already exists" not in str(e).lower():
            raise


def upgrade():
    # --- pr16_stash (create if missing) ---
    if not _has_table("pr16_stash"):
        op.create_table(
            "pr16_stash",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("density", sa.Float(), nullable=False),
            sa.Column("material_code", sa.String(length=20), nullable=False),
            sa.Column("kg_remaining", sa.Float(), nullable=False, server_default="0"),
            sa.Column("source_pre_expansion_id", sa.Integer(), sa.ForeignKey("pre_expansions.id")),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("(CURRENT_TIMESTAMP)")),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("(CURRENT_TIMESTAMP)")),
        )
        _safe_create_index("ix_pr16_stash_density", "pr16_stash", ["density"])
        _safe_create_index("ix_pr16_stash_material_code", "pr16_stash", ["material_code"])

    # --- block_material_consumptions (create if missing) ---
    if not _has_table("block_material_consumptions"):
        op.create_table(
            "block_material_consumptions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("block_id", sa.Integer(), sa.ForeignKey("blocks.id", ondelete="CASCADE"), nullable=False),
            sa.Column("source_pre_expansion_id", sa.Integer(), sa.ForeignKey("pre_expansions.id"), nullable=False),
            sa.Column("kg_from_source", sa.Float(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("(CURRENT_TIMESTAMP)")),
        )
        _safe_create_index(
            "ix_block_material_consumptions_block_id",
            "block_material_consumptions",
            ["block_id"],
        )
        _safe_create_index(
            "ix_block_material_consumptions_source_pre_expansion_id",
            "block_material_consumptions",
            ["source_pre_expansion_id"],
        )

    # --- pre_expansions new columns (add only if missing) ---
    with op.batch_alter_table("pre_expansions") as batch:
        if not _has_column("pre_expansions", "leftover_kg"):
            batch.add_column(sa.Column("leftover_kg", sa.Float(), nullable=True))
        if not _has_column("pre_expansions", "leftover_disposition"):
            batch.add_column(sa.Column("leftover_disposition", sa.String(length=20), nullable=True))
        if not _has_column("pre_expansions", "leftover_target_pre_expansion_id"):
            batch.add_column(
                sa.Column(
                    "leftover_target_pre_expansion_id",
                    sa.Integer(),
                    sa.ForeignKey("pre_expansions.id"),
                    nullable=True,
                )
            )

    # Named index for leftover_disposition (ignore if already present)
    _safe_create_index(
        "ix_pre_expansions_leftover_disposition",
        "pre_expansions",
        ["leftover_disposition"],
    )

    # --- UNIQUE on pre_expansion_checklists.pre_expansion_id (give it a NAME) ---
    # In SQLite this recreates the table; name is required in batch mode.
    try:
        with op.batch_alter_table("pre_expansion_checklists") as batch:
            # Only create if not already unique
            # (SQLite doesn’t expose constraints easily; creating twice will raise -> we swallow.)
            batch.create_unique_constraint(
                "uq_pre_expansion_checklists_pre_expansion_id",
                ["pre_expansion_id"],
            )
    except Exception:
        # If it already exists or SQLite complained, ignore.
        pass


def downgrade():
    # Best effort, only drop objects if they exist
    if _has_table("block_material_consumptions"):
        op.drop_index("ix_block_material_consumptions_source_pre_expansion_id", table_name="block_material_consumptions")
        op.drop_index("ix_block_material_consumptions_block_id", table_name="block_material_consumptions")
        op.drop_table("block_material_consumptions")

    if _has_table("pr16_stash"):
        op.drop_index("ix_pr16_stash_material_code", table_name="pr16_stash")
        op.drop_index("ix_pr16_stash_density", table_name="pr16_stash")
        op.drop_table("pr16_stash")

    # columns on pre_expansions
    with op.batch_alter_table("pre_expansions") as batch:
        if _has_column("pre_expansions", "leftover_target_pre_expansion_id"):
            batch.drop_column("leftover_target_pre_expansion_id")
        if _has_column("pre_expansions", "leftover_disposition"):
            batch.drop_column("leftover_disposition")
        if _has_column("pre_expansions", "leftover_kg"):
            batch.drop_column("leftover_kg")

    try:
        op.drop_index("ix_pre_expansions_leftover_disposition", table_name="pre_expansions")
    except Exception:
        pass

    try:
        with op.batch_alter_table("pre_expansion_checklists") as batch:
            batch.drop_constraint("uq_pre_expansion_checklists_pre_expansion_id", type_="unique")
    except Exception:
        pass
