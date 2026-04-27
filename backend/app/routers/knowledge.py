from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services import graph_service
from app.services import job_service
from app.services.job_executor import schedule_job

router = APIRouter(prefix="/api", tags=["knowledge"])


@router.get("/knowledge/graph")
async def get_graph(
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    return await graph_service.get_graph(db, limit)


@router.get("/knowledge/node/{node_id}")
async def get_node_detail(node_id: str, db: AsyncSession = Depends(get_db)):
    result = await graph_service.get_node_detail(db, node_id)
    if not result:
        raise HTTPException(status_code=404, detail="Node not found")
    return result


@router.post("/knowledge/rebuild")
async def rebuild_graph(db: AsyncSession = Depends(get_db)):
    return await graph_service.rebuild_graph(db)


@router.post("/knowledge/rebuild-async", status_code=202)
async def rebuild_graph_async(db: AsyncSession = Depends(get_db)):
    job, created = await job_service.enqueue_job(
        db,
        job_type=job_service.JOB_TYPE_GRAPH_REBUILD,
        payload={},
        resource_key=job_service.graph_rebuild_resource_key(),
    )
    if created:
        schedule_job(job["id"])
    return job
