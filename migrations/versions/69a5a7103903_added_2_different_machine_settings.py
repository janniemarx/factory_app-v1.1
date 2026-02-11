from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "69a5a7103903"
down_revision = "862dfdd3c83b"
branch_labels = None
depends_on = None


# ---------- helpers ----------
def _insp():
    return sa.inspect(op.get_bind())

def _has_column(table: str, col: str) -> bool:
    return any(c["name"] == col for c in _insp().get_columns(table))

def _has_index(table: str, name: str) -> bool:
    return any(ix["name"] == name for ix in _insp().get_indexes(table))

def _has_fk(table: str, name: str) -> bool:
    return any(fk.get("name") == name for fk in _insp().get_foreign_keys(table))

def _col_null_count(table: str, col: str) -> int:
    conn = op.get_bind()
    row = conn.execute(sa.text(f"SELECT COUNT(*) AS n FROM {table} WHERE {col} IS NULL")).fetchone()
    return int(row[0] if row else 0)


def upgrade():
    table = "extruded_profile_settings"

    # 1) Add columns if missing (nullable first)
    with op.batch_alter_table(table) as batch_op:
        if not _has_column(table, "extruder_id"):
            batch_op.add_column(sa.Column("extruder_id", sa.Integer(), nullable=True))
        if not _has_column(table, "extruder_hz"):
            batch_op.add_column(sa.Column("extruder_hz", sa.Float(), nullable=True))
        if not _has_column(table, "co2_hz"):
            batch_op.add_column(sa.Column("co2_hz", sa.Float(), nullable=True))
        if not _has_column(table, "alcohol_hz"):
            batch_op.add_column(sa.Column("alcohol_hz", sa.Float(), nullable=True))
        if not _has_column(table, "oil_hz"):
            batch_op.add_column(sa.Column("oil_hz", sa.Float(), nullable=True))

    # 2) Backfill extruder_id for existing rows, if column exists & has NULLs
    if _has_column(table, "extruder_id") and _col_null_count(table, "extruder_id") > 0:
        conn = op.get_bind()
        ex2 = conn.execute(
            sa.text("SELECT id FROM extruders WHERE code IN ('EXTR-2','Extruder 2') LIMIT 1")
        ).fetchone()
        if not ex2:
            ex2 = conn.execute(sa.text("SELECT id FROM extruders ORDER BY id LIMIT 1")).fetchone()
        if ex2:
            conn.execute(
                sa.text(
                    f"UPDATE {table} SET extruder_id = :eid WHERE extruder_id IS NULL"
                ),
                {"eid": ex2[0]},
            )

    # 3) Drop legacy indexes if present (SQLite-safe)
    op.execute("DROP INDEX IF EXISTS ix_profile_settings_profile_effective")
    op.execute("DROP INDEX IF EXISTS ix_profile_settings_profile_id_created")

    # 4) FK + new indexes (only if missing) + NOT NULL (only if safe)
    with op.batch_alter_table(table) as batch_op:
        if _has_column(table, "extruder_id"):
            if not _has_fk(table, "fk_eps_extruder"):
                batch_op.create_foreign_key(
                    "fk_eps_extruder", "extruders", ["extruder_id"], ["id"]
                )

        if not _has_index(table, "ix_profile_settings_profile_extruder"):
            batch_op.create_index(
                "ix_profile_settings_profile_extruder", ["profile_id", "extruder_id"]
            )
        if not _has_index(table, "ix_profile_settings_profile_extruder_effective"):
            batch_op.create_index(
                "ix_profile_settings_profile_extruder_effective",
                ["profile_id", "extruder_id", "effective_from"],
            )

        # Make NOT NULL only when there are no NULLs left (avoid failures on empty/missing extruders)
        if _has_column(table, "extruder_id") and _col_null_count(table, "extruder_id") == 0:
            batch_op.alter_column("extruder_id", existing_type=sa.Integer(), nullable=False)


def downgrade():
    table = "extruded_profile_settings"

    with op.batch_alter_table(table) as batch_op:
        # Drop FK if present
        if _has_fk(table, "fk_eps_extruder"):
            batch_op.drop_constraint("fk_eps_extruder", type_="foreignkey")

        # Drop new indexes if present
        if _has_index(table, "ix_profile_settings_profile_extruder_effective"):
            batch_op.drop_index("ix_profile_settings_profile_extruder_effective")
        if _has_index(table, "ix_profile_settings_profile_extruder"):
            batch_op.drop_index("ix_profile_settings_profile_extruder")

        # Drop columns if present
        for col in ("oil_hz", "alcohol_hz", "co2_hz", "extruder_hz", "extruder_id"):
            if _has_column(table, col):
                batch_op.drop_column(col)
