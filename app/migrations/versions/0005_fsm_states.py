"""fsm states

Telegram conversation (aiogram FSM) state, kept in the DB because Lambda has no memory between calls.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-10 13:58:03.196336
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0005'
down_revision: Union[str, None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('fsm_states',
    sa.Column('key', sa.String(length=255), nullable=False),
    sa.Column('state', sa.String(length=255), nullable=True),
    sa.Column('data', sa.Text(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.PrimaryKeyConstraint('key')
    )


def downgrade() -> None:
    op.drop_table('fsm_states')
