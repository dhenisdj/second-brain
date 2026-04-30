import asyncio
import json
import logging
from datetime import date as date_type, datetime

from fastapi import HTTPException
from sqlalchemy import func, select

from app.database import get_session_factory
from app.models.event import Event
from app.services import analysis_service, graph_service, plan_service, summary_service
from app.services.llm_service import LLMTimeoutError
from app.services import job_service
from app.routers.ingest import ConfiguredSourcesRequest, ingest_configured_sources

logger = logging.getLogger(__name__)
_running_tasks: dict[str, asyncio.Task] = {}


async def _handle_summary_generate(db, payload: dict) -> dict:
    date_str = payload["date"]
    analysis_result = await analysis_service.run_analysis(db, date_str)
    result = await summary_service.generate_summary(db, date_str)
    graph_job, created = await job_service.enqueue_job(
        db,
        job_type=job_service.JOB_TYPE_GRAPH_REFRESH,
        payload={"date": date_str},
        resource_key=job_service.graph_refresh_resource_key(date_str),
    )
    if created:
        schedule_job(graph_job["id"])
    result["analysis"] = analysis_result
    result["graph_job_id"] = graph_job["id"]
    return result


async def _handle_plan_generate(db, payload: dict) -> dict:
    return await plan_service.generate_plan(db, payload["date"])


async def _handle_graph_refresh(db, payload: dict) -> dict:
    return await graph_service.refresh_graph_for_date(db, payload["date"])


async def _handle_graph_rebuild(db, _payload: dict) -> dict:
    return await graph_service.rebuild_graph(db)


async def _collect_and_summarize(db, date_str: str, collect_days: int) -> dict:
    try:
        collection_result = await ingest_configured_sources(
            ConfiguredSourcesRequest(days=collect_days, target_date=date_str),
            db,
        )
    except HTTPException as exc:
        detail = exc.detail
        if isinstance(detail, dict):
            detail = json.dumps(detail, ensure_ascii=False)
        raise ValueError(str(detail)) from exc

    target = date_type.fromisoformat(date_str)
    start = datetime.combine(target, datetime.min.time())
    end = datetime.combine(target, datetime.max.time())
    event_count = await db.scalar(
        select(func.count(Event.id)).where(Event.timestamp >= start, Event.timestamp <= end)
    )

    if not event_count:
        skipped = {
            "status": "skipped",
            "reason": "No events found for this date.",
        }
        return {
            "date": date_str,
            "event_count": 0,
            "collection": collection_result,
            "summary": skipped,
        }

    summary_result = await _handle_summary_generate(db, {"date": date_str})
    return {
        "date": date_str,
        "event_count": event_count,
        "collection": collection_result,
        "summary": summary_result,
    }


async def _handle_daily_pipeline(db, payload: dict) -> dict:
    date_str = payload["date"]
    collect_days = int(payload.get("collect_days") or 2)
    result = await _collect_and_summarize(db, date_str, collect_days)

    if result.get("summary", {}).get("status") == "skipped":
        result["plan"] = {
            "status": "skipped",
            "reason": "No events found for this date.",
        }
        return result

    plan_result = await _handle_plan_generate(db, {"date": date_str})
    return {
        **result,
        "plan": plan_result,
    }


async def _handle_day_refresh(db, payload: dict) -> dict:
    date_str = payload["date"]
    collect_days = int(payload.get("collect_days") or 1)
    return await _collect_and_summarize(db, date_str, collect_days)


_JOB_HANDLERS = {
    job_service.JOB_TYPE_SUMMARY_GENERATE: _handle_summary_generate,
    job_service.JOB_TYPE_PLAN_GENERATE: _handle_plan_generate,
    job_service.JOB_TYPE_GRAPH_REFRESH: _handle_graph_refresh,
    job_service.JOB_TYPE_GRAPH_REBUILD: _handle_graph_rebuild,
    job_service.JOB_TYPE_DAILY_PIPELINE: _handle_daily_pipeline,
    job_service.JOB_TYPE_DAY_REFRESH: _handle_day_refresh,
}


async def _run_job(job_id: str):
    session_factory = get_session_factory()
    try:
        async with session_factory() as db:
            job = await job_service.get_job_model(db, job_id)
            if not job:
                return
            if job.status == job_service.JOB_STATUS_COMPLETED:
                return

            await job_service.mark_job_running(db, job)
            handler = _JOB_HANDLERS.get(job.job_type)
            if not handler:
                raise ValueError(f"Unsupported job type: {job.job_type}")
            payload = job_service._load_json(job.payload) or {}
            result = await handler(db, payload)
            job = await job_service.get_job_model(db, job_id)
            if job:
                await job_service.mark_job_completed(db, job, result)
    except LLMTimeoutError:
        async with session_factory() as db:
            job = await job_service.get_job_model(db, job_id)
            if job:
                await job_service.mark_job_failed(
                    db,
                    job,
                    "LLM 响应超时，请稍后重试，或切换更快模型后再执行。",
                )
    except Exception as exc:
        logger.exception("Background job failed: %s", job_id)
        async with session_factory() as db:
            job = await job_service.get_job_model(db, job_id)
            if job:
                await job_service.mark_job_failed(db, job, str(exc))


def schedule_job(job_id: str) -> bool:
    current = _running_tasks.get(job_id)
    if current and not current.done():
        return False

    task = asyncio.create_task(_run_job(job_id))
    _running_tasks[job_id] = task
    task.add_done_callback(lambda _task, current_job_id=job_id: _running_tasks.pop(current_job_id, None))
    return True


async def resume_incomplete_jobs():
    session_factory = get_session_factory()
    async with session_factory() as db:
        job_ids = await job_service.list_incomplete_job_ids(db)
    for job_id in job_ids:
        schedule_job(job_id)


async def shutdown_job_executor():
    tasks = list(_running_tasks.values())
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    _running_tasks.clear()
