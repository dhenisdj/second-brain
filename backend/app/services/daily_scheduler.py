import asyncio
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.config import settings
from app.database import get_session_factory
from app.services import job_service
from app.services.job_executor import schedule_job

logger = logging.getLogger(__name__)

_daily_scheduler_task: asyncio.Task | None = None
_current_day_refresh_task: asyncio.Task | None = None


def _scheduler_timezone():
    try:
        return ZoneInfo(settings.DAILY_AUTOMATION_TIMEZONE)
    except ZoneInfoNotFoundError:
        logger.warning("Unknown DAILY_AUTOMATION_TIMEZONE=%s; using local timezone", settings.DAILY_AUTOMATION_TIMEZONE)
        return datetime.now().astimezone().tzinfo


def _next_daily_run(now: datetime) -> datetime:
    run_at = now.replace(
        hour=settings.DAILY_AUTOMATION_HOUR,
        minute=settings.DAILY_AUTOMATION_MINUTE,
        second=0,
        microsecond=0,
    )
    if run_at <= now:
        run_at += timedelta(days=1)
    return run_at


def _target_date_for_run(run_at: datetime) -> str:
    return (run_at.date() - timedelta(days=1)).isoformat()


def _next_interval_run(now: datetime, interval_hours: int) -> datetime:
    interval_minutes = max(1, interval_hours) * 60
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elapsed_minutes = int((now - day_start).total_seconds() // 60)
    next_bucket_minutes = ((elapsed_minutes // interval_minutes) + 1) * interval_minutes
    return day_start + timedelta(minutes=next_bucket_minutes)


def _refresh_bucket_for_run(run_at: datetime) -> str:
    return run_at.strftime("%H%M")


async def enqueue_daily_pipeline(date_str: str | None = None) -> dict:
    tz = _scheduler_timezone()
    target_date = date_str or _target_date_for_run(datetime.now(tz))
    resource_key = job_service.daily_pipeline_resource_key(target_date)
    session_factory = get_session_factory()

    async with session_factory() as db:
        job, created = await job_service.enqueue_singleton_job(
            db,
            job_type=job_service.JOB_TYPE_DAILY_PIPELINE,
            payload={
                "date": target_date,
                "collect_days": settings.DAILY_AUTOMATION_COLLECT_DAYS,
                "scheduled_at": datetime.now(tz).isoformat(),
            },
            resource_key=resource_key,
            statuses={
                job_service.JOB_STATUS_PENDING,
                job_service.JOB_STATUS_RUNNING,
                job_service.JOB_STATUS_COMPLETED,
            },
        )

    if created:
        schedule_job(job["id"])
    return job


async def enqueue_current_day_refresh(run_at: datetime | None = None) -> dict:
    tz = _scheduler_timezone()
    scheduled_run_at = run_at or datetime.now(tz)
    target_date = scheduled_run_at.date().isoformat()
    bucket = _refresh_bucket_for_run(scheduled_run_at)
    resource_key = job_service.day_refresh_resource_key(target_date, bucket)
    session_factory = get_session_factory()

    async with session_factory() as db:
        job, created = await job_service.enqueue_singleton_job(
            db,
            job_type=job_service.JOB_TYPE_DAY_REFRESH,
            payload={
                "date": target_date,
                "collect_days": settings.CURRENT_DAY_REFRESH_COLLECT_DAYS,
                "bucket": bucket,
                "scheduled_at": datetime.now(tz).isoformat(),
            },
            resource_key=resource_key,
            statuses={
                job_service.JOB_STATUS_PENDING,
                job_service.JOB_STATUS_RUNNING,
                job_service.JOB_STATUS_COMPLETED,
            },
        )

    if created:
        schedule_job(job["id"])
    return job


async def _daily_scheduler_loop():
    tz = _scheduler_timezone()
    logger.info(
        "Daily automation scheduler enabled: %02d:%02d %s",
        settings.DAILY_AUTOMATION_HOUR,
        settings.DAILY_AUTOMATION_MINUTE,
        settings.DAILY_AUTOMATION_TIMEZONE,
    )

    while True:
        now = datetime.now(tz)
        run_at = _next_daily_run(now)
        await asyncio.sleep(max(0, (run_at - now).total_seconds()))
        try:
            target_date = _target_date_for_run(datetime.now(tz))
            job = await enqueue_daily_pipeline(target_date)
            logger.info("Daily automation enqueued for %s: %s", target_date, job.get("id"))
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Daily automation scheduling failed")


async def _current_day_refresh_loop():
    tz = _scheduler_timezone()
    logger.info(
        "Current-day refresh scheduler enabled: every %s hours in %s",
        settings.CURRENT_DAY_REFRESH_INTERVAL_HOURS,
        settings.DAILY_AUTOMATION_TIMEZONE,
    )

    while True:
        now = datetime.now(tz)
        run_at = _next_interval_run(now, settings.CURRENT_DAY_REFRESH_INTERVAL_HOURS)
        await asyncio.sleep(max(0, (run_at - now).total_seconds()))
        try:
            job = await enqueue_current_day_refresh(run_at)
            logger.info(
                "Current-day refresh enqueued for %s bucket %s: %s",
                run_at.date().isoformat(),
                _refresh_bucket_for_run(run_at),
                job.get("id"),
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Current-day refresh scheduling failed")


def start_daily_scheduler() -> bool:
    global _daily_scheduler_task, _current_day_refresh_task
    started = False

    if settings.DAILY_AUTOMATION_ENABLED:
        if not _daily_scheduler_task or _daily_scheduler_task.done():
            _daily_scheduler_task = asyncio.create_task(_daily_scheduler_loop())
            started = True
    else:
        logger.info("Daily automation scheduler disabled")

    if settings.CURRENT_DAY_REFRESH_ENABLED:
        if not _current_day_refresh_task or _current_day_refresh_task.done():
            _current_day_refresh_task = asyncio.create_task(_current_day_refresh_loop())
            started = True
    else:
        logger.info("Current-day refresh scheduler disabled")

    return started


async def shutdown_daily_scheduler():
    global _daily_scheduler_task, _current_day_refresh_task
    tasks = [task for task in (_daily_scheduler_task, _current_day_refresh_task) if task]
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    _daily_scheduler_task = None
    _current_day_refresh_task = None
