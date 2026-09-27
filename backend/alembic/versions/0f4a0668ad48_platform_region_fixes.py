"""platform region fixes

Revision ID: 0f4a0668ad48
Revises: 0090ab831ea8
Create Date: 2026-09-27 13:31:48.873825

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0f4a0668ad48'
down_revision: Union[str, Sequence[str], None] = '0090ab831ea8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (slug, column, old seeded value, corrected value). Only rows still at the old value change,
# so edits made by an admin are kept.
FIXES = [
    ("famicom", "region", "NTSC-U", "NTSC-J"),
    ("famicom-disk-system", "region", "NTSC-U", "NTSC-J"),
    ("super-famicom", "region", "NTSC-U", "NTSC-J"),
    ("pc-engine", "region", "NTSC-U", "NTSC-J"),
    ("pc-engine", "pricecharting_slug", "pc-engine", "jp-pc-engine"),
    ("sg-1000", "region", "NTSC-U", "NTSC-J"),
    ("sg-1000", "pricecharting_slug", "sg-1000", None),
    ("msx", "pricecharting_slug", "msx", None),
    ("wonderswan", "region", "NTSC-U", "NTSC-J"),
    ("pc-fx", "region", "NTSC-U", "NTSC-J"),
]


def upgrade() -> None:
    """Correct region / PriceCharting slug on platforms seeded before PAL/JP support."""
    platforms = sa.table(
        "platforms", sa.column("slug"), sa.column("region"), sa.column("pricecharting_slug")
    )
    for slug, column, old, new in FIXES:
        op.execute(
            platforms.update()
            .where(platforms.c.slug == slug, platforms.c[column] == old)
            .values({column: new})
        )


def downgrade() -> None:
    """Data fix only; nothing to undo."""
