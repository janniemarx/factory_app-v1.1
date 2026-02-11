"""add pr16 qc control changes

Revision ID: dca385b5662c
Revises: 305c12d5fdd3
Create Date: 2025-08-13 15:55:42.529552
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'dca385b5662c'
down_revision = '305c12d5fdd3'
branch_labels = None
depends_on = None


def upgrade():
    # SQLite cannot add NOT NULL columns without a default; set safe defaults.
    with op.batch_alter_table('pr16_quality_checks', schema=None) as batch_op:
        batch_op.add_column(sa.Column('cornices_count_operator', sa.Integer(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('cornices_count_qc',       sa.Integer(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('bad_cornices_count',      sa.Integer(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('good_cornices_count',     sa.Integer(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('is_boxing_ready',         sa.Boolean(), nullable=False, server_default=sa.text('0')))

    # If you want to drop the defaults afterwards, uncomment:
    # with op.batch_alter_table('pr16_quality_checks', schema=None) as batch_op:
    #     batch_op.alter_column('cornices_count_operator', server_default=None)
    #     batch_op.alter_column('cornices_count_qc', server_default=None)
    #     batch_op.alter_column('bad_cornices_count', server_default=None)
    #     batch_op.alter_column('good_cornices_count', server_default=None)
    #     batch_op.alter_column('is_boxing_ready', server_default=None)


def downgrade():
    with op.batch_alter_table('pr16_quality_checks', schema=None) as batch_op:
        batch_op.drop_column('is_boxing_ready')
        batch_op.drop_column('good_cornices_count')
        batch_op.drop_column('bad_cornices_count')
        batch_op.drop_column('cornices_count_qc')
        batch_op.drop_column('cornices_count_operator')
