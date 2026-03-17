"""create gmail_credentials table

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-26 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "gmail_credentials",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("encrypted_refresh_token", sa.Text(), nullable=False),
        sa.Column("account_email", sa.String(255), nullable=False),
        sa.Column(
            "connected_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("gmail_credentials")
