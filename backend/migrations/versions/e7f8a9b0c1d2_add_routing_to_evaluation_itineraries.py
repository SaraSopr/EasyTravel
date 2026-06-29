"""add routing axis to evaluation_itineraries

Adds the ``routing`` column so the evaluation harness can store the 2×2 ablation
({greedy, toptw} × {estimated, real}). Existing rows were generated with real
routing, so they default to "real".

Revision ID: e7f8a9b0c1d2
Revises: c1d2e3f4a5b6
Create Date: 2026-06-29 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e7f8a9b0c1d2'
down_revision: Union[str, None] = 'c1d2e3f4a5b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'evaluation_itineraries',
        sa.Column('routing', sa.String(length=10), nullable=False, server_default='real'),
    )
    # Drop the server_default once existing rows are backfilled — new rows set it
    # explicitly from the harness.
    op.alter_column('evaluation_itineraries', 'routing', server_default=None)


def downgrade() -> None:
    op.drop_column('evaluation_itineraries', 'routing')
