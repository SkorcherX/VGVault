"""nomad shares genesis library

Revision ID: ed6aefe83cd4
Revises: 700c703963be
Create Date: 2026-09-27 14:14:41.530101

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ed6aefe83cd4'
down_revision: Union[str, Sequence[str], None] = '700c703963be'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """The Nomad is a handheld Genesis with no games of its own, so it shouldn't claim
    PriceCharting's sega-genesis console (which made Genesis links resolve to Nomad).
    Only changes the row if it still has the originally seeded value."""
    platforms = sa.table("platforms", sa.column("slug"), sa.column("pricecharting_slug"))
    op.execute(
        platforms.update()
        .where(platforms.c.slug == "nomad", platforms.c.pricecharting_slug == "sega-genesis")
        .values(pricecharting_slug=None)
    )


def downgrade() -> None:
    """Data fix only; nothing to undo."""
