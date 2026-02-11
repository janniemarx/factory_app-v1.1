"""add effective_from/is_active/created_by to extruded_profile_settings

Revision ID: 8b7e2e6e12ab
Revises: 59fc26cfcf2f
Create Date: 2025-08-14 13:35:00
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '8b7e2e6e12ab'
down_revision = '59fc26cfcf2f'
branch_labels = None
depends_on = None


def upgrade():
    # SQLite-safe: add NOT NULL with a server_default so it doesn't error.
    with op.batch_alter_table('extruded_profile_settings') as batch_op:
        batch_op.add_column(sa.Column(
            'effective_from',
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("(DATETIME('now'))")
        ))
        batch_op.add_column(sa.Column(
            'is_active',
            sa.Boolean(),
            nullable=False,
            server_default='1'
        ))
        batch_op.add_column(sa.Column(
            'created_by_id',
            sa.Integer(),
            nullable=True
        ))

    # Optional FK (SQLite adds via table recreate; batch should handle it on recent Alembic)
    # If your Alembic/SQLite combo complains, you can comment this out — model will still work.
    try:
        with op.batch_alter_table('extruded_profile_settings') as batch_op:
            batch_op.create_foreign_key(
                'fk_eps_created_by', 'operators',
                ['created_by_id'], ['id']
            )
    except Exception:
        # SQLite may ignore/lock this depending on version — safe to skip
        pass

    # New index by (profile_id, effective_from)
    op.create_index(
        'ix_profile_settings_profile_effective',
        'extruded_profile_settings',
        ['profile_id', 'effective_from'],
        unique=False
    )


def downgrade():
    # Drop new index
    op.drop_index('ix_profile_settings_profile_effective', table_name='extruded_profile_settings')

    # Drop FK if it exists (best-effort)
    try:
        with op.batch_alter_table('extruded_profile_settings') as batch_op:
            batch_op.drop_constraint('fk_eps_created_by', type_='foreignkey')
    except Exception:
        pass

    # Drop columns
    with op.batch_alter_table('extruded_profile_settings') as batch_op:
        batch_op.drop_column('created_by_id')
        batch_op.drop_column('is_active')
        batch_op.drop_column('effective_from')
