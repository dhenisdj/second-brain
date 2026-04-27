"""AC-7: 数据可审计可删除"""

from datetime import datetime
from unittest.mock import AsyncMock, patch

from sqlalchemy import select

from conftest import SAMPLE_MANUAL_ENTRIES
from app.models.analysis import Analysis
from app.models.event import Event


LLM_ANALYSIS_RESPONSE = {
    "events": [
        {"event_index": 0, "category": "work", "intent": "项目管理", "tags": ["Q2-OKR"], "confidence": 0.9},
        {"event_index": 1, "category": "study", "intent": "论文阅读", "tags": ["深度学习"], "confidence": 0.9},
        {"event_index": 2, "category": "life", "intent": "休息", "tags": ["健康"], "confidence": 0.9},
    ]
}

LLM_SUMMARY_RESPONSE = {
    "timeline_md": "## 时间线",
    "progress_md": "## 事项进展",
    "knowledge_md": "## 新知识",
    "time_distribution": {"work": 40, "study": 35, "life": 25},
}

LLM_PLAN_RESPONSE = {
    "items": [
        {"title": "跟进 Q2 OKR", "priority": "high", "reason": "推进项目"},
    ],
    "suggestions": [
        {"type": "attention", "content": "留出完整深度工作时间"},
    ],
}


class TestDataOverview:
    """AC-7: 按日期浏览数据概览"""

    async def test_overview_with_data(self, client):
        await client.post("/api/ingest/manual", json={"entries": SAMPLE_MANUAL_ENTRIES})
        resp = await client.get("/api/data/overview", params={
            "start": "2026-04-01",
            "end": "2026-04-05",
        })
        assert resp.status_code == 200
        days = resp.json()["days"]
        assert len(days) >= 1
        day = next(d for d in days if d["date"] == "2026-04-03")
        assert day["event_count"] == 3

    async def test_overview_empty_range(self, client):
        resp = await client.get("/api/data/overview", params={
            "start": "2020-01-01",
            "end": "2020-01-31",
        })
        assert resp.status_code == 200
        assert resp.json()["days"] == []


class TestDeleteEvent:
    """AC-7: 删除单条事件"""

    async def test_delete_single_event(self, client):
        await client.post("/api/ingest/manual", json={"entries": SAMPLE_MANUAL_ENTRIES})
        events_resp = await client.get("/api/events", params={"date": "2026-04-03"})
        event_id = events_resp.json()["items"][0]["id"]

        resp = await client.delete(f"/api/data/events/{event_id}")
        assert resp.status_code == 200

        events_resp2 = await client.get("/api/events", params={"date": "2026-04-03"})
        assert events_resp2.json()["total"] == 2

    @patch("app.services.llm_service.LLMService.complete_json", new_callable=AsyncMock)
    async def test_delete_event_cascades_analysis(self, mock_llm, client):
        mock_llm.return_value = LLM_ANALYSIS_RESPONSE
        await client.post("/api/ingest/manual", json={"entries": SAMPLE_MANUAL_ENTRIES})
        await client.post("/api/analysis/run", json={"date": "2026-04-03"})

        events_resp = await client.get("/api/events", params={"date": "2026-04-03"})
        event_id = events_resp.json()["items"][0]["id"]

        await client.delete(f"/api/data/events/{event_id}")

        events_resp2 = await client.get("/api/events", params={"date": "2026-04-03"})
        remaining_ids = [e["id"] for e in events_resp2.json()["items"]]
        assert event_id not in remaining_ids

    async def test_delete_event_removes_all_analysis_versions(self, client, db_session):
        event = Event(
            source="manual",
            timestamp=datetime.fromisoformat("2026-04-03T09:00:00"),
            title="团队站会",
            content="同步项目进展",
        )
        db_session.add(event)
        await db_session.flush()
        db_session.add_all(
            [
                Analysis(event_id=event.id, category="work", intent="旧版本", tags='["old"]', confidence=0.2),
                Analysis(event_id=event.id, category="work", intent="新版本", tags='["new"]', confidence=0.9),
            ]
        )
        await db_session.commit()
        event_id = event.id

        resp = await client.delete(f"/api/data/events/{event_id}")

        assert resp.status_code == 200
        assert resp.json()["analyses"] == 2
        db_session.expire_all()
        assert await db_session.get(Event, event_id) is None
        remaining = await db_session.execute(select(Analysis).where(Analysis.event_id == event_id))
        assert remaining.scalars().all() == []

    async def test_delete_nonexistent_event(self, client):
        resp = await client.delete("/api/data/events/nonexistent-id")
        assert resp.status_code == 404


