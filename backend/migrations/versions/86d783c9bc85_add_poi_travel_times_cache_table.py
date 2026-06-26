"""add poi_travel_times cache table

Revision ID: 86d783c9bc85
Revises: 10e0bb02e91f
Create Date: 2026-06-13 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '86d783c9bc85'
down_revision: Union[str, None] = '10e0bb02e91f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'poi_travel_times',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('origin_poi_id', sa.Uuid(), nullable=False),
        sa.Column('dest_poi_id', sa.Uuid(), nullable=False),
        sa.Column('mode', sa.String(length=10), nullable=False),
        sa.Column('seconds', sa.Integer(), nullable=False),
        sa.Column('meters', sa.Integer(), nullable=False),
        sa.Column('source', sa.String(length=20), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['origin_poi_id'], ['pois.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['dest_poi_id'], ['pois.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('origin_poi_id', 'dest_poi_id', 'mode', name='uq_travel_origin_dest_mode'),
    )
    op.create_index('ix_poi_travel_times_origin', 'poi_travel_times', ['origin_poi_id'])


def downgrade() -> None:
    op.drop_index('ix_poi_travel_times_origin', table_name='poi_travel_times')
    op.drop_table('poi_travel_times')
