"""add evaluation tables

Revision ID: a1b2c3d4e5f6
Revises: 86d783c9bc85
Create Date: 2026-06-13 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '86d783c9bc85'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'evaluation_itineraries',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('run_id', sa.Uuid(), nullable=False),
        sa.Column('profile_key', sa.String(length=50), nullable=False),
        sa.Column('city', sa.String(length=100), nullable=False),
        sa.Column('num_days', sa.Integer(), nullable=False),
        sa.Column('solver', sa.String(length=10), nullable=False),
        sa.Column('payload_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('candidates_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('metrics_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_evaluation_itineraries_run', 'evaluation_itineraries', ['run_id'])

    op.create_table(
        'evaluation_pairs',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('itinerary_id', sa.Uuid(), nullable=False),
        sa.Column('pair_type', sa.String(length=20), nullable=False),
        sa.Column('poi_a_id', sa.Uuid(), nullable=False),
        sa.Column('poi_b_id', sa.Uuid(), nullable=False),
        sa.Column('poi_a_snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('poi_b_snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('profile_key', sa.String(length=50), nullable=False),
        sa.Column('city', sa.String(length=100), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['itinerary_id'], ['evaluation_itineraries.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_evaluation_pairs_itinerary', 'evaluation_pairs', ['itinerary_id'])

    op.create_table(
        'evaluation_ratings',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('pair_id', sa.Uuid(), nullable=False),
        sa.Column('evaluator_id', sa.String(length=100), nullable=False),
        sa.Column('choice', sa.String(length=10), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['pair_id'], ['evaluation_pairs.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_evaluation_ratings_pair', 'evaluation_ratings', ['pair_id'])
    op.create_index('ix_evaluation_ratings_evaluator', 'evaluation_ratings', ['evaluator_id'])

    op.create_table(
        'evaluation_likert',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('itinerary_id', sa.Uuid(), nullable=False),
        sa.Column('evaluator_id', sa.String(length=100), nullable=False),
        sa.Column('realism', sa.Integer(), nullable=False),
        sa.Column('completeness', sa.Integer(), nullable=False),
        sa.Column('profile_fit', sa.Integer(), nullable=False),
        sa.Column('overall', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['itinerary_id'], ['evaluation_itineraries.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_evaluation_likert_itinerary', 'evaluation_likert', ['itinerary_id'])


def downgrade() -> None:
    op.drop_table('evaluation_likert')
    op.drop_table('evaluation_ratings')
    op.drop_table('evaluation_pairs')
    op.drop_table('evaluation_itineraries')
