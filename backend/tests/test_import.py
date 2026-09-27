import time
from decimal import Decimal

import pytest

from app.pricing.base import PriceSet, ProductPage, SearchResult
from app.services import pricing
from app.services.importer import parse_date, parse_money, suggest_mapping

MAPPING = {
    "title": "Game",
    "platform": "System",
    "condition": "Condition",
    "purchase_price": "Paid",
    "purchase_date": "Bought",
    "quantity": "Qty",
    "tags": "Tags",
    "status": "List",
}


def row(game, system, condition="", paid="", bought="", qty="", tags="", status=""):
    return {
        "Game": game,
        "System": system,
        "Condition": condition,
        "Paid": paid,
        "Bought": bought,
        "Qty": qty,
        "Tags": tags,
        "List": status,
    }


def body(rows, **kw):
    return {"rows": rows, "mapping": MAPPING, **kw}


def test_suggest_mapping():
    m = suggest_mapping(["Game Name", "Console", "Price Paid", "Date Acquired", "Qty", "Notes", "UPC"])
    assert m == {
        "title": "Game Name",
        "platform": "Console",
        "purchase_price": "Price Paid",
        "purchase_date": "Date Acquired",
        "quantity": "Qty",
        "notes": "Notes",
        "upc": "UPC",
    }
    # Our own export round-trips exactly
    assert suggest_mapping(["title", "platform", "purchase_price"]) == {
        "title": "title",
        "platform": "platform",
        "purchase_price": "purchase_price",
    }


def test_parsers():
    assert parse_money("$1,234.50") == Decimal("1234.50")
    assert parse_money("12,50") == Decimal("12.50")
    assert parse_money("") is None
    assert str(parse_date("2024-03-05")) == "2024-03-05"
    assert str(parse_date("3/5/2024")) == "2024-03-05"
    assert str(parse_date("3/5/2024", day_first=True)) == "2024-05-03"
    assert str(parse_date("2024-03-05T10:00:00")) == "2024-03-05"
    with pytest.raises(ValueError):
        parse_date("someday")


def test_validate_reports_per_row(admin):
    rows = [
        row("Super Mario 64", "N64", "CIB", "$45", "2023-01-15", tags="fav; mario"),
        row("Halo", "Xbox", "loose", "5"),
        row("Final Fantasy VII", "PSX", "sealed", status="want"),
        row("Mystery", "Commodore VIC-20"),
        row("", "SNES"),
        row("Zelda", "SNES", "complete", "abc"),
        row("Super Mario 64", "Nintendo 64", "CIB"),  # duplicate of row 0
    ]
    r = admin.post("/api/import/validate", json=body(rows)).json()
    res = r["rows"]
    assert res[0]["ok"] and res[0]["platform"] == "Nintendo 64" and res[0]["condition"] == "cib"
    assert res[1]["platform"] == "Xbox"
    assert (
        res[2]["platform"] == "PlayStation"
        and res[2]["condition"] == "new"
        and res[2]["status"] == "wishlist"
    )
    assert not res[3]["ok"] and "unknown platform" in res[3]["errors"][0]
    assert not res[4]["ok"] and res[4]["errors"] == ["missing title"]
    assert not res[5]["ok"] and "purchase price" in res[5]["errors"][0]
    assert res[6]["duplicate"] and "duplicate row" in res[6]["warnings"]
    assert r["summary"] == {"total": 7, "ok": 4, "errors": 3, "duplicates": 1, "new_products": 3}


def test_default_platform_rescues_unknown(admin):
    snes = next(p["id"] for p in admin.get("/api/platforms").json() if p["slug"] == "snes")
    r = admin.post(
        "/api/import/validate", json=body([row("X", "Mystery Box")], default_platform_id=snes)
    ).json()
    assert r["rows"][0]["ok"] and r["rows"][0]["platform"] == "Super Nintendo" and r["rows"][0]["warnings"]


def test_commit_creates_items_and_skips_duplicates(admin):
    rows = [
        row("Super Mario 64", "N64", "CIB", "$45", "1/15/2023", "2", "fav; mario"),
        row("Super Mario 64", "N64", "loose", "20"),  # same product, other condition
        row("Halo", "Xbox"),
        row("Bad", "Nope"),
    ]
    result = admin.post("/api/import/commit", json=body(rows)).json()
    assert result == {"created_items": 3, "created_products": 2, "skipped": 0, "failed": 1, "unlinked": 2}

    items = admin.get("/api/collection", params={"sort": "purchase_price", "order": "desc"}).json()["items"]
    mario = items[0]
    assert mario["product"]["title"] == "Super Mario 64" and mario["quantity"] == 2
    assert mario["purchase_date"] == "2023-01-15" and mario["tags"] == ["fav", "mario"]
    assert mario["has_box"] and mario["has_manual"]  # inferred from CIB
    assert items[0]["product"]["id"] == items[1]["product"]["id"]

    # Importing the same file again skips everything already owned
    again = admin.post("/api/import/commit", json=body(rows)).json()
    assert again["created_items"] == 0 and again["skipped"] == 3


