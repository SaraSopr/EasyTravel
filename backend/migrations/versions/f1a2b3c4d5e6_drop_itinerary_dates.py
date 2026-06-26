"""drop itinerary dates

Revision ID: f1a2b3c4d5e6
Revises: a1b2c3d4e5f6
Create Date: 2026-06-26 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column('itineraries', 'start_date')
    op.drop_column('itineraries', 'end_date')


def downgrade() -> None:
    op.add_column('itineraries', sa.Column('start_date', sa.Date(), nullable=False))
    op.add_column('itineraries', sa.Column('end_date', sa.Date(), nullable=False))