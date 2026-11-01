"""scoring_runs.embedding_model and score_results.experience_detail for Scoring v1 (ERD §4)

Revision ID: 0012
Revises: 0011
"""

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nullable: a run and its results scored by v0 have neither.
    op.execute("ALTER TABLE scoring_runs ADD COLUMN embedding_model text")
    op.execute("ALTER TABLE score_results ADD COLUMN experience_detail jsonb")


def downgrade() -> None:
    op.execute("ALTER TABLE score_results DROP COLUMN experience_detail")
    op.execute("ALTER TABLE scoring_runs DROP COLUMN embedding_model")
