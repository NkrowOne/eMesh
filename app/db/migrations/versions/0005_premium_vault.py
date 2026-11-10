"""💎 premium copies: canal almacén, the posts' copy in it and forwarded deliveries

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-10
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0005'
down_revision: str | None = '0004'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table('em_chats', schema=None) as batch_op:
        batch_op.add_column(sa.Column('vault', sa.Boolean(), server_default=sa.false(), nullable=False))
    with op.batch_alter_table('em_posts', schema=None) as batch_op:
        batch_op.add_column(sa.Column('vault_chat_id', sa.BigInteger(), nullable=True))
        batch_op.add_column(sa.Column('vault_msg_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('vault_sig', sa.String(length=32), nullable=True))
    with op.batch_alter_table('em_deliveries', schema=None) as batch_op:
        batch_op.add_column(sa.Column('forwarded', sa.Boolean(), server_default=sa.false(), nullable=False))


def downgrade() -> None:
    with op.batch_alter_table('em_deliveries', schema=None) as batch_op:
        batch_op.drop_column('forwarded')
    with op.batch_alter_table('em_posts', schema=None) as batch_op:
        batch_op.drop_column('vault_sig')
        batch_op.drop_column('vault_msg_id')
        batch_op.drop_column('vault_chat_id')
    with op.batch_alter_table('em_chats', schema=None) as batch_op:
        batch_op.drop_column('vault')
