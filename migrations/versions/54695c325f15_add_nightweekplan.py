"""add NightWeekPlan

Revision ID: 54695c325f15
Revises: e4c0a5a6a380
Create Date: 2025-08-27 09:13:23.645773
"""
from alembic import op
import sqlalchemy as sa

revision = '54695c325f15'
down_revision = 'e4c0a5a6a380'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)

    # Create table only if it isn't there already (first run may have created it)
    if not insp.has_table('night_week_plans'):
        op.create_table(
            'night_week_plans',
            sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
            sa.Column('operator_id', sa.Integer(), sa.ForeignKey('operators.id'), nullable=False),
            sa.Column('week_monday', sa.Date(), nullable=False),

            sa.Column('mon', sa.Boolean(), nullable=False, server_default=sa.text("0")),
            sa.Column('tue', sa.Boolean(), nullable=False, server_default=sa.text("0")),
            sa.Column('wed', sa.Boolean(), nullable=False, server_default=sa.text("0")),
            sa.Column('thu', sa.Boolean(), nullable=False, server_default=sa.text("0")),
            sa.Column('fri', sa.Boolean(), nullable=False, server_default=sa.text("0")),
            sa.Column('sat', sa.Boolean(), nullable=False, server_default=sa.text("0")),
            sa.Column('sun', sa.Boolean(), nullable=False, server_default=sa.text("0")),

            sa.Column('notes', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False),

            sa.UniqueConstraint('operator_id', 'week_monday', name='uq_night_plan_operator_week'),
        )

    # Ensure the index exists
    if insp.has_table('night_week_plans'):
        existing = {ix.get('name') for ix in insp.get_indexes('night_week_plans')}
        if 'ix_night_plan_operator_week' not in existing:
            op.create_index(
                'ix_night_plan_operator_week',
                'night_week_plans',
                ['operator_id', 'week_monday'],
                unique=False
            )


def downgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if insp.has_table('night_week_plans'):
        existing = {ix.get('name') for ix in insp.get_indexes('night_week_plans')}
        if 'ix_night_plan_operator_week' in existing:
            op.drop_index('ix_night_plan_operator_week', table_name='night_week_plans')
        op.drop_table('night_week_plans')
