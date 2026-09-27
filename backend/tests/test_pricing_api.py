from datetime import date
from decimal import Decimal

import pytest

from app.pricing.base import BlockedError, PriceSet, ProductPage, SearchResult
from app.services import pricing
from tests.conftest import login

URL = "https://www.pricecharting.com/game/super-nintendo/super-metroid"
URL2 = "https://www.pricecharting.com/game/nintendo-64/super-mario-64"


class FakeProvider:
    def __init__(self):
        self.fetches: list[str] = []
        self.fail: Exception | None = None
        self.loose = Decimal("94.06")

    def page(self, url):
        sid, title, slug = ("7143", "Super Metroid", "super-nintendo")
        if url == URL2:
            sid, title, slug = ("1000", "Super Mario 64", "nintendo-64")
        return ProductPage(
            source_id=sid,
            title=title,
            url=url,
            console_name=None,
            console_slug=slug,
            is_system=False,
            prices=PriceSet(loose=self.loose, cib=Decimal("300"), new=Decimal("6000")),
            history={
                date(2020, 1, 1): PriceSet(loose=Decimal("40")),
                date(2024, 1, 1): PriceSet(loose=Decimal("80")),
            },
            image_url=None,
            genre="Action",
        )

    def search(self, query):
        p = self.page(URL)
        return [SearchResult(p.source_id, p.title, p.url, "Super Nintendo", p.console_slug, None, p.prices)]

    def fetch(self, url):
        self.fetches.append(url)
        if self.fail:
            raise self.fail
        return self.page(url)

    def download(self, url):
        return b""


@pytest.fixture
def fake():
    provider = FakeProvider()
    pricing.set_provider(provider)
    yield provider
    pricing.set_provider(None)


def _platform(client, slug):
    return next(p for p in client.get("/api/platforms").json() if p["slug"] == slug)


def test_search_maps_platform(admin, fake):
    snes = _platform(admin, "snes")
    hits = admin.get("/api/pricecharting/search", params={"q": "metroid", "platform_id": snes["id"]}).json()
    assert hits[0]["platform_id"] == snes["id"] and hits[0]["platform_match"] is True
    assert hits[0]["product_id"] is None


def test_import_creates_product_with_history_and_is_idempotent(admin, fake):
    r = admin.post("/api/products/import", json={"url": URL})
    assert r.status_code == 200, r.text
    product = r.json()
    assert product["title"] == "Super Metroid" and product["platform"]["slug"] == "snes"
    assert product["pricecharting_id"] == "7143" and product["genre"] == "Action"

    history = admin.get(f"/api/products/{product['id']}/prices").json()
    assert [h["source"] for h in history] == ["history", "history", "scrape"]

    again = admin.post("/api/products/import", json={"url": URL}).json()
    assert again["id"] == product["id"]
    assert len(fake.fetches) == 2  # fetched, but no duplicate product


def test_item_value_and_summary(admin, fake):
    product = admin.post("/api/products/import", json={"url": URL}).json()
    admin.post(
        "/api/collection",
        json={"product_id": product["id"], "condition": "cib", "quantity": 2, "purchase_price": "100"},
    )
    item = admin.get("/api/collection").json()["items"][0]
    assert Decimal(item["market_price"]) == Decimal("300")
    assert Decimal(item["value"]) == Decimal("600")
    summary = admin.get("/api/collection/summary").json()
    assert summary["total_value"] == 600.0 and summary["cost_basis"] == 200.0 and summary["unpriced"] == 0


def test_link_existing_product(admin, fake):
    snes = _platform(admin, "snes")
    product = admin.post("/api/products", json={"title": "Metroid 3", "platform_id": snes["id"]}).json()
    r = admin.post(f"/api/products/{product['id']}/link", json={"url": URL})
    assert r.status_code == 200 and r.json()["pricecharting_id"] == "7143"

    other = admin.post("/api/products", json={"title": "Dupe", "platform_id": snes["id"]}).json()
    assert admin.post(f"/api/products/{other['id']}/link", json={"url": URL}).status_code == 409
    bad = admin.post(f"/api/products/{other['id']}/link", json={"url": "https://x.com/a"})
    assert bad.status_code == 400


def test_user_refresh_cooldown(admin, fake):
    product = admin.post("/api/products/import", json={"url": URL}).json()
    admin.post("/api/users", json={"username": "bob", "password": "password123"})
    login(admin, "bob")
    assert admin.post(f"/api/products/{product['id']}/refresh").status_code == 429
    login(admin, "admin")
    assert admin.post(f"/api/products/{product['id']}/refresh").status_code == 200


def test_full_run_updates_in_use_products_and_stops_when_blocked(admin, fake):
    a = admin.post("/api/products/import", json={"url": URL}).json()
    b = admin.post("/api/products/import", json={"url": URL2}).json()
    admin.post("/api/collection", json={"product_id": a["id"]})
    # b is in no collection, so it is not scraped

    fake.fetches.clear()
    fake.loose = Decimal("120")
    run_id = pricing.run_price_update("manual", force=True)
    assert fake.fetches == [URL]
    status = admin.get("/api/admin/scraper").json()
    run = status["runs"][0]
    assert run["id"] == run_id and run["status"] == "ok" and run["succeeded"] == 1
    assert status["tracked_products"] == 1
    item = admin.get("/api/collection").json()["items"][0]
    assert Decimal(item["market_price"]) == Decimal("120")

    # A non-forced run skips recently priced products
    fake.fetches.clear()
    pricing.run_price_update("schedule")
    assert fake.fetches == []

    admin.post("/api/collection", json={"product_id": b["id"]})
    fake.fail = BlockedError("HTTP 429", status=429)
    pricing.run_price_update("manual", force=True)
    run = admin.get("/api/admin/scraper").json()["runs"][0]
    assert run["status"] == "blocked" and run["failed"] == 1 and run["skipped"] == 1
    errors = admin.get("/api/admin/scraper/errors").json()
    assert errors[0]["kind"] == "blocked"


def test_admin_settings(admin, fake):
    s = admin.get("/api/admin/scraper").json()["settings"]
    s["cron"] = "not a cron"
    assert admin.put("/api/admin/scraper/settings", json=s).status_code == 422
    s["cron"] = "0 4 * * *"
    assert admin.put("/api/admin/scraper/settings", json=s).json()["cron"] == "0 4 * * *"
    assert admin.get("/api/admin/scraper").json()["settings"]["cron"] == "0 4 * * *"

    admin.post("/api/users", json={"username": "bob", "password": "password123"})
    login(admin, "bob")
    assert admin.get("/api/admin/scraper").status_code == 403
