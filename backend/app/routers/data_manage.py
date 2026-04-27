from datetime import datetime, date as date_type
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, delete, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.event import Event
from app.models.analysis import Analysis
from app.models.summary import DailySummary
from app.models.knowledge import KGNode, KGEvidence
from app.models.plan import Plan
from app.services import graph_service

router = APIRouter(prefix="/api", tags=["data_manage"])


@router.get("/data/overview")
async def data_overview(
    start: str = Query(...),
    end: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    start_date = date_type.fromisoformat(start)
    end_date = date_type.fromisoformat(end)
    start_dt = datetime.combine(start_date, datetime.min.time())
    end_dt = datetime.combine(end_date, datetime.max.time())

    result = await db.execute(
        select(
            func.date(Event.timestamp).label("date"),
            func.count(Event.id).label("count"),
        )
        .where(Event.timestamp >= start_dt, Event.timestamp <= end_dt)
        .group_by(func.date(Event.timestamp))
    )
    rows = result.all()

    summary_result = await db.execute(
        select(DailySummary.date).where(
            DailySummary.date >= start_date,
            DailySummary.date <= end_date,
        )
    )
    summary_dates = {str(r) for r in summary_result.scalars().all()}

    analysis_dates = set()
    for row in rows:
        d = str(row.date)
        a_result = await db.execute(
            select(func.count(Analysis.id))
            .join(Event)
            .where(
                func.date(Event.timestamp) == row.date,
            )
        )
        if a_result.scalar() > 0:
            analysis_dates.add(d)

    days = []
    for row in rows:
        d = str(row.date)
        days.append({
            "date": d,
            "event_count": row.count,
            "has_analysis": d in analysis_dates,
            "has_summary": d in summary_dates,
        })

    return {"days": days}


@router.delete("/data/events/{event_id}")
async def delete_event(event_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Event).where(Event.id == event_id))
    event = result.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    analyses_deleted = (
        await db.execute(delete(Analysis).where(Analysis.event_id == event_id))
    ).rowcount or 0
    await db.execute(delete(KGEvidence).where(KGEvidence.event_id == event_id))
    await db.delete(event)
    await db.commit()
    return {"deleted": True, "analyses": analyses_deleted}


@router.delete("/data/day/{date}")
async def delete_day(date: str, db: AsyncSession = Depends(get_db)):
    target = date_type.fromisoformat(date)
    start = datetime.combine(target, datetime.min.time())
    end = datetime.combine(target, datetime.max.time())

    events_result = await db.execute(
        select(Event).where(Event.timestamp >= start, Event.timestamp <= end)
    )
    events = events_result.scalars().all()
    event_ids = [e.id for e in events]

    summary_result = await db.execute(
        select(DailySummary.id).where(DailySummary.date == target)
    )
    summary_ids = summary_result.scalars().all()

    graph_cleanup = {"evidences_deleted": 0, "edges_deleted": 0, "nodes_deleted": 0}
    if summary_ids:
        graph_cleanup = await graph_service.remove_summary_graph(db, summary_ids)

    analyses_deleted = 0
    if event_ids:
        a_result = await db.execute(
            delete(Analysis).where(Analysis.event_id.in_(event_ids))
        )
        analyses_deleted = a_result.rowcount

    events_deleted = 0
    if event_ids:
        e_result = await db.execute(
            delete(Event).where(Event.id.in_(event_ids))
        )
        events_deleted = e_result.rowcount

    summaries_deleted = 0
    s_result = await db.execute(delete(DailySummary).where(DailySummary.date == target))
    summaries_deleted = s_result.rowcount

    plans_deleted = 0
    if summary_ids:
        p_result = await db.execute(
            delete(Plan).where(or_(Plan.date == target, Plan.summary_id.in_(summary_ids)))
        )
    else:
        p_result = await db.execute(delete(Plan).where(Plan.date == target))
    plans_deleted = p_result.rowcount

    await db.commit()

    return {
        "deleted": {
            "events": events_deleted,
            "analyses": analyses_deleted,
            "summaries": summaries_deleted,
            "graph_evidences": graph_cleanup["evidences_deleted"],
            "graph_edges": graph_cleanup["edges_deleted"],
            "graph_nodes": graph_cleanup["nodes_deleted"],
            "plans": plans_deleted,
        }
    }
