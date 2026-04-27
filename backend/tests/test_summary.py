"""AC-3: 每日总结生成"""

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, patch
from conftest import SAMPLE_MANUAL_ENTRIES
from app.models.event import Event
from app.models.analysis import Analysis
from app.services import summary_service
from app.services.llm_service import LLMTimeoutError


LLM_SUMMARY_RESPONSE = {
    "timeline_md": "## 时间线\n- 09:00 团队站会：讨论 Q2 OKR\n- 10:00 论文阅读：Transformer\n- 12:00 午餐散步",
    "progress_md": "## 事项进展\n### Q2 OKR\n- 分配了数据分析任务，进度 40%\n### 论文学习\n- 完成 Attention Is All You Need 精读",
    "knowledge_md": "## 新知识\n- Self-attention 机制：通过 Q/K/V 矩阵计算注意力权重\n- Multi-head attention 可以并行捕捉不同子空间特征",
    "time_distribution": {"work": 40, "study": 35, "life": 25},
}

LLM_ANALYSIS_RESPONSE = {
    "events": [
        {"event_index": 0, "category": "work", "intent": "项目管理", "tags": ["Q2-OKR"], "confidence": 0.9},
        {"event_index": 1, "category": "study", "intent": "论文阅读", "tags": ["深度学习"], "confidence": 0.9},
        {"event_index": 2, "category": "life", "intent": "休息", "tags": ["健康"], "confidence": 0.9},
    ]
}


async def _seed_and_analyze(client, mock_llm):
    """Helper: import data and run analysis before generating summary."""
    mock_llm.return_value = LLM_ANALYSIS_RESPONSE
    await client.post("/api/ingest/manual", json={"entries": SAMPLE_MANUAL_ENTRIES})
    await client.post("/api/analysis/run", json={"date": "2026-04-03"})


class TestSummaryGenerate:
    """AC-3: 生成每日总结"""

    @patch("app.services.llm_service.LLMService.complete_json", new_callable=AsyncMock)
    async def test_generate_summary_success(self, mock_llm, client):
        await _seed_and_analyze(client, mock_llm)
        mock_llm.return_value = LLM_SUMMARY_RESPONSE

        resp = await client.post("/api/summary/generate", json={"date": "2026-04-03"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["date"] == "2026-04-03"
        assert "timeline_md" in data
        assert "progress_md" in data
        assert "knowledge_md" in data
        assert "time_distribution" in data

    @patch("app.services.llm_service.LLMService.complete_json", new_callable=AsyncMock)
    async def test_summary_contains_timeline(self, mock_llm, client):
        await _seed_and_analyze(client, mock_llm)
        mock_llm.return_value = LLM_SUMMARY_RESPONSE

        resp = await client.post("/api/summary/generate", json={"date": "2026-04-03"})
        assert "时间线" in resp.json()["timeline_md"]

    @patch("app.services.llm_service.LLMService.complete_json", new_callable=AsyncMock)
    async def test_summary_time_distribution_sums_to_100(self, mock_llm, client):
        await _seed_and_analyze(client, mock_llm)
        mock_llm.return_value = LLM_SUMMARY_RESPONSE

        resp = await client.post("/api/summary/generate", json={"date": "2026-04-03"})
        dist = resp.json()["time_distribution"]
        assert sum(dist.values()) == 100

    @patch("app.services.llm_service.LLMService.complete_json", new_callable=AsyncMock)
    async def test_summary_get_after_generate(self, mock_llm, client):
        await _seed_and_analyze(client, mock_llm)
        mock_llm.return_value = LLM_SUMMARY_RESPONSE

        await client.post("/api/summary/generate", json={"date": "2026-04-03"})
        resp = await client.get("/api/summary/2026-04-03")
        assert resp.status_code == 200
        assert resp.json()["date"] == "2026-04-03"

    async def test_summary_get_nonexistent(self, client):
        resp = await client.get("/api/summary/2020-01-01")
        assert resp.status_code == 404

    async def test_generate_summary_no_analysis(self, client):
        """Should fail gracefully if events haven't been analyzed yet."""
        await client.post("/api/ingest/manual", json={"entries": SAMPLE_MANUAL_ENTRIES})
        resp = await client.post("/api/summary/generate", json={"date": "2026-04-03"})
        assert resp.status_code == 400

    @patch("app.routers.summary.summary_service.generate_summary", new_callable=AsyncMock)
    async def test_generate_summary_timeout_returns_504(self, mock_generate, client):
        mock_generate.side_effect = LLMTimeoutError("LLM request timed out")

        resp = await client.post("/api/summary/generate", json={"date": "2026-04-03"})

        assert resp.status_code == 504
        assert "超时" in resp.json()["detail"]

    @patch("app.services.summary_service.extract_and_merge_graph", new_callable=AsyncMock)
    @patch("app.services.llm_service.LLMService.complete_json", new_callable=AsyncMock)
    async def test_generate_summary_compresses_chrome_and_uses_latest_analysis(
        self,
        mock_llm,
        _mock_graph,
        db_session,
    ):
        chrome_1 = Event(
            source="chrome",
            timestamp=datetime.fromisoformat("2026-04-03T10:00:00"),
            title="GitHub Pull Request",
            content="review PR",
            url="https://github.com/openai/openai-python/pull/1",
        )
        chrome_2 = Event(
            source="chrome",
            timestamp=datetime.fromisoformat("2026-04-03T10:20:00"),
            title="GitHub Issue",
            content="check issue",
            url="https://github.com/openai/openai-python/issues/2",
        )
        manual = Event(
            source="manual",
            timestamp=datetime.fromisoformat("2026-04-03T11:00:00"),
            title="项目复盘",
            content="梳理上线问题",
            duration_minutes=45,
        )
        db_session.add_all([chrome_1, chrome_2, manual])
        await db_session.flush()

        db_session.add_all(
            [
                Analysis(
                    event_id=chrome_1.id,
                    category="work",
                    intent="代码协作",
                    tags='["github"]',
                    confidence=0.9,
                    created_at=datetime.fromisoformat("2026-04-03T10:01:00"),
                ),
                Analysis(
                    event_id=chrome_2.id,
                    category="work",
                    intent="代码协作",
                    tags='["github", "issue"]',
                    confidence=0.9,
                    created_at=datetime.fromisoformat("2026-04-03T10:21:00"),
                ),
                Analysis(
                    event_id=manual.id,
                    category="work",
                    intent="旧意图",
                    tags='["legacy"]',
                    confidence=0.2,
                    created_at=datetime.fromisoformat("2026-04-03T10:59:00"),
                ),
                Analysis(
                    event_id=manual.id,
                    category="work",
                    intent="新意图",
                    tags='["retro"]',
                    confidence=0.95,
                    created_at=datetime.fromisoformat("2026-04-03T11:01:00"),
                ),
            ]
        )
        await db_session.commit()

        mock_llm.return_value = LLM_SUMMARY_RESPONSE

        result = await summary_service.generate_summary(db_session, "2026-04-03")

        prompt = mock_llm.await_args.args[0]
        assert result["date"] == "2026-04-03"
        assert "浏览 github.com" in prompt
        assert "旧意图" not in prompt
        assert "新意图" in prompt
