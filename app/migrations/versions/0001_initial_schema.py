"""initial schema

Matches the schema previously created by Base.metadata.create_all(); existing
databases are stamped with this revision instead of running it (see db/migrations.py).

Revision ID: 0001
Revises:
Create Date: 2026-10-03 15:15:48.159250
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('users',
    sa.Column('telegram_id', sa.BigInteger(), nullable=False),
    sa.Column('username', sa.String(length=64), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.PrimaryKeyConstraint('telegram_id')
    )
    op.create_table('receipts',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('user_id', sa.BigInteger(), nullable=False),
    sa.Column('store_name', sa.String(length=128), nullable=True),
    sa.Column('date', sa.Date(), nullable=True),
    sa.Column('total_amount', sa.Numeric(precision=10, scale=2), nullable=False),
    sa.Column('currency', sa.String(length=10), nullable=False),
    sa.Column('blob_name', sa.String(length=255), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.telegram_id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('blob_name')
    )
    with op.batch_alter_table('receipts', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_receipts_date'), ['date'], unique=False)
        batch_op.create_index(batch_op.f('ix_receipts_user_id'), ['user_id'], unique=False)

    op.create_table('receipt_items',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('receipt_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('quantity', sa.Numeric(precision=10, scale=3), nullable=False),
    sa.Column('total_price', sa.Numeric(precision=10, scale=2), nullable=False),
    sa.Column('category', sa.String(length=64), nullable=False),
    sa.ForeignKeyConstraint(['receipt_id'], ['receipts.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('receipt_items', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_receipt_items_category'), ['category'], unique=False)
        batch_op.create_index(batch_op.f('ix_receipt_items_receipt_id'), ['receipt_id'], unique=False)



def downgrade() -> None:
    with op.batch_alter_table('receipt_items', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_receipt_items_receipt_id'))
        batch_op.drop_index(batch_op.f('ix_receipt_items_category'))

    op.drop_table('receipt_items')
    with op.batch_alter_table('receipts', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_receipts_user_id'))
        batch_op.drop_index(batch_op.f('ix_receipts_date'))

    op.drop_table('receipts')
    op.drop_table('users')