class TestDeleteDay:
    """AC-7: 删除整天数据"""

    @patch("app.services.llm_service.LLMService.complete_json", new_callable=AsyncMock)
    async def test_delete_day_all_data(self, mock_llm, client):
        mock_llm.return_value = LLM_ANALYSIS_RESPONSE
        await client.post("/api/ingest/manual", json={"entries": SAMPLE_MANUAL_ENTRIES})
        await client.post("/api/analysis/run", json={"date": "2026-04-03"})

        resp = await client.delete("/api/data/day/2026-04-03")
        assert resp.status_code == 200
        deleted = resp.json()["deleted"]
        assert deleted["events"] == 3
        assert deleted["analyses"] == 3

    @patch("app.services.llm_service.LLMService.complete_json", new_callable=AsyncMock)
    async def test_day_is_empty_after_delete(self, mock_llm, client):
        mock_llm.return_value = LLM_ANALYSIS_RESPONSE
        await client.post("/api/ingest/manual", json={"entries": SAMPLE_MANUAL_ENTRIES})
        await client.post("/api/analysis/run", json={"date": "2026-04-03"})

        await client.delete("/api/data/day/2026-04-03")

        events_resp = await client.get("/api/events", params={"date": "2026-04-03"})
        assert events_resp.json()["total"] == 0

    async def test_delete_day_no_data(self, client):
        resp = await client.delete("/api/data/day/2020-01-01")
        assert resp.status_code == 200
        deleted = resp.json()["deleted"]
        assert deleted["events"] == 0

    @patch("app.services.llm_service.LLMService.complete_json", new_callable=AsyncMock)
    async def test_delete_day_removes_generated_plan(self, mock_llm, client):
        mock_llm.return_value = LLM_ANALYSIS_RESPONSE
        await client.post("/api/ingest/manual", json={"entries": SAMPLE_MANUAL_ENTRIES})
        await client.post("/api/analysis/run", json={"date": "2026-04-03"})

        mock_llm.return_value = LLM_SUMMARY_RESPONSE
        await client.post("/api/summary/generate", json={"date": "2026-04-03"})

        mock_llm.return_value = LLM_PLAN_RESPONSE
        await client.post("/api/plan/generate", json={"date": "2026-04-03"})

        delete_resp = await client.delete("/api/data/day/2026-04-03")
        assert delete_resp.status_code == 200
        assert delete_resp.json()["deleted"]["plans"] == 1

        plan_resp = await client.get("/api/plan/by-summary/2026-04-03")
        assert plan_resp.status_code == 404

    @patch("app.services.llm_service.LLMService.complete_json", new_callable=AsyncMock)
    async def test_delete_day_removes_graph_edges_and_nodes(self, mock_llm, client):
        mock_llm.return_value = LLM_ANALYSIS_RESPONSE
        await client.post("/api/ingest/manual", json={"entries": SAMPLE_MANUAL_ENTRIES})
        await client.post("/api/analysis/run", json={"date": "2026-04-03"})

        mock_llm.return_value = LLM_SUMMARY_RESPONSE
        await client.post("/api/summary/generate", json={"date": "2026-04-03"})

        mock_llm.return_value = {
            "nodes": [
                {"name": "Q2 OKR", "type": "project"},
                {"name": "团队管理", "type": "topic"},
            ],
            "edges": [
                {"source": "Q2 OKR", "target": "团队管理", "relation": "related_to"},
            ],
        }
        await client.post("/api/knowledge/rebuild")

        before_resp = await client.get("/api/knowledge/graph")
        assert before_resp.status_code == 200
        assert len(before_resp.json()["nodes"]) == 2
        assert len(before_resp.json()["edges"]) == 1

        delete_resp = await client.delete("/api/data/day/2026-04-03")

        assert delete_resp.status_code == 200
        assert delete_resp.json()["deleted"]["graph_edges"] == 1
        assert delete_resp.json()["deleted"]["graph_nodes"] == 2

        after_resp = await client.get("/api/knowledge/graph")
        assert after_resp.status_code == 200
        assert after_resp.json()["nodes"] == []
        assert after_resp.json()["edges"] == []
