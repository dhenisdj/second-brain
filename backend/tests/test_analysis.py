"""AC-2: 意图理解 — 自动推断用户在做什么"""

import pytest
from unittest.mock import AsyncMock, patch
from conftest import SAMPLE_MANUAL_ENTRIES


LLM_ANALYSIS_RESPONSE = {
    "events": [
        {
            "event_index": 0,
            "category": "work",
            "intent": "项目管理 - 同步团队进度和分配任务",
            "tags": ["Q2-OKR", "团队管理"],
            "confidence": 0.9,
        },
        {
            "event_index": 1,
            "category": "study",
            "intent": "深度学习 - 研究 Transformer 架构原理",
            "tags": ["深度学习", "NLP", "论文阅读"],
            "confidence": 0.95,
        },
        {
            "event_index": 2,
            "category": "life",
            "intent": "休息放松 - 午间休息与社交",
            "tags": ["健康", "社交"],
            "confidence": 0.85,
        },
    ]
}


class TestAnalysisRun:
    """AC-2: LLM 意图分析"""

    @patch("app.services.llm_service.LLMService.complete_json", new_callable=AsyncMock)
    async def test_analysis_run_success(self, mock_llm, client):
        mock_llm.return_value = LLM_ANALYSIS_RESPONSE
        await client.post("/api/ingest/manual", json={"entries": SAMPLE_MANUAL_ENTRIES})

        resp = await client.post("/api/analysis/run", json={"date": "2026-04-03"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["analyzed_count"] == 3
        assert "categories" in data
        assert data["categories"]["work"] >= 1

    @patch("app.services.llm_service.LLMService.complete_json", new_callable=AsyncMock)
    async def test_analysis_results_persisted(self, mock_llm, client):
        mock_llm.return_value = LLM_ANALYSIS_RESPONSE
        await client.post("/api/ingest/manual", json={"entries": SAMPLE_MANUAL_ENTRIES})
        await client.post("/api/analysis/run", json={"date": "2026-04-03"})

        resp = await client.get("/api/events", params={"date": "2026-04-03"})
        items = resp.json()["items"]
        analyzed = [e for e in items if e.get("analysis")]
        assert len(analyzed) == 3
        assert analyzed[0]["analysis"]["category"] in ("work", "study", "life", "entertainment")
        assert len(analyzed[0]["analysis"]["tags"]) >= 1

    @patch("app.services.llm_service.LLMService.complete_json", new_callable=AsyncMock)
    async def test_analysis_has_intent_field(self, mock_llm, client):
        mock_llm.return_value = LLM_ANALYSIS_RESPONSE
        await client.post("/api/ingest/manual", json={"entries": SAMPLE_MANUAL_ENTRIES})
        await client.post("/api/analysis/run", json={"date": "2026-04-03"})

        resp = await client.get("/api/events", params={"date": "2026-04-03"})
        for item in resp.json()["items"]:
            assert "intent" in item["analysis"]
            assert len(item["analysis"]["intent"]) > 0

    async def test_analysis_no_events(self, client):
        resp = await client.post("/api/analysis/run", json={"date": "2020-01-01"})
        assert resp.status_code == 200
        assert resp.json()["analyzed_count"] == 0

    async def test_analysis_missing_date(self, client):
        resp = await client.post("/api/analysis/run", json={})
        assert resp.status_code == 422

    @patch("app.services.llm_service.LLMService.complete_json", new_callable=AsyncMock)
    async def test_analysis_llm_failure_returns_500(self, mock_llm, client):
        mock_llm.side_effect = Exception("LLM service unavailable")
        await client.post("/api/ingest/manual", json={"entries": SAMPLE_MANUAL_ENTRIES})

        resp = await client.post("/api/analysis/run", json={"date": "2026-04-03"})
        assert resp.status_code == 500
