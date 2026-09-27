from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Platform

ERAS = {
    1: "1st Gen (1972-1980)",
    2: "2nd Gen (1976-1992)",
    3: "3rd Gen / 8-bit",
    4: "4th Gen / 16-bit",
    5: "5th Gen / 32-64-bit",
    6: "6th Gen",
    7: "7th Gen",
    8: "8th Gen",
    9: "9th Gen",
    10: "10th Gen",
}
FIELDS = [
    "name",
    "slug",
    "brand",
    "generation",
    "media_type",
    "handheld",
    "release_year",
    "pricecharting_slug",
]


def seed_platforms(db: Session) -> int:
    """Insert any seed platforms whose slug is not already present. Returns count added."""
    data = yaml.safe_load((Path(__file__).parent / "platforms.yaml").read_text(encoding="utf-8"))
    existing = set(db.scalars(select(Platform.slug)))
    added = 0
    for row in data["platforms"]:
        values = dict(zip(FIELDS, row, strict=True))
        if values["slug"] in existing:
            continue
        values["era"] = ERAS.get(values["generation"]) or (
            "Computer" if values["media_type"] != "none" else None
        )
        db.add(Platform(**values))
        added += 1
    db.commit()
    return added
