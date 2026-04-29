import json
from datetime import date

import pytest

from app.config import settings
from app.services import graphiti_service
from app.services.graphiti_mcp_client import _parse_mcp_response


def test_parse_mcp_response_accepts_json_response():
    payload = {"jsonrpc": "2.0", "result": {"ok": True}}

    assert _parse_mcp_response(json.dumps(payload)) == payload


def test_parse_mcp_response_accepts_event_stream_response():
    payload = {"jsonrpc": "2.0", "result": {"ok": True}}
    raw = f"event: message\ndata: {json.dumps(payload)}\n\n"

    assert _parse_mcp_response(raw) == payload


def test_build_summary_episode_body_contains_summary_and_events():
    body = graphiti_service.build_summary_episode_body(
        {
            "timeline_md": "## 时间线",
            "progress_md": "## 事项进展",
            "knowledge_md": "Transformer 和 Self-Attention",
            "time_distribution": {"study": 100},
        },
        date.fromisoformat("2026-04-03"),
        summary_id="summary-1",
        events_data=[
            {
                "id": "event-1",
                "timestamp": "2026-04-03T10:00:00",
                "title": "阅读 Transformer 论文",
                "content": "理解 self-attention",
                "category": "study",
                "intent": "论文阅读",
                "tags": ["深度学习"],
                "duration_minutes": 60,
            }
        ],
    )

    payload = json.loads(body)
    assert payload["kind"] == "daily_summary"
    assert payload["summary_id"] == "summary-1"
    assert payload["summary"]["knowledge_md"] == "Transformer 和 Self-Attention"
    assert payload["events"][0]["title"] == "阅读 Transformer 论文"


@pytest.mark.asyncio
async def test_publish_summary_episode_noops_when_disabled(monkeypatch):
    monkeypatch.setattr(settings, "GRAPHITI_MCP_ENABLED", False)

    result = await graphiti_service.publish_summary_episode(
        {"knowledge_md": "Transformer"},
        date.fromisoformat("2026-04-03"),
    )

    assert result == {"enabled": False, "published": False}


@pytest.mark.asyncio
async def test_publish_summary_episode_calls_graphiti_mcp(monkeypatch):
    calls = []

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def add_memory(self, **kwargs):
            calls.append(kwargs)
            return {"message": "queued"}

    monkeypatch.setattr(settings, "GRAPHITI_MCP_ENABLED", True)
    monkeypatch.setattr(settings, "GRAPHITI_MCP_GROUP_ID", "test-group")
    monkeypatch.setattr(graphiti_service, "_client", lambda: FakeClient())

    result = await graphiti_service.publish_summary_episode(
        {"knowledge_md": "Transformer"},
        date.fromisoformat("2026-04-03"),
        summary_id="summary-1",
    )

    assert result["published"] is True
    assert calls[0]["name"] == "second-brain-daily-summary-2026-04-03"
    assert calls[0]["group_id"] == "test-group"
    assert calls[0]["source"] == "json"
    assert calls[0]["uuid"] == "summary-1"
    assert "Transformer" in calls[0]["episode_body"]


async def test_graphiti_status_route_disabled(client, monkeypatch):
    monkeypatch.setattr(settings, "GRAPHITI_MCP_ENABLED", False)

    resp = await client.get("/api/knowledge/graphiti/status")

    assert resp.status_code == 200
    assert resp.json() == {"enabled": False, "status": "disabled"}
