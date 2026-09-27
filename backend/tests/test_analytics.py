from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.core.db import SessionLocal
from app.models import PriceSnapshot

TODAY = datetime.now(UTC).date()


def _platform_id(client, slug):
    return next(p["id"] for p in client.get("/api/platforms").json() if p["slug"] == slug)


def _item(client, title, slug, prices: dict[int, float], condition="loose", **fields):
    """Create product + item; `prices` maps days-ago -> price for the item's condition."""
    product = client.post(
        "/api/products", json={"title": title, "platform_id": _platform_id(client, slug)}
    ).json()
    with SessionLocal() as db:
        for days_ago, price in prices.items():
            db.add(
                PriceSnapshot(
                    product_id=product["id"],
                    captured_on=TODAY - timedelta(days=days_ago),
                    **{condition: Decimal(str(price))},
                )
            )
        db.commit()
    r = client.post("/api/collection", json={"product_id": product["id"], "condition": condition, **fields})
    assert r.status_code == 201
    return r.json()


@pytest.fixture
def data(admin):
    # Super Mario 64: 40 -> 60 over the year (bought for 30)
    _item(admin, "Super Mario 64", "n64", {400: 35, 365: 40, 30: 50, 0: 60}, purchase_price="30")
    # Halo: 20 -> 10, two copies (bought for 25 each)
    _item(admin, "Halo", "xbox", {365: 20, 30: 15, 0: 10}, quantity=2, purchase_price="25")
    # Chrono Trigger CIB: 900 -> 1000, no purchase price
    _item(admin, "Chrono Trigger", "snes", {365: 900, 0: 1000}, condition="cib")
    # Unpriced
    _item(admin, "Obscure", "ps1", {})
    # Wishlist items are excluded by default
    _item(admin, "Wanted", "n64", {0: 500}, status="wishlist")
    return admin


def test_overview(data):
    o = data.get("/api/analytics/overview").json()
    assert o["total_value"] == 60 + 20 + 1000
    assert o["cost_basis"] == 30 + 50
    assert o["gain"] == (60 + 20) - (30 + 50)  # only items with a purchase price
    assert o["items"] == 4 and o["quantity"] == 5 and o["unpriced"] == 1
    assert o["changes"]["30d"]["change"] == (60 - 50) + (20 - 30) + (1000 - 900)  # 900 carried forward
    assert o["changes"]["1y"]["change"] == (60 - 40) + (20 - 40) + (1000 - 900)
    assert [t["title"] for t in o["top_items"]] == ["Chrono Trigger", "Super Mario 64", "Halo"]


def test_overview_respects_filters(data):
    o = data.get("/api/analytics/overview", params={"brand": "Nintendo"}).json()
    assert o["total_value"] == 1060
    o = data.get("/api/analytics/overview", params={"status": "wishlist"}).json()
    assert o["total_value"] == 500


def test_timeseries(data):
    points = data.get("/api/analytics/timeseries", params={"range": "1y"}).json()
    assert points[-1]["date"] == TODAY.isoformat()
    assert points[-1]["value"] == 1080
    assert points[0]["value"] == 40 + 40 + 900  # a year ago
    assert all(p["cost"] == 80 for p in points)  # no purchase dates -> counted throughout

    all_points = data.get("/api/analytics/timeseries", params={"range": "all"}).json()
    assert all_points[0]["priced"] == 1  # only Mario had a price 400 days ago
    assert len(all_points) >= 13


def test_breakdown(data):
    rows = data.get("/api/analytics/breakdown", params={"by": "brand"}).json()
    assert [(r["key"], r["value"], r["quantity"]) for r in rows] == [
        ("Nintendo", 1060, 2),
        ("Microsoft", 20, 2),
        ("Sony", 0, 1),
    ]
    rows = data.get("/api/analytics/breakdown", params={"by": "condition"}).json()
    assert {r["key"] for r in rows} == {"loose", "cib"}
    assert data.get("/api/analytics/breakdown", params={"by": "nope"}).status_code == 422


def test_movers(data):
    m = data.get("/api/analytics/movers", params={"days": 365}).json()
    assert [g["title"] for g in m["gainers"]] == ["Chrono Trigger", "Super Mario 64"]
    assert [loser["title"] for loser in m["losers"]] == ["Halo"]
    halo = m["losers"][0]
    assert halo["change"] == -10 and halo["value_change"] == -20 and halo["pct"] == -50

    # min_value threshold drops cheap items
    m = data.get("/api/analytics/movers", params={"days": 365, "min_value": 100}).json()
    assert [g["title"] for g in m["gainers"]] == ["Chrono Trigger"] and m["losers"] == []


def test_collection_sort_by_value(data):
    def titles(sort, order):
        items = data.get("/api/collection", params={"sort": sort, "order": order, "status": "owned"}).json()[
            "items"
        ]
        return [i["product"]["title"] for i in items]

    # values: Chrono 1000 (cib), Mario 60, Halo 10 x2 = 20, Obscure unpriced (always last)
    assert titles("value", "desc") == ["Chrono Trigger", "Super Mario 64", "Halo", "Obscure"]
    assert titles("value", "asc") == ["Halo", "Super Mario 64", "Chrono Trigger", "Obscure"]
    # per-unit market price: Halo 10 < Mario 60
    assert titles("market_price", "asc") == ["Halo", "Super Mario 64", "Chrono Trigger", "Obscure"]
    # paging still works with the extra joins
    page = data.get(
        "/api/collection",
        params={"sort": "value", "order": "desc", "limit": 2, "offset": 2, "status": "owned"},
    ).json()
    assert page["total"] == 4 and [i["product"]["title"] for i in page["items"]] == ["Halo", "Obscure"]
