"""backfill missing receipt dates

Receipts saved without a recognized date were invisible in monthly statistics.
New receipts get today's date when the AI cannot read one; this gives old ones their upload date.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-03 16:00:00
"""
from typing import Sequence, Union

from alembic import op

revision: str = '0002'
down_revision: Union[str, None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        op.execute("UPDATE receipts SET date = date(created_at) WHERE date IS NULL")
    else:
        op.execute("UPDATE receipts SET date = created_at::date WHERE date IS NULL")


def downgrade() -> None:
    # The original NULLs cannot be told apart from real dates, so the backfill is kept
    pass
