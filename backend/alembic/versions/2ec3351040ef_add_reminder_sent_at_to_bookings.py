"""Add reminder_sent_at to bookings

Revision ID: 2ec3351040ef
Revises: 664ec4d0ef9b
Create Date: 2026-05-18 18:34:55.081706

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2ec3351040ef'
down_revision: Union[str, None] = '664ec4d0ef9b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'bookings',
        sa.Column('reminder_sent_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        op.f('ix_bookings_reminder_sent_at'),
        'bookings',
        ['reminder_sent_at'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_bookings_reminder_sent_at'), table_name='bookings')
    op.drop_column('bookings', 'reminder_sent_at')
