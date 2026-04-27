import asyncio
import logging

from app.database import get_session_factory
from app.services import graph_service, plan_service, summary_service
from app.services.llm_service import LLMTimeoutError
from app.services import job_service

logger = logging.getLogger(__name__)
_running_tasks: dict[str, asyncio.Task] = {}


async def _handle_summary_generate(db, payload: dict) -> dict:
    date_str = payload["date"]
    result = await summary_service.generate_summary(db, date_str)
    graph_job, created = await job_service.enqueue_job(
        db,
        job_type=job_service.JOB_TYPE_GRAPH_REFRESH,
        payload={"date": date_str},
        resource_key=job_service.graph_refresh_resource_key(date_str),
    )
    if created:
        schedule_job(graph_job["id"])
    result["graph_job_id"] = graph_job["id"]
    return result


async def _handle_plan_generate(db, payload: dict) -> dict:
    return await plan_service.generate_plan(db, payload["date"])


async def _handle_graph_refresh(db, payload: dict) -> dict:
    return await graph_service.refresh_graph_for_date(db, payload["date"])


async def _handle_graph_rebuild(db, _payload: dict) -> dict:
    return await graph_service.rebuild_graph(db)


_JOB_HANDLERS = {
    job_service.JOB_TYPE_SUMMARY_GENERATE: _handle_summary_generate,
    job_service.JOB_TYPE_PLAN_GENERATE: _handle_plan_generate,
    job_service.JOB_TYPE_GRAPH_REFRESH: _handle_graph_refresh,
    job_service.JOB_TYPE_GRAPH_REBUILD: _handle_graph_rebuild,
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
