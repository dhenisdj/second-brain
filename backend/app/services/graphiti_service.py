import json
import logging
from datetime import date as date_type
from typing import Any

from app.config import settings
from app.services.graphiti_mcp_client import GraphitiMCPClient, GraphitiMCPError

logger = logging.getLogger(__name__)

MAX_EPISODE_EVENTS = 80


def is_enabled() -> bool:
    return bool(settings.GRAPHITI_MCP_ENABLED)


def _event_payload(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": event.get("id"),
        "timestamp": event.get("timestamp"),
        "title": event.get("title"),
        "content": event.get("content"),
        "category": event.get("category"),
        "intent": event.get("intent"),
        "tags": event.get("tags") or [],
        "duration_minutes": event.get("duration_minutes"),
    }


def build_summary_episode_body(
    summary_data: dict[str, Any],
    target_date: date_type,
    *,
    summary_id: str | None = None,
    events_data: list[dict[str, Any]] | None = None,
) -> str:
    payload = {
        "source": "second-brain",
        "kind": "daily_summary",
        "date": target_date.isoformat(),
        "summary_id": summary_id,
        "summary": {
            "timeline_md": summary_data.get("timeline_md") or "",
            "progress_md": summary_data.get("progress_md") or "",
            "knowledge_md": summary_data.get("knowledge_md") or "",
            "time_distribution": summary_data.get("time_distribution") or {},
        },
        "events": [
            _event_payload(event)
            for event in (events_data or [])[:MAX_EPISODE_EVENTS]
        ],
    }
    return json.dumps(payload, ensure_ascii=False)


def _client() -> GraphitiMCPClient:
    return GraphitiMCPClient(
        settings.GRAPHITI_MCP_URL,
        timeout_seconds=settings.GRAPHITI_MCP_TIMEOUT_SECONDS,
        allow_remote=settings.GRAPHITI_MCP_ALLOW_REMOTE,
    )


async def publish_summary_episode(
    summary_data: dict[str, Any],
    target_date: date_type,
    *,
    summary_id: str | None = None,
    events_data: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if not is_enabled():
        return {"enabled": False, "published": False}

    episode_body = build_summary_episode_body(
        summary_data,
        target_date,
        summary_id=summary_id,
        events_data=events_data,
    )

    try:
        async with _client() as client:
            result = await client.add_memory(
                name=f"second-brain-daily-summary-{target_date.isoformat()}",
                episode_body=episode_body,
                group_id=settings.GRAPHITI_MCP_GROUP_ID,
                source="json",
                source_description="Second Brain daily summary and supporting events",
                uuid=summary_id,
            )
    except GraphitiMCPError as exc:
        logger.warning("Graphiti MCP publish failed for %s: %s", target_date.isoformat(), exc)
        return {"enabled": True, "published": False, "error": str(exc)}

    return {"enabled": True, "published": True, "result": result}


async def get_status() -> dict[str, Any]:
    if not is_enabled():
        return {"enabled": False, "status": "disabled"}
    try:
        async with _client() as client:
            status = await client.get_status()
    except GraphitiMCPError as exc:
        return {"enabled": True, "status": "error", "error": str(exc)}
    return {"enabled": True, **status}


async def search(query: str, *, kind: str = "facts", limit: int = 10) -> dict[str, Any]:
    if not is_enabled():
        return {"enabled": False, "results": []}
    try:
        async with _client() as client:
            if kind == "nodes":
                result = await client.search_nodes(
                    query=query,
                    group_ids=[settings.GRAPHITI_MCP_GROUP_ID],
                    max_nodes=limit,
                )
            else:
                result = await client.search_facts(
                    query=query,
                    group_ids=[settings.GRAPHITI_MCP_GROUP_ID],
                    max_facts=limit,
                )
    except GraphitiMCPError as exc:
        return {"enabled": True, "error": str(exc), "results": []}
    return {"enabled": True, "kind": kind, "result": result}
