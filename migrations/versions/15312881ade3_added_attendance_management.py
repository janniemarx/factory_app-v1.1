"""added_attendance_management

Revision ID: 15312881ade3
Revises: 99284f6723fc
Create Date: 2025-08-18 10:37:18.257543

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '15312881ade3'
down_revision = '99284f6723fc'
branch_labels = None
depends_on = None


def upgrade():
    # --- Robust handling of the old leftover_cornices FK ---
    # Skip on SQLite (unnamed FK + table rebuild required). On other DBs, drop only if we can find a named FK.
    conn = op.get_bind()
    if conn.dialect.name != "sqlite":
        insp = sa.inspect(conn)
        for fk in insp.get_foreign_keys("leftover_cornices"):
            if (
                set(fk.get("constrained_columns", [])) == {"profile_code"}
                and fk.get("referred_table") == "profiles"
                and fk.get("name")
            ):
                op.drop_constraint(fk["name"], "leftover_cornices", type_="foreignkey")

    # --- Operators: attendance fields ---
    with op.batch_alter_table('operators', schema=None) as batch_op:
        batch_op.add_column(sa.Column('emp_no', sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column('room_number', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('birthday', sa.Date(), nullable=True))
        batch_op.create_index(batch_op.f('ix_operators_emp_no'), ['emp_no'], unique=True)


def downgrade():
    # --- Operators: remove attendance fields ---
    with op.batch_alter_table('operators', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_operators_emp_no'))
        batch_op.drop_column('birthday')
        batch_op.drop_column('room_number')
        batch_op.drop_column('emp_no')

    # NOTE: We intentionally do NOT recreate the old unnamed FK on leftover_cornices here.
    # If you later decide to manage that FK, do it in a dedicated migration with a table rebuild for SQLite.
