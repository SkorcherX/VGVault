"""condition ratings

Revision ID: b4e1c2d3a5f6
Revises: ed6aefe83cd4
Create Date: 2026-09-28 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b4e1c2d3a5f6'
down_revision: Union[str, Sequence[str], None] = 'ed6aefe83cd4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('collection_items', schema=None) as batch_op:
        batch_op.add_column(sa.Column('item_rating', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('box_rating', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('manual_rating', sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('collection_items', schema=None) as batch_op:
        batch_op.drop_column('manual_rating')
        batch_op.drop_column('box_rating')
        batch_op.drop_column('item_rating')
