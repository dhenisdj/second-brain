from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services import summary_service
from app.services.job_executor import schedule_job
from app.services import job_service
from app.services.llm_service import LLMTimeoutError

router = APIRouter(prefix="/api", tags=["summary"])


class SummaryRequest(BaseModel):
    date: str


@router.post("/summary/generate")
async def generate_summary(req: SummaryRequest, db: AsyncSession = Depends(get_db)):
    try:
        result = await summary_service.generate_summary(db, req.date)
    except LLMTimeoutError:
        raise HTTPException(
            status_code=504,
            detail="LLM 响应超时，请稍后重试，或减少当天数据量 / 切换更快模型后再生成总结。",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return result


@router.post("/summary/generate-async", status_code=202)
async def generate_summary_async(req: SummaryRequest, db: AsyncSession = Depends(get_db)):
    job, created = await job_service.enqueue_job(
        db,
        job_type=job_service.JOB_TYPE_SUMMARY_GENERATE,
        payload={"date": req.date},
        resource_key=job_service.summary_resource_key(req.date),
    )
    if created:
        schedule_job(job["id"])
    return job


@router.get("/summary/{date}")
async def get_summary(date: str, db: AsyncSession = Depends(get_db)):
    result = await summary_service.get_summary(db, date)
    if not result:
        raise HTTPException(status_code=404, detail="Summary not found")
    return result


@router.get("/summary/status/{date}")
async def get_summary_status(date: str, db: AsyncSession = Depends(get_db)):
    job = await job_service.get_latest_job_by_resource(
        db,
        job_type=job_service.JOB_TYPE_SUMMARY_GENERATE,
        resource_key=job_service.summary_resource_key(date),
    )
    if not job:
        return job_service.idle_job(
            job_type=job_service.JOB_TYPE_SUMMARY_GENERATE,
            payload={"date": date},
            resource_key=job_service.summary_resource_key(date),
        )
    return job_service.serialize_job(job)
