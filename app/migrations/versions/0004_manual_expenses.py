"""manual expenses

Expenses entered without a photo are receipts with blob_name = NULL.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-03 15:48:41.995237
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0004'
down_revision: Union[str, None] = '0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('receipts', schema=None) as batch_op:
        batch_op.alter_column('blob_name',
               existing_type=sa.VARCHAR(length=255),
               nullable=True)



def downgrade() -> None:
    # Fails while manual expenses exist; delete them first if a downgrade is really needed
    with op.batch_alter_table('receipts', schema=None) as batch_op:
        batch_op.alter_column('blob_name',
               existing_type=sa.VARCHAR(length=255),
               nullable=False)

