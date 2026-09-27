from collections.abc import Iterable

from sqlalchemy.orm import Session

from app.models import CollectionItem
from app.services.pricing import latest_prices


def attach_prices(db: Session, items: Iterable[CollectionItem]) -> list[CollectionItem]:
    """Set market_price / value / priced_on on each item from the latest snapshot."""
    items = list(items)
    latest = latest_prices(db, list({i.product_id for i in items}))
    for item in items:
        snap = latest.get(item.product_id)
        price = getattr(snap, item.condition, None) if snap else None
        item.market_price = price
        item.value = price * item.quantity if price is not None else None
        item.priced_on = snap.captured_on if snap else None
    return items
