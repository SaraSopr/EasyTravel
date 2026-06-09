"""rename_city_experience_place_id

Revision ID: 6d1c2b8f4e90
Revises: 4a3b9f1d2c7e
Create Date: 2026-03-26 10:35:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '6d1c2b8f4e90'
down_revision: Union[str, None] = '4a3b9f1d2c7e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('city_experiences', 'place_id', new_column_name='google_place_id')


def downgrade() -> None:
    op.alter_column('city_experiences', 'google_place_id', new_column_name='place_id')