def test_export_round_trips_through_import(admin):
    admin.post("/api/import/commit", json=body([row("Halo", "Xbox", "cib", "12.34", tags="a")]))
    csv_text = admin.get("/api/collection/export").content.decode("utf-8-sig")
    import csv
    import io

    rows = list(csv.DictReader(io.StringIO(csv_text)))
    headers = list(rows[0].keys())
    mapping = admin.post("/api/import/suggest", json={"headers": headers}).json()
    admin.post("/api/users", json={"username": "bob", "password": "password123"})
    from tests.conftest import login

    login(admin, "bob")
    result = admin.post("/api/import/commit", json={"rows": rows, "mapping": mapping}).json()
    assert result["created_items"] == 1 and result["created_products"] == 0  # reuses the catalog product
    item = admin.get("/api/collection").json()["items"][0]
    assert item["condition"] == "cib" and item["purchase_price"] == "12.34" and item["tags"] == ["a"]


class LinkProvider:
    def __init__(self):
        self.fetched = []

    def search(self, query):
        prices = PriceSet(loose=Decimal("10"))
        return [
            SearchResult("1", "Super Mario 64", "https://www.pricecharting.com/game/nintendo-64/super-mario-64",
                         None, "nintendo-64", None, prices),
            SearchResult("2", "Super Mario 64 [Player's Choice]",
                         "https://www.pricecharting.com/game/nintendo-64/super-mario-64-players-choice",
                         None, "nintendo-64", None, prices),
            SearchResult("3", "Super Mario 64 DS", "https://www.pricecharting.com/game/nintendo-ds/super-mario-64-ds",
                         None, "nintendo-ds", None, prices),
        ]  # fmt: skip

    def fetch(self, url):
        self.fetched.append(url)
        return ProductPage(
            source_id="1",
            title="Super Mario 64",
            url=url,
            console_name=None,
            console_slug="nintendo-64",
            is_system=False,
            prices=PriceSet(loose=Decimal("30")),
        )

    def download(self, url):
        return b""


def test_autolink_links_only_unambiguous_matches(admin):
    provider = LinkProvider()
    pricing.set_provider(provider)
    try:
        admin.post(
            "/api/import/commit", json=body([row("Super Mario 64", "N64"), row("Obscure Thing", "N64")])
        )
        assert admin.get("/api/import/autolink").json()["unlinked"] == 2
        assert admin.post("/api/import/autolink").status_code == 202
        for _ in range(100):
            status = admin.get("/api/import/autolink").json()
            if not status["running"]:
                break
            time.sleep(0.05)
        assert status["linked"] == 1 and status["done"] == 2 and status["unlinked"] == 1
        assert [u["title"] for u in status["unmatched"]] == ["Obscure Thing"]
        assert provider.fetched == ["https://www.pricecharting.com/game/nintendo-64/super-mario-64"]
        mario = next(
            i
            for i in admin.get("/api/collection").json()["items"]
            if i["product"]["title"] == "Super Mario 64"
        )
        assert mario["market_price"] == "30.00"
    finally:
        pricing.set_provider(None)


def test_find_match_word_order_and_ambiguity():
    from app.services.autolink import _find_match

    class P:
        def __init__(self, results):
            self.results = results

        def search(self, q):
            return self.results

    class Plat:
        pricecharting_slug = "nintendo-64"

    class Prod:
        title = "GoldenEye 007"
        platform = Plat()

    def hit(title, slug="nintendo-64"):
        return SearchResult(
            "x", title, f"https://www.pricecharting.com/game/{slug}/{title}", None, slug, None, PriceSet()
        )

    variants = [hit("007 GoldenEye"), hit("007 GoldenEye [Player's Choice]"), hit("007 GoldenEye", "wii")]
    assert _find_match(P(variants), Prod()).endswith(
        "/007 GoldenEye"
    )  # word order; variants/other consoles ignored
    # an exact title (ignoring punctuation) beats a word-order match
    assert _find_match(P([hit("007 GoldenEye"), hit("GoldenEye: 007")]), Prod()).endswith("/GoldenEye: 007")
    # two different word-order matches -> ambiguous, left for the user
    assert _find_match(P([hit("007 GoldenEye"), hit("007 - GoldenEye")]), Prod()) is None
    assert _find_match(P([hit("GoldenEye 007 Reloaded")]), Prod()) is None
