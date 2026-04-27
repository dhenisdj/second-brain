import json
from datetime import datetime, date as date_type
from collections import Counter
from urllib.parse import urlparse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import Event
from app.models.analysis import Analysis
from app.services.analysis_lookup import get_latest_analyses_by_event_ids
from app.services.browser_collector import is_browser_source
from app.services.llm_service import get_llm_service
from app.prompts.analysis import build_analysis_prompt


def _dedup_for_analysis(events: list) -> tuple[list, dict[str, list]]:
    """Deduplicate browser events by domain, keep other sources as-is.

    Returns (deduped_events, domain_to_event_ids) where deduped_events
    contains virtual Event-like objects for aggregated browser entries.
    """
    result = []
    domain_groups: dict[str, dict] = {}

    for e in events:
        if not is_browser_source(e.source):
            result.append(e)
            continue

        url = e.url or ""
        try:
            domain = urlparse(url).netloc or "other"
        except Exception:
            domain = "other"

        if domain not in domain_groups:
            domain_groups[domain] = {
                "first_ts": e.timestamp,
                "titles": set(),
                "event_ids": [],
            }
        info = domain_groups[domain]
        info["event_ids"].append(e.id)
        info["first_ts"] = min(info["first_ts"], e.timestamp)
        if e.title:
            info["titles"].add(e.title)

    class VirtualEvent:
        def __init__(self, ts, title, content, source="browser"):
            self.id = f"virtual-{title}"
            self.timestamp = ts
            self.title = title
            self.content = content
            self.source = source
            self.url = None
            self.duration_minutes = None

    for domain, info in domain_groups.items():
        count = len(info["event_ids"])
        titles = sorted(info["titles"])
        sample = ", ".join(titles[:5])
        result.append(VirtualEvent(
            ts=info["first_ts"],
            title=f"浏览 {domain}",
            content=f"{count} 次访问 | {sample}",
        ))

    result.sort(key=lambda e: e.timestamp)
    return result, {d: info["event_ids"] for d, info in domain_groups.items()}


async def run_analysis(db: AsyncSession, date_str: str) -> dict:
    target = date_type.fromisoformat(date_str)
    start = datetime.combine(target, datetime.min.time())
    end = datetime.combine(target, datetime.max.time())

    result = await db.execute(
        select(Event)
        .outerjoin(Analysis)
        .where(Event.timestamp >= start, Event.timestamp <= end, Analysis.id.is_(None))
        .order_by(Event.timestamp)
    )
    events = result.scalars().all()

    if not events:
        return {"analyzed_count": 0, "categories": {}}

    deduped, domain_event_ids = _dedup_for_analysis(events)

    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"Analysis: {len(events)} raw events -> {len(deduped)} after dedup")

    llm = get_llm_service()
    batch_size = 20
    all_analyses = []
    batch_errors = []

    for i in range(0, len(deduped), batch_size):
        batch = deduped[i : i + batch_size]
        logger.info(f"Analysis batch {i//batch_size + 1}: {len(batch)} events")
        try:
            prompt = build_analysis_prompt(batch)
            llm_result = await llm.complete_json(prompt)
            all_analyses.extend(llm_result.get("events", []))
            logger.info(f"Analysis batch {i//batch_size + 1}: got {len(llm_result.get('events', []))} results")
        except Exception as e:
            logger.error(f"Analysis batch {i//batch_size + 1} failed: {e}")
            batch_errors.append(e)
            continue

    if batch_errors and not all_analyses:
        raise batch_errors[0]

    categories = Counter()
    analyzed = 0

    real_events = {e.id: e for e in events}
    analyses_by_event_id = await get_latest_analyses_by_event_ids(db, list(real_events.keys()))

    for idx, analysis_data in enumerate(all_analyses):
        event_idx = analysis_data.get("event_index", idx)
        if event_idx >= len(deduped):
            continue

        source_item = deduped[event_idx]
        category = analysis_data["category"]
        intent = analysis_data["intent"]
        tags = json.dumps(analysis_data.get("tags", []), ensure_ascii=False)
        confidence = analysis_data.get("confidence")

        if hasattr(source_item, "id") and source_item.id.startswith("virtual-"):
            domain = source_item.title.replace("浏览 ", "")
            event_ids = domain_event_ids.get(domain, [])
            for eid in event_ids:
                if eid in real_events:
                    existing = analyses_by_event_id.get(eid)
                    if existing:
                        existing.category = category
                        existing.intent = intent
                        existing.tags = tags
                        existing.confidence = confidence
                    else:
                        existing = Analysis(
                            event_id=eid, category=category, intent=intent,
                            tags=tags, confidence=confidence,
                        )
                        db.add(existing)
                        analyses_by_event_id[eid] = existing
                    analyzed += 1
            categories[category] += len(event_ids)
        else:
            existing = analyses_by_event_id.get(source_item.id)
            if existing:
                existing.category = category
                existing.intent = intent
                existing.tags = tags
                existing.confidence = confidence
            else:
                existing = Analysis(
                    event_id=source_item.id, category=category, intent=intent,
                    tags=tags, confidence=confidence,
                )
                db.add(existing)
                analyses_by_event_id[source_item.id] = existing
            categories[category] += 1
            analyzed += 1

    await db.commit()
    return {"analyzed_count": analyzed, "categories": dict(categories)}
