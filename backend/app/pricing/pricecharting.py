"""PriceCharting.com scraper.

Kept deliberately polite: a single shared rate limiter (random delay between every
request), exponential backoff on 429/5xx, and hard stop on repeated blocks. Parsing
targets element IDs, not table positions, so cosmetic layout changes don't break it.
"""

import json
import logging
import random
import re
import threading
import time
from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode, urlparse

import httpx
from selectolax.parser import HTMLParser, Node

from app.pricing.base import (
    BlockedError,
    NetworkError,
    NotFoundError,
    ParseError,
    PriceProviderError,
    PriceSet,
    ProductPage,
    SearchResult,
)

log = logging.getLogger(__name__)

BASE_URL = "https://www.pricecharting.com"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0 Safari/537.36"
)
PRICE_IDS = {
    "loose": "used_price",
    "cib": "complete_price",
    "new": "new_price",
    "graded": "graded_price",
    "box_only": "box_only_price",
    "manual_only": "manual_only_price",
}
CHART_KEYS = {
    "loose": "used",
    "cib": "cib",
    "new": "new",
    "graded": "graded",
    "box_only": "boxonly",
    "manual_only": "manualonly",
}


# --- Parsing (pure functions; tested against saved fixtures) -----------------


def parse_money(text: str | None) -> Decimal | None:
    if not text:
        return None
    cleaned = re.sub(r"[^\d.]", "", text)
    if not cleaned:
        return None
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        return None
    return value if value > 0 else None


def _text(node: Node | None) -> str | None:
    if node is None:
        return None
    return " ".join(node.text(deep=True).split()) or None


def console_slug_from_url(url: str) -> str | None:
    parts = urlparse(url).path.strip("/").split("/")
    return parts[1] if len(parts) >= 3 and parts[0] == "game" else None


def _cell_price(cell: Node | None) -> Decimal | None:
    if cell is None:
        return None
    # The first .js-price is the price; later ones are the +/- change.
    price = cell.css_first(".price.js-price") or cell.css_first(".js-price")
    return parse_money(_text(price))


def _parse_history(html: str) -> dict[date, PriceSet]:
    m = re.search(r"VGPC\.chart_data\s*=\s*(\{.*?\});", html, re.S)
    if not m:
        return {}
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError:
        return {}
    history: dict[date, PriceSet] = {}
    for field, key in CHART_KEYS.items():
        for point in data.get(key) or []:
            try:
                ts, cents = point
            except (TypeError, ValueError):
                continue
            if not cents:
                continue
            day = datetime.fromtimestamp(ts / 1000, UTC).date()
            setattr(history.setdefault(day, PriceSet()), field, Decimal(cents) / 100)
    return history


def _parse_date(text: str | None) -> date | None:
    if not text:
        return None
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def parse_product_page(html: str, url: str) -> ProductPage:
    tree = HTMLParser(html)
    title_node = tree.css_first("h1#product_name")
    if title_node is None:
        raise ParseError("Product title (#product_name) not found", html=html)

    source_id = (title_node.attributes.get("title") or "").strip()
    if not source_id.isdigit():
        m = re.search(r"VGPC\.product\s*=\s*\{\s*id:\s*(\d+)", html)
        source_id = m.group(1) if m else ""
    if not source_id:
        raise ParseError("Product id not found", html=html)

    console_link = title_node.css_first("a")
    console_name = _text(console_link)
    # Title is the h1 text minus the console link text.
    title = (title_node.text(deep=False) or "").strip() or (_text(title_node) or "")
    title = " ".join(title.split())

    prices = PriceSet()
    for field, element_id in PRICE_IDS.items():
        setattr(prices, field, _cell_price(tree.css_first(f"td#{element_id}")))
    if prices.is_empty() and tree.css_first("td#used_price") is None:
        raise ParseError("Price table not found", html=html)

    image = tree.css_first("#product_details img, .cover img, img[src*='images.pricecharting.com']")
    image_url = image.attributes.get("src") if image else None

    return ProductPage(
        source_id=source_id,
        title=title,
        url=url.split("?")[0],
        console_name=console_name,
        console_slug=console_slug_from_url(url),
        is_system=bool(re.search(r"is_system:\s*true", html)),
        prices=prices,
        history=_parse_history(html),
        image_url=image_url,
        genre=_text(tree.css_first('td[itemprop="genre"]')),
        release_date=_parse_date(_text(tree.css_first('td[itemprop="datePublished"]'))),
    )


def parse_search_page(html: str) -> list[SearchResult]:
    tree = HTMLParser(html)
    table = tree.css_first("table#games_table")
    if table is None:
        return []
    results = []
    for row in table.css("tr[data-product]"):
        link = row.css_first("td.title a")
        if link is None:
            continue
        url = link.attributes.get("href") or ""
        if url.startswith("/"):
            url = BASE_URL + url
        img = row.css_first("td.image img")
        results.append(
            SearchResult(
                source_id=row.attributes.get("data-product") or "",
                title=_text(link) or "",
                url=url,
                console_name=_text(row.css_first("td.console"))
                or _text(row.css_first(".console-in-title a")),
                console_slug=console_slug_from_url(url),
                image_url=img.attributes.get("src") if img else None,
                prices=PriceSet(
                    loose=_cell_price(row.css_first("td.used_price")),
                    cib=_cell_price(row.css_first("td.cib_price")),
                    new=_cell_price(row.css_first("td.new_price")),
                ),
            )
        )
    return results


