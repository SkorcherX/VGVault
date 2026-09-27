from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from app.pricing.base import BlockedError, NotFoundError, ParseError
from app.pricing.pricecharting import (
    PriceChartingProvider,
    RateLimiter,
    parse_money,
    parse_product_page,
    parse_search_page,
)

FIXTURES = Path(__file__).parent / "fixtures"
GAME_URL = "https://www.pricecharting.com/game/super-nintendo/super-metroid"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_parse_money():
    assert parse_money("$6,512.83") == Decimal("6512.83")
    assert parse_money(" - ") is None
    assert parse_money("$0.00") is None


def test_parse_product_page():
    page = parse_product_page(fixture("pc_game_super_metroid.html"), GAME_URL)
    assert page.source_id == "7143"
    assert page.title == "Super Metroid"
    assert page.console_name == "Super Nintendo"
    assert page.console_slug == "super-nintendo"
    assert page.is_system is False
    assert page.prices.loose == Decimal("94.06")
    assert page.prices.cib == Decimal("326.83")
    assert page.prices.new == Decimal("6512.83")
    assert page.prices.graded and page.prices.box_only and page.prices.manual_only
    assert page.genre == "Action & Adventure"
    assert page.release_date == date(1994, 4, 18)
    assert page.image_url and page.image_url.endswith(".jpg")
    # ~20 years of monthly history, in dollars
    assert len(page.history) > 200
    latest = page.history[max(page.history)]
    assert latest.loose and latest.loose < 1000


def test_parse_product_page_rejects_garbage():
    with pytest.raises(ParseError):
        parse_product_page("<html><body>nope</body></html>", GAME_URL)


def test_parse_search_page():
    results = parse_search_page(fixture("pc_search_super_metroid.html"))
    assert len(results) > 5
    first = results[0]
    assert (first.source_id, first.title, first.console_slug) == ("7143", "Super Metroid", "super-nintendo")
    assert first.url == GAME_URL
    assert first.prices.loose == Decimal("94.06")


def _provider(handler) -> tuple[PriceChartingProvider, list[float]]:
    sleeps: list[float] = []
    provider = PriceChartingProvider(
        RateLimiter(0, 0, sleep=sleeps.append),
        max_retries=2,
        sleep=sleeps.append,
        transport=httpx.MockTransport(handler),
    )
    return provider, sleeps


def test_fetch_retries_then_succeeds():
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(503)
        return httpx.Response(200, text=fixture("pc_game_super_metroid.html"))

    provider, sleeps = _provider(handler)
    assert provider.fetch(GAME_URL).source_id == "7143"
    assert len(calls) == 2 and any(s >= 15 for s in sleeps)  # backed off


def test_fetch_blocked_after_retries():
    provider, _ = _provider(lambda r: httpx.Response(429))
    with pytest.raises(BlockedError):
        provider.fetch(GAME_URL)


def test_fetch_404():
    provider, _ = _provider(lambda r: httpx.Response(404))
    with pytest.raises(NotFoundError):
        provider.fetch(GAME_URL)


def test_search_redirect_to_single_product():
    def handler(request):
        if request.url.path == "/search-products":
            return httpx.Response(302, headers={"Location": GAME_URL})
        return httpx.Response(200, text=fixture("pc_game_super_metroid.html"))

    provider, _ = _provider(handler)
    results = provider.search("super metroid")
    assert [r.source_id for r in results] == ["7143"]


def test_fetch_rejects_other_hosts():
    provider, _ = _provider(lambda r: httpx.Response(200))
    with pytest.raises(Exception, match="Not a PriceCharting"):
        provider.fetch("https://evil.example.com/game/x/y")


def test_fetch_moved_page_redirecting_to_search_is_not_found():
    def handler(request):
        if request.url.path.startswith("/game/"):
            return httpx.Response(
                302, headers={"Location": "https://www.pricecharting.com/search-products?q=x"}
            )
        return httpx.Response(200, text=fixture("pc_search_super_metroid.html"))

    provider, _ = _provider(handler)
    with pytest.raises(NotFoundError):
        provider.fetch("https://www.pricecharting.com/game/xbox/everything-or-nothing")
