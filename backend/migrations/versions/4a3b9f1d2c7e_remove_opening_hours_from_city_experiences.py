"""remove_opening_hours_from_city_experiences

Revision ID: 4a3b9f1d2c7e
Revises: 8475178a6524
Create Date: 2026-03-25 16:25:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '4a3b9f1d2c7e'
down_revision: Union[str, None] = '8475178a6524'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column('city_experiences', 'opening_hours')


def downgrade() -> None:
    op.add_column('city_experiences', sa.Column('opening_hours', postgresql.JSON(astext_type=sa.Text()), nullable=True))
