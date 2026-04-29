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

SUMMARY_TOPIC_LIMIT = 18
SUMMARY_TOPIC_EVIDENCE_LIMIT = 4
SUMMARY_TIMELINE_BLOCK_LIMIT = 18
SUMMARY_TIMELINE_SAMPLE_LIMIT = 5
SUMMARY_SOURCE_SAMPLE_LIMIT = 6


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


def _safe_parse_timestamp(raw_ts: str) -> datetime | None:
    try:
        return datetime.fromisoformat(raw_ts)
    except Exception:
        return None


def _format_item_time(raw_ts: str) -> str:
    parsed = _safe_parse_timestamp(raw_ts)
    return parsed.strftime("%H:%M") if parsed else raw_ts[:16]


def _format_time_range(timestamps: list[str]) -> str:
    parsed = sorted(ts for ts in (_safe_parse_timestamp(ts) for ts in timestamps) if ts)
    if not parsed:
        return ""
    first = parsed[0].strftime("%H:%M")
    last = parsed[-1].strftime("%H:%M")
    return first if first == last else f"{first}~{last}"


def _estimate_minutes(item: dict) -> int:
    duration = item.get("duration_minutes")
    if isinstance(duration, (int, float)) and duration > 0:
        return int(duration)
    return 5


def _normalize_topic_part(value: str | None) -> str:
    return " ".join((value or "").lower().split())[:80]


def _topic_key(item: dict) -> tuple[str, str]:
    item_id = str(item.get("id") or "")
    if item_id.startswith("browser-"):
        return ("browser", item.get("title") or item_id)

    tags = [str(tag).strip() for tag in item.get("tags") or [] if str(tag).strip()]
    if tags:
        return (str(item.get("source") or "event"), tags[0])

    intent = _normalize_topic_part(item.get("intent"))
    if intent:
        return (str(item.get("source") or "event"), intent)

    return (str(item.get("source") or "event"), _normalize_topic_part(item.get("title")) or "未分类")


def _unique_append(values: list[str], value: str, limit: int) -> None:
    if value and value not in values and len(values) < limit:
        values.append(value)


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
                    "source": event.source,
                    "timestamp": event.timestamp.isoformat(),
                    "title": _truncate_text(event.title, 100),
                    "content": _truncate_text(event.content, 180),
                    "url": event.url,
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
                "source": "browser",
                "timestamp": info["first_ts"].isoformat(),
                "title": f"浏览 {domain}",
                "content": _truncate_text(content, 240),
                "url": domain,
                "category": _counter_top_value(info["categories"], "work"),
                "intent": _counter_top_value(info["intents"], "浏览资料"),
                "tags": sorted(info["tags"])[:6],
                "duration_minutes": info["duration_minutes"] or None,
            }
        )

    items.sort(key=lambda item: item["timestamp"])
    return items


