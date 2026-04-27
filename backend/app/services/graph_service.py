import json
import logging
from datetime import date as date_type, datetime
from collections import Counter
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import KGNode, KGEdge, KGEvidence
from app.models.event import Event
from app.models.summary import DailySummary
from app.services.analysis_lookup import get_latest_analyses_by_event_ids
from app.services.llm_service import get_llm_service
from app.prompts.summary import build_graph_extraction_prompt

logger = logging.getLogger(__name__)


def _parse_tags(raw_tags: str | None) -> list[str]:
    if not raw_tags:
        return []
    try:
        parsed = json.loads(raw_tags)
        return parsed if isinstance(parsed, list) else []
    except Exception:
        return []


def _summary_to_dict(summary: DailySummary) -> dict:
    if summary.raw_llm_response:
        try:
            parsed = json.loads(summary.raw_llm_response)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            logger.warning("Failed to parse raw summary response for %s", summary.date)

    return {
        "timeline_md": summary.timeline_md or "",
        "progress_md": summary.progress_md or "",
        "knowledge_md": summary.knowledge_md or "",
        "time_distribution": json.loads(summary.time_distribution) if summary.time_distribution else {},
    }


async def _build_events_data_for_summary(db: AsyncSession, target_date: date_type) -> list[dict]:
    start = datetime.combine(target_date, datetime.min.time())
    end = datetime.combine(target_date, datetime.max.time())

    events = (
        await db.execute(
            select(Event)
            .where(Event.timestamp >= start, Event.timestamp <= end)
            .order_by(Event.timestamp)
        )
    ).scalars().all()
    analyses_by_event_id = await get_latest_analyses_by_event_ids(
        db,
        [event.id for event in events],
    )

    items: list[dict] = []
    for event in events:
        analysis = analyses_by_event_id.get(event.id)
        if not analysis:
            continue
        items.append(
            {
                "id": event.id,
                "timestamp": event.timestamp.isoformat(),
                "title": event.title,
                "content": event.content or "",
                "category": analysis.category,
                "intent": analysis.intent,
                "tags": _parse_tags(analysis.tags),
                "duration_minutes": event.duration_minutes,
            }
        )
    return items


def _find_summary_excerpt(node_name: str, summary_data: dict) -> str | None:
    node_lower = node_name.lower()
    for field in ("progress_md", "knowledge_md", "timeline_md"):
        text = (summary_data.get(field) or "").strip()
        if not text:
            continue
        for raw_line in text.splitlines():
            line = raw_line.strip().lstrip("-").strip()
            if line and node_lower in line.lower():
                return line[:240]

    for field in ("progress_md", "knowledge_md", "timeline_md"):
        text = (summary_data.get(field) or "").strip()
        if text:
            return text.splitlines()[0].strip()[:240]
    return None


def _find_event_matches(node_name: str, events_data: list[dict] | None, limit: int = 3) -> list[dict]:
    if not events_data:
        return []

    node_lower = node_name.lower()
    matches = []
    for event in events_data:
        tags = " ".join(event.get("tags") or [])
        haystack = " ".join(
            [
                event.get("title", ""),
                event.get("content", ""),
                event.get("intent", ""),
                tags,
            ]
        ).lower()
        if node_lower not in haystack:
            continue

        parts = []
        if event.get("intent"):
            parts.append(event["intent"])
        if event.get("content"):
            parts.append(event["content"])
        elif event.get("tags"):
            parts.append("标签: " + ", ".join(event["tags"]))

        matches.append(
            {
                "event_id": event.get("id"),
                "title": event.get("title", "活动记录"),
                "excerpt": " | ".join(p for p in parts if p).strip()[:240] or event.get("title", "活动记录"),
            }
        )
        if len(matches) >= limit:
            break
    return matches


def _load_edge_context(raw_context: str | None) -> dict:
    if not raw_context:
        return {"summary_ids": [], "note": None}
    try:
        parsed = json.loads(raw_context)
        if isinstance(parsed, dict):
            return {
                "summary_ids": parsed.get("summary_ids", []),
                "note": parsed.get("note"),
            }
    except Exception:
        pass
    return {"summary_ids": [], "note": raw_context}


