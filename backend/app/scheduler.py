from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import settings
from app.database import SessionLocal
from app.jobs import refresh_replies, run_monitors

scheduler = BackgroundScheduler(timezone=ZoneInfo(settings.desk_timezone))


def _daily() -> None:
    with SessionLocal() as session:
        run_monitors(session)
        refresh_replies(session)


def start_scheduler() -> None:
    if scheduler.running:
        return
    scheduler.add_job(
        _daily,
        CronTrigger(hour=settings.desk_refresh_hour, minute=0, timezone=ZoneInfo(settings.desk_timezone)),
        id="daily-refresh",
        replace_existing=True,
    )
    scheduler.start()


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
