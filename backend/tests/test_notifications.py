from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.core.db import SessionLocal
from app.models import PriceSnapshot
from app.services import notifications

TODAY = datetime.now(UTC).date()


@pytest.fixture
def sent(monkeypatch):
    messages = []

    def fake_send(urls, title, body):
        messages.append((urls, title, body))
        return True

    monkeypatch.setattr(notifications, "send", fake_send)
    return messages


def _item(client, title, prices, **fields):
    platform = next(p["id"] for p in client.get("/api/platforms").json() if p["slug"] == "n64")
    product = client.post("/api/products", json={"title": title, "platform_id": platform}).json()
    with SessionLocal() as db:
        for days_ago, price in prices.items():
            db.add(
                PriceSnapshot(
                    product_id=product["id"],
                    captured_on=TODAY - timedelta(days=days_ago),
                    loose=Decimal(str(price)),
                )
            )
        db.commit()
    return client.post("/api/collection", json={"product_id": product["id"], **fields}).json()


def _enable(client, **overrides):
    body = {"enabled": True, "urls": ["json://localhost/hook"], **overrides}
    r = client.put("/api/auth/notifications", json=body)
    assert r.status_code == 200, r.text


def _run():
    with SessionLocal() as db:
        return notifications.notify_all(db)


def test_settings_roundtrip(admin):
    assert admin.get("/api/auth/notifications").json()["enabled"] is False
    _enable(admin, urls=["  json://localhost/a  ", ""], move_pct=25)
    s = admin.get("/api/auth/notifications").json()
    assert s["urls"] == ["json://localhost/a"] and s["move_pct"] == 25


def test_moves_and_wishlist_digest_sent_once(admin, sent):
    _item(admin, "Up", {7: 100, 0: 130})  # +30%
    _item(admin, "Flat", {7: 100, 0: 102})  # +2%, below threshold
    _item(admin, "Cheap", {7: 2, 0: 4})  # +100% but under min value
    _item(admin, "Down", {7: 50, 0: 40})  # -20%
    _item(admin, "Wanted", {7: 80, 0: 55}, status="wishlist", target_price="60")
    _item(admin, "Still pricey", {7: 90, 0: 70}, status="wishlist", target_price="60")
    _enable(admin)

    assert _run() == 3
    assert len(sent) == 1
    _, title, body = sent[0]
    assert title == "VGVault: 3 price alerts"
    assert "Up" in body and "+30.0%" in body and "Down" in body and "Wanted" in body
    assert "Flat" not in body and "Cheap" not in body and "Still pricey" not in body

    # Same snapshots -> nothing new
    assert _run() == 0 and len(sent) == 1


def test_disabled_or_no_urls_sends_nothing(admin, sent):
    _item(admin, "Up", {7: 100, 0: 200})
    assert _run() == 0
    _enable(admin, urls=[])
    assert _run() == 0
    assert sent == []


def test_failed_delivery_retries_next_time(admin, monkeypatch):
    _item(admin, "Up", {7: 100, 0: 200})
    _enable(admin)
    monkeypatch.setattr(notifications, "send", lambda *a: False)
    assert _run() == 0
    monkeypatch.setattr(notifications, "send", lambda *a: True)
    assert _run() == 1


def test_test_endpoint(admin, sent):
    assert admin.post("/api/auth/notifications/test").status_code == 400
    _enable(admin)
    assert admin.post("/api/auth/notifications/test").json() == {"sent": True}
