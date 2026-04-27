from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analysis import Analysis


async def get_latest_analyses_by_event_ids(
    db: AsyncSession,
    event_ids: list[str],
) -> dict[str, Analysis]:
    if not event_ids:
        return {}

    result = await db.execute(
        select(Analysis)
        .where(Analysis.event_id.in_(event_ids))
        .order_by(Analysis.event_id, Analysis.created_at.desc(), Analysis.id.desc())
    )

    latest: dict[str, Analysis] = {}
    for analysis in result.scalars().all():
        latest.setdefault(analysis.event_id, analysis)
    return latest
