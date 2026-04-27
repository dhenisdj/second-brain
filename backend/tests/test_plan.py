"""AC-5: 计划与建议生成"""

import pytest
from unittest.mock import AsyncMock, patch
from conftest import SAMPLE_MANUAL_ENTRIES


LLM_ANALYSIS_RESPONSE = {
    "events": [
        {"event_index": 0, "category": "work", "intent": "项目管理", "tags": ["Q2-OKR"], "confidence": 0.9},
        {"event_index": 1, "category": "study", "intent": "论文阅读", "tags": ["深度学习"], "confidence": 0.9},
        {"event_index": 2, "category": "life", "intent": "休息", "tags": ["健康"], "confidence": 0.9},
    ]
}

LLM_SUMMARY_RESPONSE = {
    "timeline_md": "## 时间线",
    "progress_md": "## 进展",
    "knowledge_md": "## 知识",
    "time_distribution": {"work": 40, "study": 35, "life": 25},
}

LLM_PLAN_RESPONSE = {
    "items": [
        {"title": "跟进 Q2 OKR 数据分析", "priority": "high", "reason": "今日站会提到进度滞后"},
        {"title": "复习 Transformer 论文", "priority": "medium", "reason": "今日学习中断未完成"},
        {"title": "准备周报", "priority": "low", "reason": "周五例行事务"},
    ],
    "suggestions": [
        {"type": "attention", "content": "今日工作占比 40%，建议明日留出 2h 深度学习时间"},
        {"type": "review", "content": "连续 3 天接触 Transformer，建议做系统复盘"},
    ],
}


async def _seed_with_summary(client, mock_llm):
    mock_llm.return_value = LLM_ANALYSIS_RESPONSE
    await client.post("/api/ingest/manual", json={"entries": SAMPLE_MANUAL_ENTRIES})
    await client.post("/api/analysis/run", json={"date": "2026-04-03"})
    mock_llm.return_value = LLM_SUMMARY_RESPONSE
    await client.post("/api/summary/generate", json={"date": "2026-04-03"})


class TestPlanGenerate:
    """AC-5: 基于总结生成计划与建议"""

    @patch("app.services.llm_service.LLMService.complete_json", new_callable=AsyncMock)
    async def test_generate_plan_success(self, mock_llm, client):
        await _seed_with_summary(client, mock_llm)
        mock_llm.return_value = LLM_PLAN_RESPONSE

        resp = await client.post("/api/plan/generate", json={"date": "2026-04-03"})
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "suggestions" in data
        assert len(data["items"]) >= 1

    @patch("app.services.llm_service.LLMService.complete_json", new_callable=AsyncMock)
    async def test_plan_items_have_priority(self, mock_llm, client):
        await _seed_with_summary(client, mock_llm)
        mock_llm.return_value = LLM_PLAN_RESPONSE

        resp = await client.post("/api/plan/generate", json={"date": "2026-04-03"})
        for item in resp.json()["items"]:
            assert "title" in item
            assert "priority" in item
            assert item["priority"] in ("high", "medium", "low")
            assert "reason" in item

    @patch("app.services.llm_service.LLMService.complete_json", new_callable=AsyncMock)
    async def test_plan_suggestions_have_type(self, mock_llm, client):
        await _seed_with_summary(client, mock_llm)
        mock_llm.return_value = LLM_PLAN_RESPONSE

        resp = await client.post("/api/plan/generate", json={"date": "2026-04-03"})
        for sug in resp.json()["suggestions"]:
            assert "type" in sug
            assert sug["type"] in ("attention", "review", "health", "goal")
            assert "content" in sug

    async def test_generate_plan_no_summary(self, client):
        resp = await client.post("/api/plan/generate", json={"date": "2020-01-01"})
        assert resp.status_code == 400

    @patch("app.services.llm_service.LLMService.complete_json", new_callable=AsyncMock)
    async def test_plan_edit(self, mock_llm, client):
        await _seed_with_summary(client, mock_llm)
        mock_llm.return_value = LLM_PLAN_RESPONSE
        create_resp = await client.post("/api/plan/generate", json={"date": "2026-04-03"})
        plan_id = create_resp.json()["id"]

        updated_items = [{"title": "修改后的计划", "priority": "high", "reason": "用户编辑"}]
        resp = await client.put(f"/api/plan/{plan_id}", json={"items": updated_items})
        assert resp.status_code == 200
        assert resp.json()["items"][0]["title"] == "修改后的计划"

    async def test_plan_edit_not_found(self, client):
        resp = await client.put("/api/plan/nonexistent-id", json={"items": []})
        assert resp.status_code == 404

    @patch("app.services.llm_service.LLMService.complete_json", new_callable=AsyncMock)
    async def test_get_plan_by_summary_date(self, mock_llm, client):
        await _seed_with_summary(client, mock_llm)
        mock_llm.return_value = LLM_PLAN_RESPONSE
        await client.post("/api/plan/generate", json={"date": "2026-04-03"})

        resp = await client.get("/api/plan/by-summary/2026-04-03")
        assert resp.status_code == 200
        assert len(resp.json()["items"]) >= 1

    @patch("app.services.llm_service.LLMService.complete_json", new_callable=AsyncMock)
    async def test_generate_plan_reuses_existing_record(self, mock_llm, client):
        await _seed_with_summary(client, mock_llm)
        mock_llm.return_value = LLM_PLAN_RESPONSE

        first = await client.post("/api/plan/generate", json={"date": "2026-04-03"})
        second = await client.post("/api/plan/generate", json={"date": "2026-04-03"})

        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json()["id"] == second.json()["id"]
