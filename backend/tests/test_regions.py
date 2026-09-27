from decimal import Decimal

import pytest
import sqlalchemy as sa

from app.core.db import SessionLocal, engine
from app.pricing.base import PriceSet, ProductPage
from app.services import pricing


def _platforms(client):
    return {p["slug"]: p for p in client.get("/api/platforms").json()}


def test_seeded_regional_platforms(admin):
    p = _platforms(admin)
    assert p["n64-pal"]["region"] == "PAL" and p["n64-pal"]["pricecharting_slug"] == "pal-nintendo-64"
    assert p["n64-jp"]["region"] == "NTSC-J" and p["n64-jp"]["pricecharting_slug"] == "jp-nintendo-64"
    assert p["genesis-pal"]["name"] == "Sega Mega Drive (PAL)"
    assert p["n64-pal"]["era"] == p["n64"]["era"] and p["n64-pal"]["brand"] == "Nintendo"
    assert p["super-famicom"]["region"] == "NTSC-J" and p["pc-engine"]["pricecharting_slug"] == "jp-pc-engine"
    assert p["n64"]["region"] == "NTSC-U"
    # every PriceCharting console slug maps to exactly one platform
    slugs = [x["pricecharting_slug"] for x in p.values() if x["pricecharting_slug"]]
    dupes = {s for s in slugs if slugs.count(s) > 1}
    assert dupes <= {"sega-genesis"}  # Nomad intentionally shares the Genesis library


@pytest.mark.parametrize(
    ("platform", "region", "expected"),
    [
        ("N64", "", "Nintendo 64"),
        ("N64 PAL", "", "Nintendo 64 (PAL)"),
        ("Nintendo 64 (PAL)", "", "Nintendo 64 (PAL)"),
        ("Japanese Saturn", "", "Sega Saturn (JP)"),
        ("Mega Drive", "PAL", "Sega Mega Drive (PAL)"),
        ("Playstation 2", "Japan", "PlayStation 2 (JP)"),
        ("SNES", "JP", "Super Famicom"),
        ("Super Famicom", "", "Super Famicom"),
        ("PS2", "NTSC-U", "PlayStation 2"),
    ],
)
def test_import_region_matching(admin, platform, region, expected):
    rows = [{"t": "Game", "p": platform, "r": region}]
    r = admin.post(
        "/api/import/validate", json={"rows": rows, "mapping": {"title": "t", "platform": "p", "region": "r"}}
    ).json()
    assert r["rows"][0]["platform"] == expected, r["rows"][0]


def test_import_default_region_for_european_collections(admin):
    rows = [{"t": "A", "p": "N64"}, {"t": "B", "p": "N64 NTSC"}, {"t": "C", "p": "Super Famicom"}]
    r = admin.post(
        "/api/import/validate",
        json={"rows": rows, "mapping": {"title": "t", "platform": "p"}, "default_region": "PAL"},
    ).json()
    assert [x["platform"] for x in r["rows"]] == ["Nintendo 64 (PAL)", "Nintendo 64", "Super Famicom"]


def test_pricecharting_pal_page_maps_to_pal_platform(admin):
    class Provider:
        def fetch(self, url):
            return ProductPage(
                "55", "Super Mario 64", url, None, "pal-nintendo-64", False, PriceSet(loose=Decimal("20"))
            )

        def download(self, url):
            return b""

    pricing.set_provider(Provider())
    try:
        product = admin.post(
            "/api/products/import",
            json={"url": "https://www.pricecharting.com/game/pal-nintendo-64/super-mario-64"},
        ).json()
    finally:
        pricing.set_provider(None)
    assert product["platform"]["name"] == "Nintendo 64 (PAL)" and product["platform"]["region"] == "PAL"


def test_region_breakdown(admin):
    p = _platforms(admin)
    for title, slug in (("A", "n64"), ("B", "n64-pal"), ("C", "saturn-jp")):
        prod = admin.post("/api/products", json={"title": title, "platform_id": p[slug]["id"]}).json()
        admin.post("/api/collection", json={"product_id": prod["id"]})
    rows = admin.get("/api/analytics/breakdown", params={"by": "region"}).json()
    assert sorted(r["key"] for r in rows) == ["NTSC-J", "NTSC-U", "PAL"]
    items = admin.get("/api/collection", params={"region": "PAL"}).json()["items"]
    assert [i["product"]["title"] for i in items] == ["B"]


def test_migration_fixes_only_untouched_rows(admin):
    """The data migration corrects old seed values but keeps admin edits."""
    import importlib.util
    from pathlib import Path

    path = next(Path("alembic/versions").glob("*platform_region_fixes.py"))
    spec = importlib.util.spec_from_file_location("m", path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)

    with engine.begin() as conn:
        conn.execute(sa.text("update platforms set region='NTSC-U' where slug='famicom'"))  # old seed value
        conn.execute(sa.text("update platforms set region='Custom' where slug='super-famicom'"))  # admin edit
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    with engine.begin() as conn:
        m.op = Operations(MigrationContext.configure(conn))
        m.upgrade()
    with SessionLocal() as db:
        regions = dict(
            db.execute(
                sa.text("select slug, region from platforms where slug in ('famicom','super-famicom')")
            ).all()
        )
    assert regions == {"famicom": "NTSC-J", "super-famicom": "Custom"}
