"""add nightshift boolean

Revision ID: bff3cacee80d
Revises: 97c42be886dc
Create Date: 2025-08-19 14:01:24.162646
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'bff3cacee80d'
down_revision = '97c42be886dc'
branch_labels = None
depends_on = None


def upgrade():
    # Only add the new column. On SQLite, NOT NULL requires a server_default.
    with op.batch_alter_table('operators', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'is_night_shift',
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0")  # SQLite-friendly default for existing rows
            )
        )

    # Drop the default for future inserts; ORM default (False) will apply.
    with op.batch_alter_table('operators', schema=None) as batch_op:
        batch_op.alter_column('is_night_shift', server_default=None)


def downgrade():
    with op.batch_alter_table('operators', schema=None) as batch_op:
        batch_op.drop_column('is_night_shift')
