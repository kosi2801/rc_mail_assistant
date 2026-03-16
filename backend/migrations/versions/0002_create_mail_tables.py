"""create mail tables

Revision ID: 0002
Revises: 0001
Create Date: 2026-02-28 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # incoming_emails — stores fetched Gmail messages
    op.create_table(
        "incoming_emails",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("gmail_message_id", sa.String(255), nullable=False),
        sa.Column("gmail_thread_id", sa.String(255), nullable=False),
        sa.Column("sender_name", sa.String(255), nullable=False),
        sa.Column("sender_email", sa.String(255), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("received_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "synced_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.UniqueConstraint("gmail_message_id", name="uq_incoming_emails_gmail_message_id"),
    )
    op.create_index(
        "ix_incoming_emails_gmail_message_id",
        "incoming_emails",
        ["gmail_message_id"],
        unique=True,
    )

    # mail_sync_cursor — singleton (id=1) tracking last successful sync timestamp
    op.create_table(
        "mail_sync_cursor",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("last_synced_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("overlap_minutes", sa.Integer(), nullable=False, server_default="5"),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            onupdate=sa.text("NOW()"),
            nullable=False,
        ),
    )

    # mail_sync_runs — audit log of each sync execution
    op.create_table(
        "mail_sync_runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("finished_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("outcome", sa.String(20), nullable=True),
        sa.Column("new_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("triggered_by", sa.String(20), nullable=False, server_default="manual"),
    )


def downgrade() -> None:
    op.drop_table("mail_sync_runs")
    op.drop_table("mail_sync_cursor")
    op.drop_index("ix_incoming_emails_gmail_message_id", table_name="incoming_emails")
    op.drop_table("incoming_emails")
