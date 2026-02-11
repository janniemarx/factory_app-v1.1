"""Added Machines to Moulded3

Revision ID: aa4bbc935e21
Revises: 3a8e067efa62
Create Date: 2025-08-08 06:52:39.234260

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'aa4bbc935e21'
down_revision = '3a8e067efa62'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('moulded_cornice_sessions', schema=None) as batch_op:
        # add the column
        batch_op.add_column(sa.Column('machine_id', sa.Integer(), nullable=True))
        # optional index (your autogen detected one)
        batch_op.create_index('ix_moulded_cornice_sessions_machine_id', ['machine_id'], unique=False)
        # IMPORTANT: give the FK a NAME
        batch_op.create_foreign_key(
            'fk_mcs_machine_id_moulded_machines',   # <-- name it!
            'moulded_machines',                     # referent table
            ['machine_id'],                         # local columns
            ['id']                                  # remote columns
        )


def downgrade():
    with op.batch_alter_table('moulded_cornice_sessions', schema=None) as batch_op:
        # drop FK by name
        batch_op.drop_constraint('fk_mcs_machine_id_moulded_machines', type_='foreignkey')
        batch_op.drop_index('ix_moulded_cornice_sessions_machine_id')
        batch_op.drop_column('machine_id')
        batch_op.drop_column('machine_id')

    # ### end Alembic commands ###