def _build_summary_digest(summary_events: list[dict], raw_event_count: int) -> dict:
    source_groups: dict[str, dict] = {}
    topic_groups: dict[tuple[str, str], dict] = {}
    timeline_groups: dict[str, dict] = {}
    category_minutes: Counter[str] = Counter()

    for item in summary_events:
        source = str(item.get("source") or "unknown")
        category = str(item.get("category") or "work")
        minutes = _estimate_minutes(item)
        title = _truncate_text(item.get("title"), 90)
        content = _truncate_text(item.get("content"), 150)
        intent = _truncate_text(item.get("intent"), 70)
        tags = [str(tag) for tag in item.get("tags") or []][:6]
        timestamp = str(item.get("timestamp") or "")

        category_minutes[category] += minutes

        source_info = source_groups.setdefault(
            source,
            {
                "source": source,
                "count": 0,
                "estimated_minutes": 0,
                "categories": Counter(),
                "top_titles": [],
                "top_intents": [],
                "top_tags": Counter(),
            },
        )
        source_info["count"] += 1
        source_info["estimated_minutes"] += minutes
        source_info["categories"][category] += 1
        _unique_append(source_info["top_titles"], title, SUMMARY_SOURCE_SAMPLE_LIMIT)
        _unique_append(source_info["top_intents"], intent, SUMMARY_SOURCE_SAMPLE_LIMIT)
        source_info["top_tags"].update(tags)

        topic_key = _topic_key(item)
        topic_info = topic_groups.setdefault(
            topic_key,
            {
                "topic": topic_key[1],
                "source": source,
                "count": 0,
                "estimated_minutes": 0,
                "time_range": "",
                "timestamps": [],
                "categories": Counter(),
                "intents": Counter(),
                "tags": Counter(),
                "evidence": [],
            },
        )
        topic_info["count"] += 1
        topic_info["estimated_minutes"] += minutes
        topic_info["timestamps"].append(timestamp)
        topic_info["categories"][category] += 1
        if intent:
            topic_info["intents"][intent] += 1
        topic_info["tags"].update(tags)
        if len(topic_info["evidence"]) < SUMMARY_TOPIC_EVIDENCE_LIMIT:
            topic_info["evidence"].append(
                {
                    "time": _format_item_time(timestamp),
                    "title": title,
                    "content": content,
                    "intent": intent,
                }
            )

        parsed_ts = _safe_parse_timestamp(timestamp)
        block_key = parsed_ts.strftime("%H:00") if parsed_ts else timestamp[:13]
        timeline_info = timeline_groups.setdefault(
            block_key,
            {
                "time": block_key,
                "count": 0,
                "estimated_minutes": 0,
                "sources": Counter(),
                "categories": Counter(),
                "items": [],
            },
        )
        timeline_info["count"] += 1
        timeline_info["estimated_minutes"] += minutes
        timeline_info["sources"][source] += 1
        timeline_info["categories"][category] += 1
        if len(timeline_info["items"]) < SUMMARY_TIMELINE_SAMPLE_LIMIT:
            timeline_info["items"].append(
                {
                    "title": title,
                    "intent": intent,
                    "source": source,
                }
            )

    total_minutes = sum(category_minutes.values()) or 1
    category_distribution_estimate = {
        category: round(minutes * 100 / total_minutes)
        for category, minutes in category_minutes.items()
    }

    source_summaries = []
    for info in source_groups.values():
        source_summaries.append(
            {
                "source": info["source"],
                "count": info["count"],
                "estimated_minutes": info["estimated_minutes"],
                "primary_category": _counter_top_value(info["categories"], "work"),
                "top_titles": info["top_titles"],
                "top_intents": info["top_intents"],
                "top_tags": [tag for tag, _ in info["top_tags"].most_common(8)],
            }
        )

    main_topics = []
    ranked_topics = sorted(
        topic_groups.values(),
        key=lambda info: (info["estimated_minutes"], info["count"]),
        reverse=True,
    )
    for info in ranked_topics[:SUMMARY_TOPIC_LIMIT]:
        main_topics.append(
            {
                "topic": info["topic"],
                "source": info["source"],
                "count": info["count"],
                "estimated_minutes": info["estimated_minutes"],
                "time_range": _format_time_range(info["timestamps"]),
                "primary_category": _counter_top_value(info["categories"], "work"),
                "primary_intent": _counter_top_value(info["intents"], ""),
                "top_tags": [tag for tag, _ in info["tags"].most_common(8)],
                "evidence": info["evidence"],
            }
        )

    timeline_blocks = []
    for key in sorted(timeline_groups):
        info = timeline_groups[key]
        timeline_blocks.append(
            {
                "time": info["time"],
                "count": info["count"],
                "estimated_minutes": info["estimated_minutes"],
                "primary_source": _counter_top_value(info["sources"], "unknown"),
                "primary_category": _counter_top_value(info["categories"], "work"),
                "items": info["items"],
            }
        )

    return {
        "raw_event_count": raw_event_count,
        "prompt_item_count_after_source_compression": len(summary_events),
        "content_extractor": {
            "strategy": "rule_based_source_topic_digest",
            "topic_limit": SUMMARY_TOPIC_LIMIT,
            "evidence_per_topic_limit": SUMMARY_TOPIC_EVIDENCE_LIMIT,
        },
        "category_distribution_estimate": category_distribution_estimate,
        "source_summaries": sorted(source_summaries, key=lambda item: item["count"], reverse=True),
        "timeline_blocks": timeline_blocks[:SUMMARY_TIMELINE_BLOCK_LIMIT],
        "main_topics": main_topics,
    }


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
    summary_digest = _build_summary_digest(summary_events, len(events_data))
    logger.info(
        "Summary generation: %s analyzed events compressed to %s prompt items and %s digest topics for %s",
        len(events_data),
        len(summary_events),
        len(summary_digest["main_topics"]),
        target.isoformat(),
    )

    llm = get_llm_service()
    prompt = build_summary_prompt(summary_digest)
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
