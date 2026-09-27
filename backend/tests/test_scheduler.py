from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.services.scheduler import cron_trigger

UTC = ZoneInfo("UTC")


def _next(expr: str, now: datetime) -> datetime:
    return cron_trigger(expr, "UTC").get_next_fire_time(None, now)


@pytest.mark.parametrize(
    ("expr", "weekday"),
    [("0 3 * * 0", 6), ("0 3 * * 7", 6), ("0 3 * * 1", 0), ("0 3 * * 6", 5)],
)
def test_weekday_numbers_follow_standard_cron(expr, weekday):
    # Sunday 2026-09-27 12:00 UTC
    nxt = _next(expr, datetime(2026, 9, 27, 12, tzinfo=UTC))
    assert nxt.weekday() == weekday and nxt.hour == 3


def test_weekday_ranges_and_lists():
    now = datetime(2026, 9, 27, 12, tzinfo=UTC)  # Sunday
    assert _next("0 3 * * 1-5", now).weekday() == 0  # Monday
    assert _next("0 3 * * 0,3", now).weekday() == 2  # Wednesday


def test_invalid():
    with pytest.raises(ValueError):
        cron_trigger("0 3 * *")
