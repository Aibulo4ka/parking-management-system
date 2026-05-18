"""Add telegram_chat_id to customers and create telegram_link_tokens

Revision ID: 664ec4d0ef9b
Revises: 858c32f188eb
Create Date: 2026-05-18 17:59:16.728942

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '664ec4d0ef9b'
down_revision: Union[str, None] = '858c32f188eb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'customers',
        sa.Column('telegram_chat_id', sa.String(length=64), nullable=True),
    )
    op.create_index(
        op.f('ix_customers_telegram_chat_id'),
        'customers',
        ['telegram_chat_id'],
        unique=True,
    )

    op.create_table(
        'telegram_link_tokens',
        sa.Column('token_id', sa.UUID(), nullable=False),
        sa.Column('customer_id', sa.UUID(), nullable=False),
        sa.Column('token', sa.String(length=64), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('used', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['customer_id'], ['customers.customer_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('token_id'),
    )
    op.create_index(
        op.f('ix_telegram_link_tokens_customer_id'),
        'telegram_link_tokens',
        ['customer_id'],
        unique=False,
    )
    op.create_index(
        op.f('ix_telegram_link_tokens_token'),
        'telegram_link_tokens',
        ['token'],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_telegram_link_tokens_token'), table_name='telegram_link_tokens')
    op.drop_index(op.f('ix_telegram_link_tokens_customer_id'), table_name='telegram_link_tokens')
    op.drop_table('telegram_link_tokens')

    op.drop_index(op.f('ix_customers_telegram_chat_id'), table_name='customers')
    op.drop_column('customers', 'telegram_chat_id')