# --- HTTP client --------------------------------------------------------------


class RateLimiter:
    """Process-wide: at most one request per random [min_delay, max_delay] seconds."""

    def __init__(self, min_delay: float, max_delay: float, sleep: Callable[[float], None] = time.sleep):
        self.min_delay = min_delay
        self.max_delay = max_delay
        self._sleep = sleep
        self._lock = threading.Lock()
        self._next_at = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            if now < self._next_at:
                self._sleep(self._next_at - now)
            self._next_at = time.monotonic() + random.uniform(self.min_delay, self.max_delay)


class PriceChartingProvider:
    def __init__(
        self,
        limiter: RateLimiter,
        *,
        max_retries: int = 3,
        timeout: float = 20.0,
        sleep: Callable[[float], None] = time.sleep,
        transport: httpx.BaseTransport | None = None,
    ):
        self.limiter = limiter
        self.max_retries = max_retries
        self._sleep = sleep
        self._client = httpx.Client(
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "en-US,en;q=0.9",
            },
            timeout=timeout,
            follow_redirects=True,
            transport=transport,
        )

    def _get(self, url: str) -> httpx.Response:
        last_error: PriceProviderError | None = None
        for attempt in range(self.max_retries + 1):
            if attempt:
                backoff = min(300, 15 * 2 ** (attempt - 1)) + random.uniform(0, 5)
                log.info("Retrying %s in %.0fs (attempt %d)", url, backoff, attempt + 1)
                self._sleep(backoff)
            self.limiter.wait()
            try:
                resp = self._client.get(url)
            except httpx.HTTPError as e:
                last_error = NetworkError(f"{type(e).__name__}: {e}")
                continue
            if resp.status_code == 200:
                if "challenge-platform" in resp.text[:5000] or "cf-chl" in resp.text[:5000]:
                    raise BlockedError("Bot challenge page returned", status=200, html=resp.text)
                return resp
            if resp.status_code == 404:
                raise NotFoundError("Page not found", status=404)
            if resp.status_code in (403, 429):
                last_error = BlockedError(f"HTTP {resp.status_code}", status=resp.status_code)
            elif resp.status_code >= 500:
                last_error = PriceProviderError(f"HTTP {resp.status_code}", status=resp.status_code)
            else:
                raise PriceProviderError(f"HTTP {resp.status_code}", status=resp.status_code)
        assert last_error is not None
        raise last_error

    def search(self, query: str) -> list[SearchResult]:
        resp = self._get(f"{BASE_URL}/search-products?{urlencode({'q': query, 'type': 'prices'})}")
        # A single strong match redirects straight to the product page.
        if urlparse(str(resp.url)).path.startswith("/game/"):
            page = parse_product_page(resp.text, str(resp.url))
            return [
                SearchResult(
                    source_id=page.source_id,
                    title=page.title,
                    url=page.url,
                    console_name=page.console_name,
                    console_slug=page.console_slug,
                    image_url=page.image_url,
                    prices=page.prices,
                )
            ]
        return parse_search_page(resp.text)

    def fetch(self, url: str) -> ProductPage:
        if not is_pricecharting_url(url):
            raise PriceProviderError("Not a PriceCharting product URL")
        resp = self._get(url)
        if not urlparse(str(resp.url)).path.startswith("/game/"):
            # Renamed pages redirect to a search for the old name.
            raise NotFoundError(
                "PriceCharting page has moved (redirected to a search)", status=resp.status_code
            )
        return parse_product_page(resp.text, str(resp.url))

    def download(self, url: str) -> bytes:
        # Images come from a CDN, not the site itself; no need to rate limit.
        resp = self._client.get(url)
        resp.raise_for_status()
        return resp.content


PC_HOSTS = ("pricecharting.com", "www.pricecharting.com", "videogames.pricecharting.com")


def normalize_pricecharting_url(url: str) -> str | None:
    """Canonical https://www.pricecharting.com/game/<console>/<slug> for current and legacy links
    (http, the old videogames. subdomain, search ?q= suffixes). None if not a game page."""
    parsed = urlparse((url or "").strip())
    if parsed.scheme not in ("http", "https") or parsed.netloc.lower() not in PC_HOSTS:
        return None
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) != 3 or parts[0] != "game":
        return None
    return f"{BASE_URL}/game/{parts[1]}/{parts[2]}"


def is_pricecharting_url(url: str) -> bool:
    parsed = urlparse(url)
    return (
        parsed.scheme == "https"
        and parsed.netloc in ("www.pricecharting.com", "pricecharting.com")
        and parsed.path.startswith("/game/")
    )
