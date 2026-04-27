from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services import plan_service
from app.services import job_service
from app.services.job_executor import schedule_job

router = APIRouter(prefix="/api", tags=["plan"])


class PlanGenerateRequest(BaseModel):
    date: str


class PlanUpdateRequest(BaseModel):
    items: list[dict]


@router.post("/plan/generate")
async def generate_plan(req: PlanGenerateRequest, db: AsyncSession = Depends(get_db)):
    try:
        result = await plan_service.generate_plan(db, req.date)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return result


@router.post("/plan/generate-async", status_code=202)
async def generate_plan_async(req: PlanGenerateRequest, db: AsyncSession = Depends(get_db)):
    job, created = await job_service.enqueue_job(
        db,
        job_type=job_service.JOB_TYPE_PLAN_GENERATE,
        payload={"date": req.date},
        resource_key=job_service.plan_resource_key(req.date),
    )
    if created:
        schedule_job(job["id"])
    return job


@router.get("/plan/by-summary/{date}")
async def get_plan_by_summary(date: str, db: AsyncSession = Depends(get_db)):
    result = await plan_service.get_plan_by_summary_date(db, date)
    if not result:
        raise HTTPException(status_code=404, detail="Plan not found")
    return result


@router.put("/plan/{plan_id}")
async def update_plan(plan_id: str, req: PlanUpdateRequest, db: AsyncSession = Depends(get_db)):
    result = await plan_service.update_plan(db, plan_id, req.items)
    if not result:
        raise HTTPException(status_code=404, detail="Plan not found")
    return result
