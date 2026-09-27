"""Collection analytics computed from price snapshots.

Historical values answer "what were the items I hold now worth on date X" — current
holdings valued with the latest price on or before each date. Items with no price
yet on a date contribute nothing to that date.
"""

from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CollectionItem, PriceSnapshot
from app.models.enums import ItemStatus
from app.pricing.base import CONDITION_FIELDS
from app.services.filters import ItemFilters, items_query

GROUPINGS = ("brand", "platform", "era", "media_type", "category", "condition", "genre", "status", "region")


@dataclass
class Series:
    """Non-null prices for one item's condition, sorted by date."""

    dates: list[date]
    prices: list[Decimal]

    def at(self, day: date) -> Decimal | None:
        i = bisect_right(self.dates, day)
        return self.prices[i - 1] if i else None

    @property
    def latest(self) -> Decimal | None:
        return self.prices[-1] if self.prices else None

    @property
    def first_date(self) -> date | None:
        return self.dates[0] if self.dates else None


@dataclass
class Holding:
    item: CollectionItem
    series: Series

    @property
    def qty(self) -> int:
        return self.item.quantity

    @property
    def cost(self) -> Decimal:
        return (self.item.purchase_price or Decimal(0)) * self.qty

    def value_at(self, day: date) -> Decimal | None:
        price = self.series.at(day)
        return price * self.qty if price is not None else None

    @property
    def value(self) -> Decimal | None:
        price = self.series.latest
        return price * self.qty if price is not None else None


def load_holdings(db: Session, user_id: int, filters: ItemFilters) -> list[Holding]:
    if not filters.status:
        filters.status = [ItemStatus.owned]
    items = list(db.scalars(items_query(user_id, filters)).unique())
    product_ids = {i.product_id for i in items}
    raw: dict[int, list[PriceSnapshot]] = defaultdict(list)
    if product_ids:
        rows = db.execute(
            select(
                PriceSnapshot.product_id,
                PriceSnapshot.captured_on,
                *[getattr(PriceSnapshot, f) for f in CONDITION_FIELDS],
            )
            .where(PriceSnapshot.product_id.in_(product_ids))
            .order_by(PriceSnapshot.captured_on)
        ).all()
        for row in rows:
            raw[row.product_id].append(row)

    holdings = []
    for item in items:
        dates, prices = [], []
        for row in raw.get(item.product_id, []):
            price = getattr(row, item.condition)
            if price is not None:
                dates.append(row.captured_on)
                prices.append(price)
        holdings.append(Holding(item, Series(dates, prices)))
    return holdings


def _pct(new: Decimal, old: Decimal) -> float | None:
    return float((new - old) / old * 100) if old else None


def overview(holdings: list[Holding], today: date) -> dict:
    priced = [h for h in holdings if h.value is not None]
    total = sum((h.value for h in priced), Decimal(0))
    cost = sum((h.cost for h in holdings), Decimal(0))
    # Gain only over items that have both a cost and a price, so unpriced items don't distort it.
    comparable = [h for h in priced if h.item.purchase_price is not None]
    comp_value = sum((h.value for h in comparable), Decimal(0))
    comp_cost = sum((h.cost for h in comparable), Decimal(0))

    changes = {}
    for label, days in (("7d", 7), ("30d", 30), ("1y", 365)):
        then_day = today - timedelta(days=days)
        pairs = [(h.value, h.value_at(then_day)) for h in priced]
        pairs = [(now, then) for now, then in pairs if then is not None]
        now_sum = sum((p[0] for p in pairs), Decimal(0))
        then_sum = sum((p[1] for p in pairs), Decimal(0))
        changes[label] = {"change": float(now_sum - then_sum), "pct": _pct(now_sum, then_sum)}

    return {
        "total_value": float(total),
        "cost_basis": float(cost),
        "gain": float(comp_value - comp_cost),
        "gain_pct": _pct(comp_value, comp_cost),
        "items": len(holdings),
        "quantity": sum(h.qty for h in holdings),
        "priced": len(priced),
        "unpriced": len(holdings) - len(priced),
        "changes": changes,
    }


