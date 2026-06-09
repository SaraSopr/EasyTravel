"""migrate travel categories to english

Revision ID: 69c5bf057c76
Revises: 127ea699f0bf
Create Date: 2026-03-31 11:33:26.887045

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '69c5bf057c76'
down_revision: Union[str, None] = '127ea699f0bf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_RENAME = [
    ("cultura", "culture"),
    ("natura", "nature"),
    ("cibo", "food"),
    ("avventura", "adventure"),
    ("famiglia", "family"),
]


def upgrade() -> None:
    for old, new in _RENAME:
        op.execute(
            f"UPDATE pois SET travel_category = '{new}' WHERE travel_category = '{old}'"
        )
        op.execute(
            f"UPDATE poi_classification_logs SET llm1_category = '{new}' WHERE llm1_category = '{old}'"
        )
        op.execute(
            f"UPDATE poi_classification_logs SET llm2_category = '{new}' WHERE llm2_category = '{old}'"
        )
        op.execute(
            f"UPDATE poi_classification_logs SET llm3_final_category = '{new}' WHERE llm3_final_category = '{old}'"
        )
        op.execute(
            f"UPDATE poi_classification_logs SET final_category = '{new}' WHERE final_category = '{old}'"
        )


def downgrade() -> None:
    for old, new in _RENAME:
        op.execute(
            f"UPDATE pois SET travel_category = '{old}' WHERE travel_category = '{new}'"
        )
        op.execute(
            f"UPDATE poi_classification_logs SET llm1_category = '{old}' WHERE llm1_category = '{new}'"
        )
        op.execute(
            f"UPDATE poi_classification_logs SET llm2_category = '{old}' WHERE llm2_category = '{new}'"
        )
        op.execute(
            f"UPDATE poi_classification_logs SET llm3_final_category = '{old}' WHERE llm3_final_category = '{new}'"
        )
        op.execute(
            f"UPDATE poi_classification_logs SET final_category = '{old}' WHERE final_category = '{new}'"
        )
