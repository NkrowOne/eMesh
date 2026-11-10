"""no rotation: every post goes out on its own schedule

Rotation posts become posts with their own schedule (``mode = 'own'``) with a copy of the network's frequency, the one
they were sent at; their next send is computed by the scheduler (``next_send_at`` NULL). The columns only the rotation
used are dropped: ``em_bots.rotation`` and ``rot_next_at``, ``em_groups.freq`` and ``rot_next_at``,
``em_chats.rot_last_post_id``. The downgrade adds the columns back (empty); the posts stay with their own schedule.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-10
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import app.db.base

revision: str = '0004'
down_revision: str | None = '0003'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "UPDATE em_posts SET mode = 'own', next_send_at = NULL, "
        "freq = (SELECT em_bots.freq FROM em_bots WHERE em_bots.id = em_posts.bot_id) "
        "WHERE mode = 'rotation'"
    )
    with op.batch_alter_table('em_bots') as batch:
        batch.drop_column('rotation')
        batch.drop_column('rot_next_at')
    with op.batch_alter_table('em_groups') as batch:
        batch.drop_column('freq')
        batch.drop_column('rot_next_at')
    with op.batch_alter_table('em_chats') as batch:
        batch.drop_column('rot_last_post_id')


def downgrade() -> None:
    with op.batch_alter_table('em_chats') as batch:
        batch.add_column(sa.Column('rot_last_post_id', sa.Integer(), nullable=True))
    with op.batch_alter_table('em_groups') as batch:
        batch.add_column(sa.Column('freq', sa.JSON(), nullable=True))
        batch.add_column(sa.Column('rot_next_at', app.db.base.UTCDateTime(), nullable=True))
    with op.batch_alter_table('em_bots') as batch:
        batch.add_column(sa.Column('rotation', sa.String(length=8), server_default='seq', nullable=False))
        batch.add_column(sa.Column('rot_next_at', app.db.base.UTCDateTime(), nullable=True))
