"""nullable candidate references for anonymous interviews

An interview may start without a candidate (`POST /interview/start` with no
candidate_id). The 0001 schema required a candidates row, which would have forced
the application to invent a fake candidate. These two columns become nullable
instead; the foreign keys stay in place, so a non-null value must still reference
a real candidate.

downgrade() deletes the anonymous rows: the 0001 schema cannot represent them.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-24 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "interview_sessions", "candidate_id", existing_type=sa.String(length=36), nullable=True
    )
    op.alter_column(
        "competency_history", "candidate_id", existing_type=sa.String(length=36), nullable=True
    )


def downgrade() -> None:
    op.execute("DELETE FROM competency_history WHERE candidate_id IS NULL")
    op.execute("DELETE FROM interview_sessions WHERE candidate_id IS NULL")
    op.alter_column(
        "competency_history", "candidate_id", existing_type=sa.String(length=36), nullable=False
    )
    op.alter_column(
        "interview_sessions", "candidate_id", existing_type=sa.String(length=36), nullable=False
    )