def _buckets(start: date, end: date, step: str) -> list[date]:
    days: list[date] = []
    if step == "day":
        d = start
        while d <= end:
            days.append(d)
            d += timedelta(days=1)
    elif step == "week":
        d = start
        while d <= end:
            days.append(d)
            d += timedelta(days=7)
    else:  # month: first of each month
        d = date(start.year, start.month, 1)
        while d <= end:
            if d >= start:
                days.append(d)
            d = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    if not days or days[-1] != end:
        days.append(end)
    return days


RANGES = {"3m": (91, "day"), "1y": (365, "week"), "5y": (365 * 5, "month"), "all": (None, "month")}


def timeseries(holdings: list[Holding], today: date, range_: str) -> list[dict]:
    span, step = RANGES[range_]
    if span is None:
        firsts = [h.series.first_date for h in holdings if h.series.first_date]
        start = min(firsts) if firsts else today
    else:
        start = today - timedelta(days=span)
    points = []
    for day in _buckets(start, today, step):
        value = Decimal(0)
        priced = 0
        cost = Decimal(0)
        for h in holdings:
            v = h.value_at(day)
            if v is not None:
                value += v
                priced += 1
            bought = h.item.purchase_date
            if h.item.purchase_price is not None and (bought is None or bought <= day):
                cost += h.cost
        points.append({"date": day, "value": float(value), "cost": float(cost), "priced": priced})
    return points


def _group_key(h: Holding, by: str) -> str:
    product = h.item.product
    platform = product.platform
    return {
        "brand": platform.brand,
        "platform": platform.name,
        "era": platform.era,
        "media_type": platform.media_type,
        "category": product.category,
        "condition": h.item.condition,
        "genre": product.genre,
        "status": h.item.status,
        "region": product.region or platform.region,
    }[by] or "Unknown"


def breakdown(holdings: list[Holding], by: str) -> list[dict]:
    groups: dict[str, dict] = {}
    for h in holdings:
        key = _group_key(h, by)
        g = groups.setdefault(
            key, {"key": key, "value": Decimal(0), "cost": Decimal(0), "items": 0, "quantity": 0}
        )
        g["value"] += h.value or 0
        g["cost"] += h.cost
        g["items"] += 1
        g["quantity"] += h.qty
    out = sorted(groups.values(), key=lambda g: (-g["value"], g["key"]))
    return [{**g, "value": float(g["value"]), "cost": float(g["cost"])} for g in out]


def movers(holdings: list[Holding], today: date, days: int, min_value: Decimal, limit: int) -> dict:
    then_day = today - timedelta(days=days)
    rows = []
    for h in holdings:
        now, then = h.series.latest, h.series.at(then_day)
        if now is None or then is None or max(now, then) < min_value or now == then:
            continue
        rows.append(
            {
                "item_id": h.item.id,
                "product_id": h.item.product_id,
                "title": h.item.product.title,
                "platform": h.item.product.platform.name,
                "condition": h.item.condition,
                "has_image": h.item.product.has_image,
                "quantity": h.qty,
                "price": float(now),
                "then": float(then),
                "change": float(now - then),
                "pct": _pct(now, then),
                "value_change": float((now - then) * h.qty),
            }
        )
    gainers = sorted((r for r in rows if r["change"] > 0), key=lambda r: -r["value_change"])[:limit]
    losers = sorted((r for r in rows if r["change"] < 0), key=lambda r: r["value_change"])[:limit]
    return {"since": then_day, "gainers": gainers, "losers": losers}


def top_items(holdings: list[Holding], limit: int) -> list[dict]:
    ranked = sorted((h for h in holdings if h.value is not None), key=lambda h: -h.value)[:limit]
    return [
        {
            "item_id": h.item.id,
            "product_id": h.item.product_id,
            "title": h.item.product.title,
            "platform": h.item.product.platform.name,
            "condition": h.item.condition,
            "has_image": h.item.product.has_image,
            "quantity": h.qty,
            "price": float(h.series.latest),
            "value": float(h.value),
            "cost": float(h.cost) if h.item.purchase_price is not None else None,
        }
        for h in ranked
    ]
