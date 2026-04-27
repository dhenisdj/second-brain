"""AC-4: 知识图谱 — 轻量版"""

import pytest
import json
from datetime import datetime, date
from unittest.mock import AsyncMock, patch
from conftest import SAMPLE_MANUAL_ENTRIES
from app.models.event import Event
from app.models.analysis import Analysis
from app.models.summary import DailySummary
from app.services import graph_service


LLM_ANALYSIS_RESPONSE = {
    "events": [
        {"event_index": 0, "category": "work", "intent": "项目管理", "tags": ["Q2-OKR"], "confidence": 0.9},
        {"event_index": 1, "category": "study", "intent": "论文阅读", "tags": ["深度学习"], "confidence": 0.9},
        {"event_index": 2, "category": "life", "intent": "休息", "tags": ["健康"], "confidence": 0.9},
    ]
}

LLM_SUMMARY_RESPONSE = {
    "timeline_md": "## 时间线\n- 09:00 团队站会\n- 10:00 论文阅读",
    "progress_md": "## 事项进展",
    "knowledge_md": "## 新知识",
    "time_distribution": {"work": 40, "study": 35, "life": 25},
}

LLM_GRAPH_RESPONSE = {
    "nodes": [
        {"name": "Q2 OKR", "type": "project"},
        {"name": "Transformer", "type": "concept"},
        {"name": "Self-Attention", "type": "concept"},
        {"name": "团队管理", "type": "topic"},
    ],
    "edges": [
        {"source": "Q2 OKR", "target": "团队管理", "relation": "related_to"},
        {"source": "Transformer", "target": "Self-Attention", "relation": "uses"},
    ],
}


async def _seed_full_pipeline(client, mock_llm):
    """Import → analyze → summarize, so graph extraction has data."""
    mock_llm.return_value = LLM_ANALYSIS_RESPONSE
    await client.post("/api/ingest/manual", json={"entries": SAMPLE_MANUAL_ENTRIES})
    await client.post("/api/analysis/run", json={"date": "2026-04-03"})
    mock_llm.return_value = LLM_SUMMARY_RESPONSE
    await client.post("/api/summary/generate", json={"date": "2026-04-03"})


class TestKnowledgeGraph:
    """AC-4: 知识图谱查询"""

    @patch("app.services.llm_service.LLMService.complete_json", new_callable=AsyncMock)
    async def test_graph_returns_nodes_and_edges(self, mock_llm, client):
        await _seed_full_pipeline(client, mock_llm)
        mock_llm.return_value = LLM_GRAPH_RESPONSE
        await client.post("/api/knowledge/rebuild")

        resp = await client.get("/api/knowledge/graph")
        assert resp.status_code == 200
        data = resp.json()
        assert "nodes" in data
        assert "edges" in data
        assert len(data["nodes"]) >= 1

    @patch("app.services.llm_service.LLMService.complete_json", new_callable=AsyncMock)
    async def test_graph_node_has_required_fields(self, mock_llm, client):
        await _seed_full_pipeline(client, mock_llm)
        mock_llm.return_value = LLM_GRAPH_RESPONSE
        await client.post("/api/knowledge/rebuild")

        resp = await client.get("/api/knowledge/graph")
        for node in resp.json()["nodes"]:
            assert "id" in node
            assert "name" in node
            assert "type" in node
            assert node["type"] in ("project", "person", "concept", "tool", "topic")

    @patch("app.services.llm_service.LLMService.complete_json", new_callable=AsyncMock)
    async def test_graph_edge_has_required_fields(self, mock_llm, client):
        await _seed_full_pipeline(client, mock_llm)
        mock_llm.return_value = LLM_GRAPH_RESPONSE
        await client.post("/api/knowledge/rebuild")

        resp = await client.get("/api/knowledge/graph")
        for edge in resp.json()["edges"]:
            assert "source" in edge
            assert "target" in edge
            assert "relation" in edge

    async def test_graph_empty_when_no_data(self, client):
        resp = await client.get("/api/knowledge/graph")
        assert resp.status_code == 200
        data = resp.json()
        assert data["nodes"] == []
        assert data["edges"] == []

    @patch("app.services.llm_service.LLMService.complete_json", new_callable=AsyncMock)
    async def test_node_detail_with_related_events(self, mock_llm, client):
        await _seed_full_pipeline(client, mock_llm)
        mock_llm.return_value = LLM_GRAPH_RESPONSE
        await client.post("/api/knowledge/rebuild")

        graph_resp = await client.get("/api/knowledge/graph")
        node_id = graph_resp.json()["nodes"][0]["id"]

        resp = await client.get(f"/api/knowledge/node/{node_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert "node" in data
        assert "connected_nodes" in data
        assert "evidences" in data

    @patch("app.services.llm_service.LLMService.complete_json", new_callable=AsyncMock)
    async def test_node_detail_contains_evidence_chain(self, mock_llm, client):
        await _seed_full_pipeline(client, mock_llm)
        mock_llm.return_value = {
            "nodes": [{"name": "Transformer", "type": "concept"}],
            "edges": [],
        }
        await client.post("/api/knowledge/rebuild")

        graph_resp = await client.get("/api/knowledge/graph")
        node_id = graph_resp.json()["nodes"][0]["id"]

        detail_resp = await client.get(f"/api/knowledge/node/{node_id}")
        assert detail_resp.status_code == 200
        evidences = detail_resp.json()["evidences"]
        assert len(evidences) >= 1
        assert evidences[0]["source_type"] in ("summary", "event")

    async def test_node_detail_not_found(self, client):
        resp = await client.get("/api/knowledge/node/nonexistent-id")
        assert resp.status_code == 404

    @patch("app.services.llm_service.LLMService.complete_json", new_callable=AsyncMock)
    async def test_rebuild_graph_reconstructs_from_existing_summaries(self, mock_llm, db_session):
        event = Event(
            source="manual",
            timestamp=datetime.fromisoformat("2026-04-03T09:00:00"),
            title="团队站会",
            content="讨论 Q2 OKR 进展",
            duration_minutes=30,
        )
        db_session.add(event)
        await db_session.flush()

        db_session.add(
            Analysis(
                event_id=event.id,
                category="work",
                intent="项目管理",
                tags='["Q2-OKR"]',
                confidence=0.9,
            )
        )
        db_session.add(
            DailySummary(
                date=date.fromisoformat("2026-04-03"),
                timeline_md=LLM_SUMMARY_RESPONSE["timeline_md"],
                progress_md=LLM_SUMMARY_RESPONSE["progress_md"],
                knowledge_md=LLM_SUMMARY_RESPONSE["knowledge_md"],
                time_distribution=json.dumps(LLM_SUMMARY_RESPONSE["time_distribution"], ensure_ascii=False),
                raw_llm_response=json.dumps(LLM_SUMMARY_RESPONSE, ensure_ascii=False),
            )
        )
        await db_session.commit()

        mock_llm.return_value = LLM_GRAPH_RESPONSE

        result = await graph_service.rebuild_graph(db_session)

        assert result["rebuilt_dates"] == ["2026-04-03"]
        assert result["graph_counts"]["nodes"] >= 1
        assert result["graph_counts"]["edges"] >= 1
