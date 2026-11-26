"""users, authentication sessions and the candidate link

Additive only: no existing table is dropped or rewritten and no existing row is
touched. `candidates.user_id` is NULL for every guest candidate that already
exists, so guest interviews keep working exactly as before.

`candidates.user_id` is UNIQUE: one account owns at most one candidate. PostgreSQL
does not compare NULLs in a unique constraint, so any number of guest candidates
may stay unlinked.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-26 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_email_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )

    op.add_column("candidates", sa.Column("user_id", sa.String(length=36), nullable=True))
    op.create_foreign_key(
        "fk_candidates_user_id_users",
        "candidates",
        "users",
        ["user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_unique_constraint("uq_candidates_user_id", "candidates", ["user_id"])

    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_auth_sessions_user_created", "auth_sessions", ["user_id", "created_at"])
    op.create_index("ix_auth_sessions_expires", "auth_sessions", ["expires_at"])


def downgrade() -> None:
    """Remove the auth tables and the candidate link.

    Interview rows are untouched: dropping `candidates.user_id` only forgets which
    account owned a candidate. The candidates and their interviews remain.
    """
    op.drop_index("ix_auth_sessions_expires", table_name="auth_sessions")
    op.drop_index("ix_auth_sessions_user_created", table_name="auth_sessions")
    op.drop_table("auth_sessions")
    op.drop_constraint("uq_candidates_user_id", "candidates", type_="unique")
    op.drop_constraint("fk_candidates_user_id_users", "candidates", type_="foreignkey")
    op.drop_column("candidates", "user_id")
    op.drop_table("users")
