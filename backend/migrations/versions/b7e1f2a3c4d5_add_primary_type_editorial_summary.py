"""add primary_type and editorial_summary to pois (Places API New)

Revision ID: b7e1f2a3c4d5
Revises: a1b2c3d4e5f6
Create Date: 2026-06-26 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7e1f2a3c4d5'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('pois', sa.Column('primary_type', sa.String(length=100), nullable=True))
    op.add_column('pois', sa.Column('editorial_summary', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('pois', 'editorial_summary')
    op.drop_column('pois', 'primary_type')
