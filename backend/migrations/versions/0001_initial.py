"""initial

Revision ID: 0001
Revises:
Create Date: 2024-01-01 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("age_range", sa.String(20), nullable=True),
        sa.Column("home_city", sa.String(100), nullable=True),
        sa.Column("travel_with_children", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "user_preferences",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("nature", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("culture", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("food", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("adventure", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("nightlife", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("relax", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("family_friendly", sa.Float(), nullable=False, server_default="0.0"),
    )

    op.create_table(
        "city_experiences",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("city", sa.String(100), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("icon", sa.String(50), nullable=True),
        sa.Column("feature_vector", postgresql.JSON(), nullable=False),
    )

    op.create_table(
        "user_experience_choices",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("experience_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("city_experiences.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "places",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("city", sa.String(100), nullable=False),
        sa.Column("category", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("lat", sa.Float(), nullable=False),
        sa.Column("lon", sa.Float(), nullable=False),
        sa.Column("visit_duration_minutes", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("opening_hours", postgresql.JSON(), nullable=True),
    )

    op.create_table(
        "place_features",
        sa.Column("place_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("places.id"), primary_key=True),
        sa.Column("nature", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("culture", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("food", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("adventure", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("nightlife", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("relax", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("family_friendly", sa.Float(), nullable=False, server_default="0.0"),
    )

    op.create_table(
        "itineraries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("city", sa.String(100), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "itinerary_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("itinerary_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("itineraries.id"), nullable=False),
        sa.Column("place_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("places.id"), nullable=False),
        sa.Column("day_number", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("arrival_time", sa.Time(), nullable=True),
        sa.Column("departure_time", sa.Time(), nullable=True),
    )

    op.create_table(
        "llm_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("model_name", sa.String(100), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("response", sa.Text(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("tokens_used", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "api_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("endpoint", sa.String(255), nullable=False),
        sa.Column("method", sa.String(10), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("request_body", postgresql.JSON(), nullable=True),
        sa.Column("response_body", postgresql.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("api_logs")
    op.drop_table("llm_logs")
    op.drop_table("itinerary_items")
    op.drop_table("itineraries")
    op.drop_table("place_features")
    op.drop_table("places")
    op.drop_table("user_experience_choices")
    op.drop_table("city_experiences")
    op.drop_table("user_preferences")
    op.drop_table("users")
