"""city_experiences hybrid fields

Revision ID: 0002
Revises: 0001
Create Date: 2026-03-14 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("city_experiences", sa.Column("created_at", sa.DateTime(), nullable=True, server_default=sa.func.now()))
    op.add_column("city_experiences", sa.Column("category", sa.String(100), nullable=True))
    op.add_column("city_experiences", sa.Column("slot", sa.String(50), nullable=True))
    op.add_column("city_experiences", sa.Column("why_locals_love_it", sa.Text(), nullable=True))
    op.add_column("city_experiences", sa.Column("effort_level", sa.String(20), nullable=True))
    op.add_column("city_experiences", sa.Column("time_of_day", sa.String(20), nullable=True))
    op.add_column("city_experiences", sa.Column("price_range", sa.String(20), nullable=True))
    op.add_column("city_experiences", sa.Column("verifiable", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("city_experiences", sa.Column("search_query", sa.Text(), nullable=True))
    op.add_column("city_experiences", sa.Column("place_id", sa.String(255), nullable=True))
    op.add_column("city_experiences", sa.Column("latitude", sa.Float(), nullable=True))
    op.add_column("city_experiences", sa.Column("longitude", sa.Float(), nullable=True))
    op.add_column("city_experiences", sa.Column("address", sa.Text(), nullable=True))
    op.add_column("city_experiences", sa.Column("phone", sa.String(50), nullable=True))
    op.add_column("city_experiences", sa.Column("website", sa.Text(), nullable=True))
    op.add_column("city_experiences", sa.Column("google_rating", sa.Float(), nullable=True))
    op.add_column("city_experiences", sa.Column("opening_hours", postgresql.JSON(), nullable=True))
    op.add_column("city_experiences", sa.Column("photo_references", postgresql.JSON(), nullable=True))
    op.add_column("city_experiences", sa.Column("verified", sa.Boolean(), nullable=False, server_default="false"))

    op.create_index("ix_city_experiences_city", "city_experiences", ["city"])


def downgrade() -> None:
    op.drop_index("ix_city_experiences_city", "city_experiences")
    for col in [
        "verified", "photo_references", "opening_hours", "google_rating",
        "website", "phone", "address", "longitude", "latitude", "place_id",
        "search_query", "verifiable", "price_range", "time_of_day",
        "effort_level", "why_locals_love_it", "slot", "category", "created_at",
    ]:
        op.drop_column("city_experiences", col)
