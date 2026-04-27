import json
from datetime import datetime
from collections import Counter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import Event
from app.models.analysis import Analysis
from app.services.analysis_lookup import get_latest_analyses_by_event_ids
from app.services.browser_collector import BROWSER_SOURCES, is_browser_source


async def ingest_manual(db: AsyncSession, entries: list[dict]) -> int:
    count = 0
    for entry in entries:
        event = Event(
            source="manual",
            timestamp=datetime.fromisoformat(entry["timestamp"]),
            title=entry["title"],
            content=entry.get("content"),
            duration_minutes=entry.get("duration_minutes"),
            raw_data=json.dumps(entry, ensure_ascii=False),
        )
        db.add(event)
        count += 1
    await db.commit()
    return count


async def _ingest_browser_records(db: AsyncSession, records: list[dict], default_source: str = "chrome") -> dict:
    if not isinstance(records, list):
        raise ValueError("Expected a JSON array")

    count = 0
    skipped = 0
    dates = []
    seen_keys: set[tuple[str, str, str | None, str]] = set()
    for rec in records:
        ts_str = rec.get("visit_time", rec.get("timestamp", ""))
        ts = datetime.fromisoformat(ts_str)
        title = rec.get("title", "Untitled")
        url = rec.get("url")
        source = rec.get("source") or default_source
        dedup_key = (source, ts.isoformat(), url, title)
        if dedup_key in seen_keys:
            skipped += 1
            continue
        seen_keys.add(dedup_key)

        existing = await db.execute(
            select(Event.id).where(
                Event.source == source,
                Event.timestamp == ts,
                Event.url == url,
                Event.title == title,
            )
        )
        if existing.scalar_one_or_none():
            skipped += 1
            continue

        duration_sec = rec.get("visit_duration_seconds")
        event = Event(
            source=source,
            timestamp=ts,
            title=title,
            content=rec.get("content"),
            url=url,
            duration_minutes=max(1, duration_sec // 60) if duration_sec else None,
            raw_data=json.dumps({**rec, "source": source}, ensure_ascii=False),
        )
        db.add(event)
        dates.append(ts.date().isoformat())
        count += 1
    await db.commit()

    unique_dates = sorted(set(dates))
    return {
        "imported_count": count,
        "skipped_count": skipped,
        "date_range": [unique_dates[0], unique_dates[-1]] if unique_dates else [],
    }


async def ingest_chrome(db: AsyncSession, file_content: bytes) -> dict:
    try:
        records = json.loads(file_content)
    except json.JSONDecodeError:
        raise ValueError("Invalid JSON file")

    return await _ingest_browser_records(db, records, default_source="chrome")


async def ingest_browser_events(db: AsyncSession, events: list[dict]) -> dict:
    return await _ingest_browser_records(db, events)


async def ingest_gcal(db: AsyncSession, events: list[dict]) -> int:
    count = 0
    for ev in events:
        ts = datetime.fromisoformat(ev["timestamp"])
        existing = await db.execute(
            select(Event).where(
                Event.source == "gcal",
                Event.timestamp == ts,
                Event.title == ev["title"],
            )
        )
        existing_event = existing.scalar_one_or_none()
        if existing_event:
            existing_event.content = ev.get("content")
            existing_event.duration_minutes = ev.get("duration_minutes")
            existing_event.raw_data = json.dumps(ev, ensure_ascii=False)
            continue

        event = Event(
            source="gcal",
            timestamp=ts,
            title=ev["title"],
            content=ev.get("content"),
            duration_minutes=ev.get("duration_minutes"),
            raw_data=json.dumps(ev, ensure_ascii=False),
        )
        db.add(event)
        count += 1
    await db.commit()
    return count


async def ingest_git(db: AsyncSession, events: list[dict]) -> dict:
    count = 0
    skipped = 0
    dates = []
    for ev in events:
        ts = datetime.fromisoformat(ev["timestamp"])
        url = ev.get("url")
        content = ev.get("content")

        filters = [
            Event.source == "git",
            Event.timestamp == ts,
            Event.title == ev["title"],
        ]
        if url:
            filters.append(Event.url == url)
        else:
            filters.append(Event.content == content)

        existing = await db.execute(select(Event).where(*filters))
        existing_event = existing.scalar_one_or_none()
        raw_data = json.dumps(ev, ensure_ascii=False)
        if existing_event:
            existing_event.content = content
            existing_event.url = url
            existing_event.raw_data = raw_data
            skipped += 1
            continue

        event = Event(
            source="git",
            timestamp=ts,
            title=ev["title"],
            content=content,
            url=url,
            raw_data=raw_data,
        )
        db.add(event)
        dates.append(ts.date().isoformat())
        count += 1
    await db.commit()

    unique_dates = sorted(set(dates))
    return {
        "imported_count": count,
        "skipped_count": skipped,
        "date_range": [unique_dates[0], unique_dates[-1]] if unique_dates else [],
    }


def _event_to_dict(e, analysis: Analysis | None = None) -> dict:
    item = {
        "id": e.id,
        "source": e.source,
        "timestamp": e.timestamp.isoformat(),
        "title": e.title,
        "content": e.content,
        "url": e.url,
        "duration_minutes": e.duration_minutes,
    }
    if analysis:
        item["analysis"] = {
            "category": analysis.category,
            "intent": analysis.intent,
            "tags": json.loads(analysis.tags) if analysis.tags else [],
        }
    else:
        item["analysis"] = None
    return item


def _extract_domain(url: str) -> str:
    from urllib.parse import urlparse
    try:
        parsed = urlparse(url)
        return parsed.netloc or "other"
    except Exception:
        return "other"


def _compact_text(text: str | None, limit: int = 120) -> str:
    cleaned = " ".join((text or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: max(0, limit - 3)].rstrip() + "..."


def _aggregate_browser_events(events: list[Event], analyses_by_event_id: dict[str, Analysis]) -> list[dict]:
    """Aggregate browser events by domain, keep other sources as-is."""
    result = []
    browser_domains: dict[str, dict] = {}

    for e in events:
        if not is_browser_source(e.source):
            result.append(_event_to_dict(e, analyses_by_event_id.get(e.id)))
            continue

        domain = _extract_domain(e.url) if e.url else "other"
        if domain not in browser_domains:
            browser_domains[domain] = {
                "first_ts": e.timestamp,
                "last_ts": e.timestamp,
                "titles": set(),
                "count": 0,
                "sources": Counter(),
                "contents": [],
            }
        info = browser_domains[domain]
        info["count"] += 1
        info["first_ts"] = min(info["first_ts"], e.timestamp)
        info["last_ts"] = max(info["last_ts"], e.timestamp)
        info["sources"][e.source] += 1
        if e.title:
            info["titles"].add(e.title)
        compact_content = _compact_text(e.content, 120)
        if compact_content and compact_content not in info["contents"]:
            info["contents"].append(compact_content)

    for domain, info in browser_domains.items():
        titles = sorted(info["titles"])
        sample = ", ".join(titles[:5])
        if len(titles) > 5:
            sample += f" 等 {len(titles)} 个页面"

        first = info["first_ts"].strftime("%H:%M")
        last = info["last_ts"].strftime("%H:%M")
        time_range = f"{first}~{last}" if first != last else first
        source_breakdown = ", ".join(f"{src.capitalize()} {count} 次" for src, count in sorted(info["sources"].items()))
        content = f"{info['count']} 次访问 ({time_range})"
        if source_breakdown:
            content += f" | {source_breakdown}"
        if sample:
            content += f" | {sample}"
        if info["contents"]:
            content += f" | 线索：{'；'.join(info['contents'][:3])}"

        result.append({
            "id": f"agg-browser-{domain}",
            "source": "browser",
            "timestamp": info["first_ts"].isoformat(),
            "title": domain,
            "content": content,
            "url": None,
            "duration_minutes": None,
            "analysis": None,
            "visit_count": info["count"],
        })

    result.sort(key=lambda x: x["timestamp"])
    return result


async def get_events_by_date(
    db: AsyncSession,
    date_str: str,
    page: int = 1,
    size: int = 50,
    source: str | None = None,
    aggregate_browser: bool = True,
) -> dict:
    from datetime import date as date_type
    target = date_type.fromisoformat(date_str)
    start = datetime.combine(target, datetime.min.time())
    end = datetime.combine(target, datetime.max.time())

    filters = [Event.timestamp >= start, Event.timestamp <= end]
    if source:
        if source == "browser":
            filters.append(Event.source.in_(BROWSER_SOURCES))
        else:
            filters.append(Event.source == source)

    all_query = (
        select(Event)
        .where(*filters)
        .order_by(Event.timestamp)
    )
    result = await db.execute(all_query)
    all_events = result.scalars().all()
    analyses_by_event_id = await get_latest_analyses_by_event_ids(
        db,
        [event.id for event in all_events],
    )

    if source or not aggregate_browser:
        items = [_event_to_dict(e, analyses_by_event_id.get(e.id)) for e in all_events]
    else:
        items = _aggregate_browser_events(all_events, analyses_by_event_id)

    total = len(items)
    offset = (page - 1) * size
    page_items = items[offset:offset + size]

    return {"items": page_items, "total": total, "page": page}
