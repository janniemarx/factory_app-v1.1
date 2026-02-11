# migrations/versions/2e897a9e0ecc_made_changes_extrusion_boxing.py
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "2e897a9e0ecc"
down_revision = "69a5a7103903"
branch_labels = None
depends_on = None


# ---------- small helpers ----------
def _insp():
    return sa.inspect(op.get_bind())

def _has_column(table: str, col: str) -> bool:
    return any(c["name"] == col for c in _insp().get_columns(table))

def _has_index(table: str, name: str) -> bool:
    return any(ix["name"] == name for ix in _insp().get_indexes(table))

def _has_fk(table: str, name: str) -> bool:
    return any(fk.get("name") == name for fk in _insp().get_foreign_keys(table))

def _col_null_count(table: str, col: str) -> int:
    row = op.get_bind().execute(sa.text(f"SELECT COUNT(*) FROM {table} WHERE {col} IS NULL")).fetchone()
    return int(row[0]) if row else 0


def upgrade():
    # --- boxing_sessions: add source_type, extrusion_session_id, relax cutting_production_id, add FK ---
    table = "boxing_sessions"
    with op.batch_alter_table(table) as batch:
        if not _has_column(table, "source_type"):
            # add nullable, backfill, then enforce NOT NULL
            batch.add_column(sa.Column("source_type", sa.String(length=20), nullable=True, server_default="cutting"))
        if not _has_column(table, "extrusion_session_id"):
            batch.add_column(sa.Column("extrusion_session_id", sa.Integer(), nullable=True))
        # make cutting_production_id nullable to allow extrusion source
        batch.alter_column("cutting_production_id", existing_type=sa.Integer(), nullable=True)

    if _has_column(table, "source_type"):
        op.execute(sa.text("UPDATE boxing_sessions SET source_type = 'cutting' WHERE source_type IS NULL"))
        with op.batch_alter_table(table) as batch:
            batch.alter_column("source_type", existing_type=sa.String(length=20), nullable=False)

    # create FK with an explicit name (required in batch mode / SQLite)
    if _has_column(table, "extrusion_session_id") and not _has_fk(table, "fk_boxing_extrusion_session"):
        with op.batch_alter_table(table) as batch:
            batch.create_foreign_key(
                "fk_boxing_extrusion_session",
                "extrusion_sessions",
                ["extrusion_session_id"],
                ["id"],
            )

    # --- extruded_profile_settings: ensure indexes/FK; tighten NOT NULL if safe ---
    eps = "extruded_profile_settings"
    # indexes
    if not _has_index(eps, "ix_profile_settings_profile_extruder"):
        with op.batch_alter_table(eps) as batch:
            batch.create_index("ix_profile_settings_profile_extruder", ["profile_id", "extruder_id"])
    if not _has_index(eps, "ix_profile_settings_profile_extruder_effective"):
        with op.batch_alter_table(eps) as batch:
            batch.create_index(
                "ix_profile_settings_profile_extruder_effective",
                ["profile_id", "extruder_id", "effective_from"],
            )
    # FK to extruders
    if _has_column(eps, "extruder_id") and not _has_fk(eps, "fk_eps_extruder"):
        with op.batch_alter_table(eps) as batch:
            batch.create_foreign_key("fk_eps_extruder", "extruders", ["extruder_id"], ["id"])
    # NOT NULL when safe
    if _has_column(eps, "extruder_id") and _col_null_count(eps, "extruder_id") == 0:
        with op.batch_alter_table(eps) as batch:
            batch.alter_column("extruder_id", existing_type=sa.Integer(), nullable=False)

    # --- extrusion_sessions: add is_boxing_ready ---
    es = "extrusion_sessions"
    if not _has_column(es, "is_boxing_ready"):
        with op.batch_alter_table(es) as batch:
            batch.add_column(sa.Column("is_boxing_ready", sa.Boolean(), nullable=False, server_default="0"))

    # --- leftover_cornices: widen profile_code to length 20; skip FK drop if unnamed on SQLite ---
    lc = "leftover_cornices"
    if _has_column(lc, "profile_code"):
        with op.batch_alter_table(lc) as batch:
            batch.alter_column(
                "profile_code",
                existing_type=sa.String(length=10),
                type_=sa.String(length=20),
                existing_nullable=False,
            )

        # Attempt to drop FK to profiles.code only if it has a name (SQLite often returns None)
        insp = _insp()
        for fk in insp.get_foreign_keys(lc) or []:
            if fk.get("referred_table") == "profiles" and "profile_code" in (fk.get("constrained_columns") or []):
                name = fk.get("name")
                if name:  # only drop when we actually have a name
                    with op.batch_alter_table(lc) as batch:
                        batch.drop_constraint(name, type_="foreignkey")
                break  # only one expected


def downgrade():
    # --- leftover_cornices: revert width, can't easily restore FK name on SQLite ---
    lc = "leftover_cornices"
    if _has_column(lc, "profile_code"):
        with op.batch_alter_table(lc) as batch:
            batch.alter_column(
                "profile_code",
                existing_type=sa.String(length=20),
                type_=sa.String(length=10),
                existing_nullable=False,
            )
        # NOTE: FK to profiles.code is not restored here because the original name may be unknown on SQLite.

    # --- extrusion_sessions: drop is_boxing_ready ---
    es = "extrusion_sessions"
    if _has_column(es, "is_boxing_ready"):
        with op.batch_alter_table(es) as batch:
            batch.drop_column("is_boxing_ready")

    # --- extruded_profile_settings: relax NOT NULL, drop FK/indexes if present ---
    eps = "extruded_profile_settings"
    if _has_fk(eps, "fk_eps_extruder"):
        with op.batch_alter_table(eps) as batch:
            batch.drop_constraint("fk_eps_extruder", type_="foreignkey")
    if _has_index(eps, "ix_profile_settings_profile_extruder_effective"):
        with op.batch_alter_table(eps) as batch:
            batch.drop_index("ix_profile_settings_profile_extruder_effective")
    if _has_index(eps, "ix_profile_settings_profile_extruder"):
        with op.batch_alter_table(eps) as batch:
            batch.drop_index("ix_profile_settings_profile_extruder")
    if _has_column(eps, "extruder_id"):
        with op.batch_alter_table(eps) as batch:
            batch.alter_column("extruder_id", existing_type=sa.Integer(), nullable=True)

    # --- boxing_sessions: drop FK/columns, restore NOT NULL on cutting_production_id ---
    bs = "boxing_sessions"
    if _has_fk(bs, "fk_boxing_extrusion_session"):
        with op.batch_alter_table(bs) as batch:
            batch.drop_constraint("fk_boxing_extrusion_session", type_="foreignkey")
    with op.batch_alter_table(bs) as batch:
        if _has_column(bs, "extrusion_session_id"):
            batch.drop_column("extrusion_session_id")
        if _has_column(bs, "source_type"):
            batch.drop_column("source_type")
        batch.alter_column("cutting_production_id", existing_type=sa.Integer(), nullable=False)
