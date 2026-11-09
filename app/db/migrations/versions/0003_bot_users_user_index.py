"""index of em_bot_users by user (the timezone a person already chose in any bot)

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-09
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = '0003'
down_revision: str | None = '0002'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index('ix_em_bot_users_user', 'em_bot_users', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_em_bot_users_user', table_name='em_bot_users')
