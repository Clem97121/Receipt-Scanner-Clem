"""families

Adds families, one-time family invites, and users.family_id / users.full_name.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-03 15:44:48.977775
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0003'
down_revision: Union[str, None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('families',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('family_invites',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('token', sa.String(length=64), nullable=False),
    sa.Column('family_id', sa.Integer(), nullable=False),
    sa.Column('created_by', sa.BigInteger(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('used_by', sa.BigInteger(), nullable=True),
    sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['created_by'], ['users.telegram_id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['family_id'], ['families.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['used_by'], ['users.telegram_id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('token')
    )
    with op.batch_alter_table('family_invites', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_family_invites_family_id'), ['family_id'], unique=False)

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('full_name', sa.String(length=128), nullable=True))
        batch_op.add_column(sa.Column('family_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_users_family_id'), ['family_id'], unique=False)
        batch_op.create_foreign_key('fk_users_family_id_families', 'families', ['family_id'], ['id'], ondelete='SET NULL')



def downgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_constraint('fk_users_family_id_families', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_users_family_id'))
        batch_op.drop_column('family_id')
        batch_op.drop_column('full_name')

    with op.batch_alter_table('family_invites', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_family_invites_family_id'))

    op.drop_table('family_invites')
    op.drop_table('families')
