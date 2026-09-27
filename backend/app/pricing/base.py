"""Provider-agnostic price types. PriceCharting is the first implementation."""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Protocol

CONDITION_FIELDS = ("loose", "cib", "new", "graded", "box_only", "manual_only")


@dataclass
class PriceSet:
    loose: Decimal | None = None
    cib: Decimal | None = None
    new: Decimal | None = None
    graded: Decimal | None = None
    box_only: Decimal | None = None
    manual_only: Decimal | None = None

    def is_empty(self) -> bool:
        return all(getattr(self, f) is None for f in CONDITION_FIELDS)

    def as_dict(self) -> dict[str, Decimal | None]:
        return {f: getattr(self, f) for f in CONDITION_FIELDS}


@dataclass
class SearchResult:
    source_id: str
    title: str
    url: str
    console_name: str | None
    console_slug: str | None
    image_url: str | None
    prices: PriceSet


@dataclass
class ProductPage:
    source_id: str
    title: str
    url: str
    console_name: str | None
    console_slug: str | None
    is_system: bool
    prices: PriceSet
    history: dict[date, PriceSet] = field(default_factory=dict)
    image_url: str | None = None
    genre: str | None = None
    release_date: date | None = None


class PriceProviderError(Exception):
    """Base error. `kind` is one of: http, blocked, parse, network."""

    kind = "http"

    def __init__(self, message: str, *, status: int | None = None, html: str | None = None):
        super().__init__(message)
        self.status = status
        self.html = html


class BlockedError(PriceProviderError):
    kind = "blocked"


class ParseError(PriceProviderError):
    kind = "parse"


class NetworkError(PriceProviderError):
    kind = "network"


class NotFoundError(PriceProviderError):
    kind = "http"


class PriceProvider(Protocol):
    def search(self, query: str) -> list[SearchResult]: ...

    def fetch(self, url: str) -> ProductPage: ...

    def download(self, url: str) -> bytes: ...