def _dump_edge_context(summary_ids: list[str], note: str | None) -> str:
    return json.dumps(
        {"summary_ids": sorted(set(summary_ids)), "note": note},
        ensure_ascii=False,
    )


async def remove_summary_graph(db: AsyncSession, summary_ids: list[str]) -> dict:
    unique_summary_ids = sorted(set(summary_ids))
    if not unique_summary_ids:
        return {
            "evidences_deleted": 0,
            "edges_deleted": 0,
            "edges_updated": 0,
            "nodes_deleted": 0,
            "nodes_updated": 0,
        }

    impacted_pairs = (
        await db.execute(
            select(KGEvidence.node_id, KGEvidence.summary_id)
            .where(KGEvidence.summary_id.in_(unique_summary_ids))
            .distinct()
        )
    ).all()
    node_decrements = Counter(node_id for node_id, _summary_id in impacted_pairs)
    impacted_node_ids = sorted(node_decrements)

    evidence_result = await db.execute(
        delete(KGEvidence).where(KGEvidence.summary_id.in_(unique_summary_ids))
    )

    edges_result = await db.execute(select(KGEdge))
    edges_deleted = 0
    edges_updated = 0
    summary_id_set = set(unique_summary_ids)
    for edge in edges_result.scalars().all():
        edge_context = _load_edge_context(edge.context)
        remaining_summary_ids = [
            summary_id
            for summary_id in edge_context.get("summary_ids", [])
            if summary_id not in summary_id_set
        ]
        if len(remaining_summary_ids) == len(edge_context.get("summary_ids", [])):
            continue
        if remaining_summary_ids:
            edge.weight = float(len(remaining_summary_ids))
            edge.context = _dump_edge_context(remaining_summary_ids, edge_context.get("note"))
            edges_updated += 1
        else:
            await db.delete(edge)
            edges_deleted += 1

    nodes_deleted = 0
    nodes_updated = 0
    if impacted_node_ids:
        nodes = (
            await db.execute(select(KGNode).where(KGNode.id.in_(impacted_node_ids)))
        ).scalars().all()
        remaining_evidence_ranges = {
            row.node_id: (row.first_seen, row.last_seen)
            for row in (
                await db.execute(
                    select(
                        KGEvidence.node_id.label("node_id"),
                        func.min(KGEvidence.mention_date).label("first_seen"),
                        func.max(KGEvidence.mention_date).label("last_seen"),
                    )
                    .where(KGEvidence.node_id.in_(impacted_node_ids))
                    .group_by(KGEvidence.node_id)
                )
            ).all()
        }
        orphan_node_ids: list[str] = []
        for node in nodes:
            decrement = node_decrements.get(node.id, 0)
            node.mention_count = max(0, node.mention_count - decrement)
            evidence_range = remaining_evidence_ranges.get(node.id)
            if not evidence_range or node.mention_count == 0:
                orphan_node_ids.append(node.id)
                continue
            node.first_seen, node.last_seen = evidence_range
            nodes_updated += 1

        if orphan_node_ids:
            await db.execute(
                delete(KGEdge).where(
                    (KGEdge.source_id.in_(orphan_node_ids))
                    | (KGEdge.target_id.in_(orphan_node_ids))
                )
            )
            await db.execute(delete(KGNode).where(KGNode.id.in_(orphan_node_ids)))
            nodes_deleted = len(orphan_node_ids)

    return {
        "evidences_deleted": evidence_result.rowcount or 0,
        "edges_deleted": edges_deleted,
        "edges_updated": edges_updated,
        "nodes_deleted": nodes_deleted,
        "nodes_updated": nodes_updated,
    }


