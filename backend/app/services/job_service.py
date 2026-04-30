import json
from datetime import datetime

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job import Job

JOB_STATUS_PENDING = "pending"
JOB_STATUS_RUNNING = "running"
JOB_STATUS_COMPLETED = "completed"
JOB_STATUS_FAILED = "failed"
OPEN_JOB_STATUSES = {JOB_STATUS_PENDING, JOB_STATUS_RUNNING}

JOB_TYPE_SUMMARY_GENERATE = "summary.generate"
JOB_TYPE_PLAN_GENERATE = "plan.generate"
JOB_TYPE_GRAPH_REFRESH = "graph.refresh"
JOB_TYPE_GRAPH_REBUILD = "graph.rebuild"
JOB_TYPE_DAILY_PIPELINE = "daily.pipeline"
JOB_TYPE_DAY_REFRESH = "day.refresh"


def summary_resource_key(date_str: str) -> str:
    return f"{JOB_TYPE_SUMMARY_GENERATE}:{date_str}"


def plan_resource_key(date_str: str) -> str:
    return f"{JOB_TYPE_PLAN_GENERATE}:{date_str}"


def graph_refresh_resource_key(date_str: str) -> str:
    return f"{JOB_TYPE_GRAPH_REFRESH}:{date_str}"


def graph_rebuild_resource_key() -> str:
    return JOB_TYPE_GRAPH_REBUILD


def daily_pipeline_resource_key(date_str: str) -> str:
    return f"{JOB_TYPE_DAILY_PIPELINE}:{date_str}"


def day_refresh_resource_key(date_str: str, bucket: str) -> str:
    return f"{JOB_TYPE_DAY_REFRESH}:{date_str}:{bucket}"


def _dump_json(value):
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False)


def _load_json(value):
    if not value:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def serialize_job(job: Job) -> dict:
    return {
        "id": job.id,
        "job_type": job.job_type,
        "resource_key": job.resource_key,
        "status": job.status,
        "payload": _load_json(job.payload),
        "result": _load_json(job.result),
        "error": job.error,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
    }


def idle_job(job_type: str, payload: dict | None = None, resource_key: str | None = None) -> dict:
    now = datetime.utcnow().isoformat()
    return {
        "id": None,
        "job_type": job_type,
        "resource_key": resource_key,
        "status": "idle",
        "payload": payload or {},
        "result": None,
        "error": None,
        "created_at": None,
        "updated_at": now,
        "started_at": None,
        "finished_at": None,
    }


async def get_job_model(db: AsyncSession, job_id: str) -> Job | None:
    result = await db.execute(select(Job).where(Job.id == job_id))
    return result.scalar_one_or_none()


async def get_job(db: AsyncSession, job_id: str) -> dict | None:
    job = await get_job_model(db, job_id)
    return serialize_job(job) if job else None


async def list_jobs(db: AsyncSession, limit: int = 10, job_type: str | None = None) -> list[dict]:
    stmt = select(Job).order_by(Job.created_at.desc()).limit(limit)
    if job_type:
        stmt = stmt.where(Job.job_type == job_type)
    result = await db.execute(stmt)
    return [serialize_job(job) for job in result.scalars().all()]


async def get_latest_job_by_resource(
    db: AsyncSession,
    job_type: str,
    resource_key: str,
    statuses: set[str] | None = None,
) -> Job | None:
    stmt = (
        select(Job)
        .where(Job.job_type == job_type, Job.resource_key == resource_key)
        .order_by(Job.created_at.desc())
    )
    if statuses:
        stmt = stmt.where(Job.status.in_(tuple(statuses)))
    result = await db.execute(stmt.limit(1))
    return result.scalars().first()


async def enqueue_job(
    db: AsyncSession,
    job_type: str,
    payload: dict | None = None,
    resource_key: str | None = None,
    dedupe_open: bool = True,
) -> tuple[dict, bool]:
    if dedupe_open and resource_key:
        existing = await get_latest_job_by_resource(
            db,
            job_type=job_type,
            resource_key=resource_key,
            statuses=OPEN_JOB_STATUSES,
        )
        if existing:
            return serialize_job(existing), False

    job = Job(
        job_type=job_type,
        resource_key=resource_key,
        status=JOB_STATUS_PENDING,
        payload=_dump_json(payload or {}),
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return serialize_job(job), True


async def enqueue_singleton_job(
    db: AsyncSession,
    job_type: str,
    payload: dict | None = None,
    resource_key: str | None = None,
    statuses: set[str] | None = None,
) -> tuple[dict, bool]:
    """Enqueue one job per resource across concurrent local backend processes."""
    if resource_key:
        bind = db.get_bind()
        if bind and bind.dialect.name == "sqlite":
            await db.execute(text("BEGIN IMMEDIATE"))

        existing = await get_latest_job_by_resource(
            db,
            job_type=job_type,
            resource_key=resource_key,
            statuses=statuses,
        )
        if existing:
            serialized = serialize_job(existing)
            await db.rollback()
            return serialized, False

    job = Job(
        job_type=job_type,
        resource_key=resource_key,
        status=JOB_STATUS_PENDING,
        payload=_dump_json(payload or {}),
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return serialize_job(job), True


async def mark_job_running(db: AsyncSession, job: Job) -> dict:
    now = datetime.utcnow()
    job.status = JOB_STATUS_RUNNING
    job.started_at = job.started_at or now
    job.finished_at = None
    job.error = None
    await db.commit()
    await db.refresh(job)
    return serialize_job(job)


async def mark_job_completed(db: AsyncSession, job: Job, result: dict | None = None) -> dict:
    job.status = JOB_STATUS_COMPLETED
    job.result = _dump_json(result or {})
    job.error = None
    job.finished_at = datetime.utcnow()
    await db.commit()
    await db.refresh(job)
    return serialize_job(job)


async def mark_job_failed(db: AsyncSession, job: Job, error: str) -> dict:
    job.status = JOB_STATUS_FAILED
    job.error = error
    job.finished_at = datetime.utcnow()
    await db.commit()
    await db.refresh(job)
    return serialize_job(job)


async def list_incomplete_job_ids(db: AsyncSession) -> list[str]:
    result = await db.execute(
        select(Job.id)
        .where(Job.status.in_(tuple(OPEN_JOB_STATUSES)))
        .order_by(Job.created_at.asc())
    )
    return list(result.scalars().all())
