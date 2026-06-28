"""add pois.description (LLM-generated) and merge heads

Adds a dedicated ``description`` column for our own (LLM-generated) place
descriptions, kept separate from Google's ``editorial_summary`` for provenance.
Moves any value currently sitting in ``editorial_summary`` into ``description``
(those were LLM-generated, since Google's summary was empty everywhere) and
clears ``editorial_summary`` back to its Google-only state.

Also merges the two parallel heads (b7e1f2a3c4d5, f1a2b3c4d5e6).

Revision ID: c1d2e3f4a5b6
Revises: b7e1f2a3c4d5, f1a2b3c4d5e6
Create Date: 2026-06-27 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c1d2e3f4a5b6'
down_revision: Union[str, Sequence[str], None] = ('b7e1f2a3c4d5', 'f1a2b3c4d5e6')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('pois', sa.Column('description', sa.Text(), nullable=True))
    # Our generated summaries are the only non-null editorial_summary values
    # (Google's were empty) — move them to the dedicated column.
    op.execute(
        "UPDATE pois SET description = editorial_summary, editorial_summary = NULL "
        "WHERE editorial_summary IS NOT NULL"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE pois SET editorial_summary = description "
        "WHERE editorial_summary IS NULL AND description IS NOT NULL"
    )
    op.drop_column('pois', 'description')
