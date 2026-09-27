"""In-process APScheduler running the price update on the admin-configured cron."""

import logging
import os
import re
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.db import SessionLocal
from app.services.pricing import run_price_update
from app.services.settings import ScraperSettings, get_scraper_settings

log = logging.getLogger(__name__)
JOB_ID = "price_update"

_scheduler: BackgroundScheduler | None = None


_DOW_NAMES = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"]


def cron_trigger(expr: str, timezone: str | None = None) -> CronTrigger:
    """Build a trigger from standard crontab syntax.

    APScheduler 3's from_crontab() treats weekday 0 as Monday; standard cron (and the
    UI presets) use 0/7 = Sunday. Convert numeric weekdays to names to avoid the shift.
    """
    fields = expr.split()
    if len(fields) != 5:
        raise ValueError(f"Wrong number of fields; got {len(fields)}, expected 5")
    minute, hour, day, month, dow = fields
    dow = re.sub(r"(?<![/\d])\d+", lambda m: _DOW_NAMES[int(m.group()) % 7], dow)
    return CronTrigger(minute=minute, hour=hour, day=day, month=month, day_of_week=dow, timezone=timezone)


def _timezone() -> str:
    return os.environ.get("TZ") or "UTC"


def start() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    _scheduler = BackgroundScheduler(
        timezone=_timezone(), job_defaults={"coalesce": True, "max_instances": 1}
    )
    _scheduler.start()
    with SessionLocal() as db:
        apply(get_scraper_settings(db))


def shutdown() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None


def apply(settings: ScraperSettings) -> None:
    """(Re)schedule the job from settings."""
    if _scheduler is None:
        return
    if _scheduler.get_job(JOB_ID):
        _scheduler.remove_job(JOB_ID)
    if settings.enabled:
        _scheduler.add_job(
            run_price_update,
            cron_trigger(settings.cron, _timezone()),
            id=JOB_ID,
            kwargs={"trigger": "schedule"},
            misfire_grace_time=3600,
        )
        log.info("Price updates scheduled: %s (%s)", settings.cron, _timezone())


def run_now(force: bool = False) -> None:
    """Kick off a manual run in the scheduler's thread pool."""
    if _scheduler is None:
        raise RuntimeError("Scheduler not running")
    _scheduler.add_job(run_price_update, kwargs={"trigger": "manual", "force": force})


def next_run_time() -> datetime | None:
    job = _scheduler.get_job(JOB_ID) if _scheduler else None
    return job.next_run_time if job else None
