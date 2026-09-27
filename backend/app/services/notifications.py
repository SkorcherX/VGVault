"""Price alerts sent through Apprise (Discord, ntfy, email, Telegram, ...).

After each price update run, every user with notifications enabled gets at most one
digest message listing:
  * owned items whose price moved by at least `move_pct` since the previous snapshot
  * wishlist items whose price dropped to or below their target price
Each (item, kind, snapshot date) is announced once, tracked in NotificationLog.
"""

import logging
from dataclasses import dataclass
from decimal import Decimal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CollectionItem, NotificationLog, PriceSnapshot, User
from app.models.enums import ItemStatus

log = logging.getLogger(__name__)


class NotificationSettings(BaseModel):
    enabled: bool = False
    urls: list[str] = Field(default_factory=list, max_length=10)
    price_moves: bool = True
    move_pct: float = Field(10.0, gt=0, le=1000)
    move_min_value: Decimal = Field(Decimal(10), ge=0)
    wishlist_targets: bool = True


def get_settings(user: User) -> NotificationSettings:
    return NotificationSettings(**(user.notify or {}))


def send(urls: list[str], title: str, body: str) -> bool:
    import apprise  # heavy import; only load when sending

    ap = apprise.Apprise()
    for url in urls:
        ap.add(url)
    if len(ap) == 0:
        raise ValueError("No valid notification URLs")
    return bool(ap.notify(title=title, body=body))


@dataclass
class Alert:
    item_id: int
    kind: str  # move | wishlist
    captured_on: object
    line: str


def _last_two(db: Session, product_ids: set[int]) -> dict[int, list[PriceSnapshot]]:
    out: dict[int, list[PriceSnapshot]] = {}
    if not product_ids:
        return out
    rows = db.scalars(
        select(PriceSnapshot)
        .where(PriceSnapshot.product_id.in_(product_ids))
        .order_by(PriceSnapshot.product_id, PriceSnapshot.captured_on.desc())
    )
    for snap in rows:
        bucket = out.setdefault(snap.product_id, [])
        if len(bucket) < 2:
            bucket.append(snap)
    return out


def _money(v: Decimal) -> str:
    return f"${v:,.2f}"


def find_alerts(db: Session, user: User, settings: NotificationSettings) -> list[Alert]:
    items = list(
        db.scalars(
            select(CollectionItem).where(
                CollectionItem.user_id == user.id,
                CollectionItem.status.in_([ItemStatus.owned, ItemStatus.wishlist]),
            )
        ).unique()
    )
    snaps = _last_two(db, {i.product_id for i in items})
    alerts = []
    for item in items:
        pair = snaps.get(item.product_id, [])
        if not pair:
            continue
        latest = pair[0]
        now = getattr(latest, item.condition)
        before = getattr(pair[1], item.condition) if len(pair) > 1 else None
        if now is None:
            continue
        name = f"{item.product.title} ({item.product.platform.name}, {item.condition})"

        if item.status == ItemStatus.owned and settings.price_moves and before:
            pct = float((now - before) / before * 100)
            if abs(pct) >= settings.move_pct and max(now, before) >= settings.move_min_value:
                arrow = "▲" if pct > 0 else "▼"
                alerts.append(
                    Alert(
                        item.id,
                        "move",
                        latest.captured_on,
                        f"{arrow} {name}: {_money(before)} → {_money(now)} ({pct:+.1f}%)",
                    )
                )

        if (
            item.status == ItemStatus.wishlist
            and settings.wishlist_targets
            and item.target_price is not None
            and now <= item.target_price
            and (before is None or before > item.target_price)
        ):
            alerts.append(
                Alert(
                    item.id,
                    "wishlist",
                    latest.captured_on,
                    f"🎯 {name} is {_money(now)} (target {_money(item.target_price)})",
                )
            )
    return alerts


def _unsent(db: Session, user: User, alerts: list[Alert]) -> list[Alert]:
    sent = set(
        db.execute(
            select(NotificationLog.item_id, NotificationLog.kind, NotificationLog.captured_on).where(
                NotificationLog.user_id == user.id
            )
        ).all()
    )
    return [a for a in alerts if (a.item_id, a.kind, a.captured_on) not in sent]


def notify_user(db: Session, user: User) -> int:
    settings = get_settings(user)
    if not settings.enabled or not settings.urls:
        return 0
    alerts = _unsent(db, user, find_alerts(db, user, settings))
    if not alerts:
        return 0
    moves = [a.line for a in alerts if a.kind == "move"]
    wishes = [a.line for a in alerts if a.kind == "wishlist"]
    parts = []
    if wishes:
        parts.append("Wishlist targets hit:\n" + "\n".join(wishes))
    if moves:
        parts.append("Price moves:\n" + "\n".join(moves))
    title = f"VGVault: {len(alerts)} price alert{'s' * (len(alerts) != 1)}"
    try:
        ok = send(settings.urls, title, "\n\n".join(parts))
    except Exception:
        log.exception("Notification to user %s failed", user.id)
        ok = False
    if not ok:
        return 0  # nothing recorded, so the next run retries
    for a in alerts:
        db.add(NotificationLog(user_id=user.id, item_id=a.item_id, kind=a.kind, captured_on=a.captured_on))
    db.commit()
    return len(alerts)


def notify_all(db: Session) -> int:
    sent = 0
    for user in db.scalars(select(User).where(User.is_active)):
        try:
            sent += notify_user(db, user)
        except Exception:
            log.exception("Evaluating alerts for user %s failed", user.id)
            db.rollback()
    return sent
