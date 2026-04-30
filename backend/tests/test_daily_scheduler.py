from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.services.daily_scheduler import (
    _next_daily_run,
    _next_interval_run,
    _target_date_for_run,
    enqueue_current_day_refresh,
    enqueue_daily_pipeline,
)


def test_next_daily_run_uses_next_three_am():
    tz = ZoneInfo("Asia/Shanghai")
    before_three = datetime(2026, 4, 30, 2, 59, tzinfo=tz)
    at_three = datetime(2026, 4, 30, 3, 0, tzinfo=tz)

    assert _next_daily_run(before_three) == datetime(2026, 4, 30, 3, 0, tzinfo=tz)
    assert _next_daily_run(at_three) == datetime(2026, 5, 1, 3, 0, tzinfo=tz)


def test_target_date_is_previous_day():
    tz = ZoneInfo("Asia/Shanghai")

    assert _target_date_for_run(datetime(2026, 5, 1, 3, 0, tzinfo=tz)) == "2026-04-30"


def test_next_interval_run_uses_next_four_hour_bucket():
    tz = ZoneInfo("Asia/Shanghai")

    assert _next_interval_run(datetime(2026, 4, 30, 11, 59, tzinfo=tz), 4) == datetime(2026, 4, 30, 12, 0, tzinfo=tz)
    assert _next_interval_run(datetime(2026, 4, 30, 12, 0, tzinfo=tz), 4) == datetime(2026, 4, 30, 16, 0, tzinfo=tz)
    assert _next_interval_run(datetime(2026, 4, 30, 23, 59, tzinfo=tz), 4) == datetime(2026, 5, 1, 0, 0, tzinfo=tz)


async def test_enqueue_daily_pipeline_dedupes_same_date(client):
    with patch("app.services.daily_scheduler.schedule_job") as mock_schedule:
        first = await enqueue_daily_pipeline("2026-04-03")
        second = await enqueue_daily_pipeline("2026-04-03")

    assert first["id"] == second["id"]
    assert first["job_type"] == "daily.pipeline"
    assert mock_schedule.call_count == 1


async def test_enqueue_current_day_refresh_dedupes_same_bucket(client):
    tz = ZoneInfo("Asia/Shanghai")
    run_at = datetime(2026, 4, 30, 12, 0, tzinfo=tz)

    with patch("app.services.daily_scheduler.schedule_job") as mock_schedule:
        first = await enqueue_current_day_refresh(run_at)
        second = await enqueue_current_day_refresh(run_at)

    assert first["id"] == second["id"]
    assert first["job_type"] == "day.refresh"
    assert first["payload"]["date"] == "2026-04-30"
    assert first["payload"]["bucket"] == "1200"
    assert mock_schedule.call_count == 1
