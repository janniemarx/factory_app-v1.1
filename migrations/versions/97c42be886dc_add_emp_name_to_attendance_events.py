"""add emp_name to attendance_events

Revision ID: 97c42be886dc
Revises: 4e4b764d537b
Create Date: 2025-08-19 08:16:01.049131
"""
from alembic import op
import sqlalchemy as sa


revision = '97c42be886dc'
down_revision = '4e4b764d537b'
branch_labels = None
depends_on = None


def _has_column(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = [c["name"] for c in insp.get_columns(table_name)]
    return column_name in cols


def upgrade():
    # Only add the column if it isn't already there (SQLite may have applied it earlier)
    if not _has_column('attendance_events', 'emp_name'):
        with op.batch_alter_table('attendance_events', schema=None) as batch_op:
            batch_op.add_column(sa.Column('emp_name', sa.String(length=128), nullable=True))


def downgrade():
    # Only drop if it exists
    if _has_column('attendance_events', 'emp_name'):
        with op.batch_alter_table('attendance_events', schema=None) as batch_op:
            batch_op.drop_column('emp_name')