async def extract_and_merge_graph(
    db: AsyncSession,
    summary_data: dict,
    target_date: date_type,
    summary_id: str | None = None,
    events_data: list[dict] | None = None,
):
    """Extract entities and relationships from summary, merge into graph."""
    llm = get_llm_service()
    prompt = build_graph_extraction_prompt(summary_data)

    try:
        graph_data = await llm.complete_json(prompt)
    except Exception:
        logger.exception(
            "Graph extraction failed for summary %s on %s",
            summary_id,
            target_date.isoformat(),
        )
        return

    if not graph_data.get("nodes"):
        logger.warning(
            "Graph extraction returned no nodes for summary %s on %s",
            summary_id,
            target_date.isoformat(),
        )
        return

    if summary_id:
        stale_nodes_result = await db.execute(
            select(KGEvidence.node_id).where(KGEvidence.summary_id == summary_id).distinct()
        )
        stale_node_ids = stale_nodes_result.scalars().all()
        if stale_node_ids:
            stale_nodes = await db.execute(select(KGNode).where(KGNode.id.in_(stale_node_ids)))
            for node in stale_nodes.scalars().all():
                if node.mention_count > 0:
                    node.mention_count -= 1
        await db.execute(delete(KGEvidence).where(KGEvidence.summary_id == summary_id))

    nodes_by_name: dict[str, KGNode] = {}
    for node_data in graph_data.get("nodes", []):
        name = node_data["name"]
        if name in nodes_by_name:
            node = nodes_by_name[name]
            node.last_seen = target_date
            continue

        with db.no_autoflush:
            existing = await db.execute(select(KGNode).where(KGNode.name == name))
            node = existing.scalar_one_or_none()
        if node:
            node.last_seen = target_date
            node.mention_count += 1
        else:
            node = KGNode(
                name=name,
                type=node_data.get("type", "concept"),
                properties=json.dumps(node_data.get("properties", {}), ensure_ascii=False),
                first_seen=target_date,
                last_seen=target_date,
                mention_count=1,
            )
            db.add(node)
        nodes_by_name[name] = node

    await db.flush()

    for edge_data in graph_data.get("edges", []):
        src = nodes_by_name.get(edge_data["source"])
        tgt = nodes_by_name.get(edge_data["target"])
        if not src or not tgt:
            continue

        existing_edge = await db.execute(
            select(KGEdge).where(
                KGEdge.source_id == src.id,
                KGEdge.target_id == tgt.id,
                KGEdge.relation == edge_data["relation"],
            )
        )
        edge = existing_edge.scalar_one_or_none()
        if edge:
            edge_ctx = _load_edge_context(edge.context)
            summary_ids = edge_ctx.get("summary_ids", [])
            if summary_id and summary_id not in summary_ids:
                summary_ids.append(summary_id)
                edge.weight += 1.0
            elif not summary_id:
                edge.weight += 1.0
            edge.context = _dump_edge_context(summary_ids, edge_data.get("context") or edge_ctx.get("note"))
        else:
            edge_summary_ids = [summary_id] if summary_id else []
            edge = KGEdge(
                source_id=src.id,
                target_id=tgt.id,
                relation=edge_data["relation"],
                weight=1.0,
                context=_dump_edge_context(edge_summary_ids, edge_data.get("context")),
            )
            db.add(edge)

    for node_name, node in nodes_by_name.items():
        excerpt = _find_summary_excerpt(node_name, summary_data)
        if excerpt:
            db.add(
                KGEvidence(
                    node_id=node.id,
                    summary_id=summary_id,
                    source_type="summary",
                    mention_date=target_date,
                    title="每日总结",
                    excerpt=excerpt,
                )
            )

        for match in _find_event_matches(node_name, events_data):
            db.add(
                KGEvidence(
                    node_id=node.id,
                    summary_id=summary_id,
                    event_id=match["event_id"],
                    source_type="event",
                    mention_date=target_date,
                    title=match["title"],
                    excerpt=match["excerpt"],
                )
            )

    await db.commit()


