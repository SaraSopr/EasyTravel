"""merge_branches

Revision ID: c499c6dd9103
Revises: 386a97b0d8fd, 6d1c2b8f4e90
Create Date: 2026-03-26 20:52:59.878762

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c499c6dd9103'
down_revision: Union[str, None] = ('386a97b0d8fd', '6d1c2b8f4e90')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
