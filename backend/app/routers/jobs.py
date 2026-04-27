from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services import job_service

router = APIRouter(prefix="/api", tags=["jobs"])


@router.get("/jobs")
async def get_jobs(
    limit: int = Query(10, ge=1, le=50),
    job_type: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    return {"items": await job_service.list_jobs(db, limit=limit, job_type=job_type)}


@router.get("/jobs/{job_id}")
async def get_job(job_id: str, db: AsyncSession = Depends(get_db)):
    job = await job_service.get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job