async def rebuild_graph(db: AsyncSession) -> dict:
    edge_result = await db.execute(delete(KGEdge))
    evidence_result = await db.execute(delete(KGEvidence))
    node_result = await db.execute(delete(KGNode))
    await db.commit()

    summaries = (
        await db.execute(select(DailySummary).order_by(DailySummary.date))
    ).scalars().all()

    rebuilt_dates: list[str] = []
    for summary in summaries:
        await extract_and_merge_graph(
            db,
            _summary_to_dict(summary),
            summary.date,
            summary_id=summary.id,
            events_data=await _build_events_data_for_summary(db, summary.date),
        )
        rebuilt_dates.append(summary.date.isoformat())

    node_count = len((await db.execute(select(KGNode))).scalars().all())
    edge_count = len((await db.execute(select(KGEdge))).scalars().all())
    evidence_count = len((await db.execute(select(KGEvidence))).scalars().all())

    return {
        "cleared": {
            "nodes": node_result.rowcount or 0,
            "edges": edge_result.rowcount or 0,
            "evidences": evidence_result.rowcount or 0,
        },
        "rebuilt_dates": rebuilt_dates,
        "graph_counts": {
            "nodes": node_count,
            "edges": edge_count,
            "evidences": evidence_count,
        },
    }


async def refresh_graph_for_date(db: AsyncSession, date_str: str) -> dict:
    target_date = date_type.fromisoformat(date_str)
    summary = (
        await db.execute(select(DailySummary).where(DailySummary.date == target_date))
    ).scalar_one_or_none()
    if not summary:
        raise ValueError("No summary found for this date. Generate a summary first.")

    events_data = await _build_events_data_for_summary(db, target_date)
    await extract_and_merge_graph(
        db,
        _summary_to_dict(summary),
        target_date,
        summary_id=summary.id,
        events_data=events_data,
    )
    return {
        "date": target_date.isoformat(),
        "summary_id": summary.id,
        "event_count": len(events_data),
    }


async def get_graph(db: AsyncSession, limit: int = 100) -> dict:
    nodes_result = await db.execute(
        select(KGNode).order_by(KGNode.mention_count.desc()).limit(limit)
    )
    nodes = nodes_result.scalars().all()

    node_ids = [n.id for n in nodes]
    edges_result = await db.execute(
        select(KGEdge).where(
            KGEdge.source_id.in_(node_ids),
            KGEdge.target_id.in_(node_ids),
        )
    )
    edges = edges_result.scalars().all()

    return {
        "nodes": [
            {
                "id": n.id,
                "name": n.name,
                "type": n.type,
                "mention_count": n.mention_count,
            }
            for n in nodes
        ],
        "edges": [
            {
                "source": e.source_id,
                "target": e.target_id,
                "relation": e.relation,
                "weight": e.weight,
            }
            for e in edges
        ],
    }


async def get_node_detail(db: AsyncSession, node_id: str) -> dict | None:
    result = await db.execute(select(KGNode).where(KGNode.id == node_id))
    node = result.scalar_one_or_none()
    if not node:
        return None

    edges_result = await db.execute(
        select(KGEdge).where(
            (KGEdge.source_id == node_id) | (KGEdge.target_id == node_id)
        )
    )
    edges = edges_result.scalars().all()

    connected_ids = set()
    for e in edges:
        if e.source_id != node_id:
            connected_ids.add(e.source_id)
        if e.target_id != node_id:
            connected_ids.add(e.target_id)

    connected_nodes = []
    if connected_ids:
        cn_result = await db.execute(select(KGNode).where(KGNode.id.in_(connected_ids)))
        connected_nodes = [
            {"id": n.id, "name": n.name, "type": n.type}
            for n in cn_result.scalars().all()
        ]

    evidence_result = await db.execute(
        select(KGEvidence)
        .where(KGEvidence.node_id == node_id)
        .order_by(KGEvidence.mention_date.desc(), KGEvidence.source_type)
        .limit(12)
    )
    evidences = evidence_result.scalars().all()

    return {
        "node": {
            "id": node.id,
            "name": node.name,
            "type": node.type,
            "properties": json.loads(node.properties) if node.properties else {},
            "first_seen": node.first_seen.isoformat() if node.first_seen else None,
            "last_seen": node.last_seen.isoformat() if node.last_seen else None,
            "mention_count": node.mention_count,
        },
        "connected_nodes": connected_nodes,
        "evidences": [
            {
                "source_type": e.source_type,
                "mention_date": e.mention_date.isoformat() if e.mention_date else None,
                "title": e.title,
                "excerpt": e.excerpt,
                "summary_id": e.summary_id,
                "event_id": e.event_id,
            }
            for e in evidences
        ],
    }
