"""fix leave payroll_captured_by -> operators FK

Revision ID: e4c0a5a6a380
Revises: bff3cacee80d
Create Date: 2025-08-25 14:18:24.944381
"""
from alembic import op
import sqlalchemy as sa

revision = 'e4c0a5a6a380'
down_revision = 'bff3cacee80d'
branch_labels = None
depends_on = None


def upgrade():
    # If you know this table exists, keep the next line; otherwise you can delete it.
    # op.drop_table('_alembic_tmp_leave_requests')

    # Backfill created_by_id before making it NOT NULL (prevents failures if any rows are null)
    op.execute("""
        UPDATE leave_requests
        SET created_by_id = COALESCE(created_by_id, approved_by_id)
        WHERE created_by_id IS NULL
    """)

    with op.batch_alter_table('leave_requests', schema=None) as batch_op:
        batch_op.add_column(sa.Column('payroll_captured_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('payroll_captured_by_id', sa.Integer(), nullable=True))
        batch_op.alter_column('created_by_id', existing_type=sa.INTEGER(), nullable=False)
        batch_op.create_foreign_key(
            'fk_leave_payroll_captured_by',   # ← give the constraint a name
            'operators',
            ['payroll_captured_by_id'],
            ['id']
        )

    # REMOVE this whole block; it can’t run without a real name and probably wasn’t intended.
    # with op.batch_alter_table('leftover_cornices', schema=None) as batch_op:
    #     batch_op.drop_constraint(None, type_='foreignkey')


def downgrade():
    with op.batch_alter_table('leave_requests', schema=None) as batch_op:
        batch_op.drop_constraint('fk_leave_payroll_captured_by', type_='foreignkey')
        batch_op.alter_column('created_by_id', existing_type=sa.INTEGER(), nullable=True)
        batch_op.drop_column('payroll_captured_by_id')
        batch_op.drop_column('payroll_captured_at')

    # Do NOT recreate _alembic_tmp_leave_requests or touch leftover_cornices here.
