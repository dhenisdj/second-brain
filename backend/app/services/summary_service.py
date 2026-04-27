import json
import logging
from datetime import datetime, date as date_type
from collections import Counter
from urllib.parse import urlparse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import Event
from app.models.summary import DailySummary
from app.services.analysis_lookup import get_latest_analyses_by_event_ids
from app.services.browser_collector import is_browser_source
from app.services.graph_service import extract_and_merge_graph  # noqa: F401
from app.services.llm_service import get_llm_service
from app.prompts.summary import build_summary_prompt

logger = logging.getLogger(__name__)


def _parse_tags(raw_tags: str | None) -> list[str]:
    if not raw_tags:
        return []
    try:
        parsed = json.loads(raw_tags)
        return parsed if isinstance(parsed, list) else []
    except Exception:
        return []


def _truncate_text(text: str | None, limit: int) -> str:
    cleaned = " ".join((text or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: max(0, limit - 3)].rstrip() + "..."


def _extract_domain(url: str | None) -> str:
    if not url:
        return "other"
    try:
        return urlparse(url).netloc or "other"
    except Exception:
        return "other"


def _counter_top_value(counter: Counter[str], fallback: str) -> str:
    if not counter:
        return fallback
    return counter.most_common(1)[0][0]


def _build_event_detail_payloads(events: list[Event], analyses_by_event_id: dict) -> list[dict]:
    payloads = []
    for event in events:
        analysis = analyses_by_event_id.get(event.id)
        if not analysis:
            continue
        payloads.append(
            {
                "id": event.id,
                "timestamp": event.timestamp.isoformat(),
                "title": _truncate_text(event.title, 120),
                "content": _truncate_text(event.content, 240),
                "category": analysis.category,
                "intent": _truncate_text(analysis.intent, 80),
                "tags": _parse_tags(analysis.tags)[:8],
                "duration_minutes": event.duration_minutes,
            }
        )
    return payloads


def _build_summary_prompt_events(events: list[Event], analyses_by_event_id: dict) -> list[dict]:
    items: list[dict] = []
    browser_groups: dict[str, dict] = {}

    for event in events:
        analysis = analyses_by_event_id.get(event.id)
        if not analysis:
            continue

        if not is_browser_source(event.source):
            items.append(
                {
                    "id": event.id,
                    "timestamp": event.timestamp.isoformat(),
                    "title": _truncate_text(event.title, 100),
                    "content": _truncate_text(event.content, 180),
                    "category": analysis.category,
                    "intent": _truncate_text(analysis.intent, 60),
                    "tags": _parse_tags(analysis.tags)[:6],
                    "duration_minutes": event.duration_minutes,
                }
            )
            continue

        domain = _extract_domain(event.url)
        info = browser_groups.setdefault(
            domain,
            {
                "first_ts": event.timestamp,
                "last_ts": event.timestamp,
                "titles": [],
                "count": 0,
                "duration_minutes": 0,
                "categories": Counter(),
                "intents": Counter(),
                "tags": set(),
                "sources": Counter(),
                "contents": [],
            },
        )
        info["first_ts"] = min(info["first_ts"], event.timestamp)
        info["last_ts"] = max(info["last_ts"], event.timestamp)
        info["count"] += 1
        info["duration_minutes"] += event.duration_minutes or 0
        info["sources"][event.source] += 1
        if event.title:
            info["titles"].append(_truncate_text(event.title, 60))
        compact_content = _truncate_text(event.content, 90)
        if compact_content and compact_content not in info["contents"]:
            info["contents"].append(compact_content)
        info["categories"][analysis.category] += 1
        if analysis.intent:
            info["intents"][_truncate_text(analysis.intent, 40)] += 1
        for tag in _parse_tags(analysis.tags)[:6]:
            info["tags"].add(tag)

    for domain, info in browser_groups.items():
        titles = []
        for title in info["titles"]:
            if title not in titles:
                titles.append(title)
        sample = ", ".join(titles[:4])
        if len(titles) > 4:
            sample += f" 等 {len(titles)} 个页面"

        first = info["first_ts"].strftime("%H:%M")
        last = info["last_ts"].strftime("%H:%M")
        time_range = f"{first}~{last}" if first != last else first
        content = f"{info['count']} 次访问 ({time_range})"
        source_breakdown = ", ".join(f"{src.capitalize()} {count} 次" for src, count in sorted(info["sources"].items()))
        if source_breakdown:
            content += f" | {source_breakdown}"
        if sample:
            content += f" | {sample}"
        if info["contents"]:
            content += f" | 线索：{'；'.join(info['contents'][:2])}"

        items.append(
            {
                "id": f"browser-{domain}",
                "timestamp": info["first_ts"].isoformat(),
                "title": f"浏览 {domain}",
                "content": _truncate_text(content, 240),
                "category": _counter_top_value(info["categories"], "work"),
                "intent": _counter_top_value(info["intents"], "浏览资料"),
                "tags": sorted(info["tags"])[:6],
                "duration_minutes": info["duration_minutes"] or None,
            }
        )

    items.sort(key=lambda item: item["timestamp"])
    return items


async def generate_summary(db: AsyncSession, date_str: str) -> dict:
    target = date_type.fromisoformat(date_str)
    start = datetime.combine(target, datetime.min.time())
    end = datetime.combine(target, datetime.max.time())

    result = await db.execute(
        select(Event)
        .where(Event.timestamp >= start, Event.timestamp <= end)
        .order_by(Event.timestamp)
    )
    events = result.scalars().all()
    analyses_by_event_id = await get_latest_analyses_by_event_ids(
        db,
        [event.id for event in events],
    )

    if not analyses_by_event_id:
        raise ValueError("No analyzed events found for this date. Run analysis first.")

    summary_events = _build_summary_prompt_events(events, analyses_by_event_id)
    events_data = _build_event_detail_payloads(events, analyses_by_event_id)
    logger.info(
        "Summary generation: %s analyzed events compressed to %s prompt items for %s",
        len(events_data),
        len(summary_events),
        target.isoformat(),
    )

    llm = get_llm_service()
    prompt = build_summary_prompt(summary_events)
    llm_result = await llm.complete_json(prompt)

    existing = await db.execute(select(DailySummary).where(DailySummary.date == target))
    summary = existing.scalar_one_or_none()

    time_dist = llm_result.get("time_distribution", {})

    if summary:
        summary.timeline_md = llm_result.get("timeline_md", "")
        summary.progress_md = llm_result.get("progress_md", "")
        summary.knowledge_md = llm_result.get("knowledge_md", "")
        summary.time_distribution = json.dumps(time_dist, ensure_ascii=False)
        summary.raw_llm_response = json.dumps(llm_result, ensure_ascii=False)
    else:
        summary = DailySummary(
            date=target,
            timeline_md=llm_result.get("timeline_md", ""),
            progress_md=llm_result.get("progress_md", ""),
            knowledge_md=llm_result.get("knowledge_md", ""),
            time_distribution=json.dumps(time_dist, ensure_ascii=False),
            raw_llm_response=json.dumps(llm_result, ensure_ascii=False),
        )
        db.add(summary)

    await db.commit()
    await db.refresh(summary)

    return {
        "id": summary.id,
        "date": target.isoformat(),
        "timeline_md": summary.timeline_md,
        "progress_md": summary.progress_md,
        "knowledge_md": summary.knowledge_md,
        "time_distribution": time_dist,
    }


async def get_summary(db: AsyncSession, date_str: str) -> dict | None:
    target = date_type.fromisoformat(date_str)
    result = await db.execute(select(DailySummary).where(DailySummary.date == target))
    summary = result.scalar_one_or_none()
    if not summary:
        return None
    return {
        "id": summary.id,
        "date": target.isoformat(),
        "timeline_md": summary.timeline_md,
        "progress_md": summary.progress_md,
        "knowledge_md": summary.knowledge_md,
        "time_distribution": json.loads(summary.time_distribution) if summary.time_distribution else {},
    }
