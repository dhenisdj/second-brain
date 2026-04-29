"""
E2E Scenario 1: Full Pipeline — AC-1 → AC-2 → AC-3 → AC-4 → AC-5

Verifies the complete user journey:
  Load manual data → Run analysis → Generate summary → Check knowledge graph → Generate plan
"""

import pytest
from unittest.mock import AsyncMock, patch


LLM_ANALYSIS = {
    "events": [
        {"event_index": i, "category": cat, "intent": intent, "tags": tags, "confidence": 0.9}
        for i, (cat, intent, tags) in enumerate([
            ("work", "项目管理 - 晨会同步进展", ["Q2-OKR", "团队管理"]),
            ("work", "代码审查 - 推荐算法优化", ["推荐系统", "协同过滤"]),
            ("study", "技术学习 - 向量数据库调研", ["向量数据库", "Pinecone"]),
            ("work", "开发 - ETL 数据管道", ["数据工程", "ETL"]),
            ("life", "午餐休息", ["健康"]),
            ("work", "职业发展讨论", ["职业规划", "导师"]),
            ("study", "编程学习 - Rust 基础", ["Rust", "编程语言"]),
            ("work", "Bug 修复 - 搜索服务", ["搜索服务", "线上问题"]),
            ("life", "健身 - 力量训练", ["健康", "健身"]),
            ("entertainment", "观看 AI 纪录片", ["AI", "纪录片"]),
        ])
    ]
}

LLM_SUMMARY = {
    "timeline_md": "## 时间线\n- 08:30 晨会同步\n- 09:00 代码审查\n- 10:00 技术博客阅读\n- 11:00 编写数据管道\n- 12:30 午餐\n- 14:00 1:1 导师会议\n- 15:00 学习 Rust\n- 16:30 修复线上 Bug\n- 18:00 健身\n- 20:00 看纪录片",
    "progress_md": "## 事项进展\n### Q2 OKR\n- 晨会同步了进展，数据分析需求明确\n### 推荐系统\n- Review 了协同过滤 PR\n### 数据工程\n- 完成了 ETL 数据清洗模块\n### 搜索服务\n- 修复了内存泄漏 Bug",
    "knowledge_md": "## 新知识\n- 向量数据库：Pinecone vs Milvus 对比，Pinecone 更适合小规模快速上手\n- Rust 所有权机制：借用规则保证内存安全\n- 协同过滤算法在推荐系统中的应用",
    "time_distribution": {"work": 45, "study": 20, "life": 20, "entertainment": 15},
}

LLM_GRAPH = {
    "nodes": [
        {"name": "Q2 OKR", "type": "project"},
        {"name": "推荐系统", "type": "project"},
        {"name": "Rust", "type": "tool"},
        {"name": "协同过滤", "type": "concept"},
        {"name": "向量数据库", "type": "concept"},
        {"name": "ETL", "type": "concept"},
    ],
    "edges": [
        {"source": "推荐系统", "target": "协同过滤", "relation": "uses"},
        {"source": "Q2 OKR", "target": "推荐系统", "relation": "related_to"},
    ],
}

LLM_PLAN = {
    "items": [
        {"title": "继续 ETL 管道开发", "priority": "high", "reason": "昨日完成了清洗模块，需要继续加载模块"},
        {"title": "跟进推荐算法 PR 合并", "priority": "medium", "reason": "已完成 review"},
        {"title": "继续 Rust 练习", "priority": "low", "reason": "保持学习节奏"},
    ],
    "suggestions": [
        {"type": "attention", "content": "工作占比 45%，学习仅 20%，建议明日留 2h 深度学习时间"},
        {"type": "review", "content": "Rust 连续学习第 2 天，建议完成所有权章节后做一次练习总结"},
    ],
}


class TestFullPipeline:
    """E2E: manual data → analysis → summary → graph → plan"""

    @patch("app.services.llm_service.LLMService.complete_json", new_callable=AsyncMock)
    async def test_complete_journey(self, mock_llm, client):
        # ── Step 1: Load manual data (AC-1) ──
        entries = [
            {"timestamp": "2026-04-03T08:30:00", "title": "晨会同步", "content": "同步 OKR 和推荐系统进展", "duration_minutes": 30},
            {"timestamp": "2026-04-03T10:00:00", "title": "ETL 数据管道开发", "content": "实现清洗和加载逻辑", "duration_minutes": 120},
            {"timestamp": "2026-04-03T15:00:00", "title": "Rust 学习", "content": "练习所有权和借用", "duration_minutes": 90},
            {"timestamp": "2026-04-03T18:00:00", "title": "健身", "content": "力量训练", "duration_minutes": 60},
        ]
        resp = await client.post("/api/ingest/manual", json={"entries": entries})
        assert resp.status_code == 200
        total_imported = resp.json()["imported_count"]
        assert total_imported > 0

        target_date = "2026-04-03"
        events_resp = await client.get("/api/events", params={"date": target_date})
        assert events_resp.status_code == 200
        event_count = events_resp.json()["total"]
        assert event_count > 0

        # ── Step 2: Run analysis (AC-2) ──
        mock_llm.return_value = LLM_ANALYSIS
        analysis_resp = await client.post("/api/analysis/run", json={"date": target_date})
        assert analysis_resp.status_code == 200
        assert analysis_resp.json()["analyzed_count"] > 0

        events_after = await client.get("/api/events", params={"date": target_date})
        first_event = events_after.json()["items"][0]
        assert first_event["analysis"] is not None
        assert first_event["analysis"]["category"] in ("work", "study", "life", "entertainment")
        assert len(first_event["analysis"]["intent"]) > 0

        # ── Step 3: Generate summary (AC-3) ──
        # generate_summary calls LLM twice: once for summary, once for graph extraction
        mock_llm.side_effect = [LLM_SUMMARY, LLM_GRAPH]
        summary_resp = await client.post("/api/summary/generate", json={"date": target_date})
        assert summary_resp.status_code == 200
        summary = summary_resp.json()
        assert summary["date"] == target_date
        assert "时间线" in summary["timeline_md"]
        assert "事项进展" in summary["progress_md"]
        assert "新知识" in summary["knowledge_md"]
        assert sum(summary["time_distribution"].values()) == 100

        get_summary = await client.get(f"/api/summary/{target_date}")
        assert get_summary.status_code == 200
        assert get_summary.json()["date"] == target_date

        # ── Step 4: Check knowledge graph (AC-4) ──
        mock_llm.side_effect = None
        mock_llm.return_value = LLM_GRAPH
        rebuild_resp = await client.post("/api/knowledge/rebuild")
        assert rebuild_resp.status_code == 200

        graph_resp = await client.get("/api/knowledge/graph")
        assert graph_resp.status_code == 200
        graph = graph_resp.json()
        assert len(graph["nodes"]) >= 1
        assert all(n["type"] in ("project", "person", "concept", "tool", "topic") for n in graph["nodes"])

        if graph["nodes"]:
            node_id = graph["nodes"][0]["id"]
            detail_resp = await client.get(f"/api/knowledge/node/{node_id}")
            assert detail_resp.status_code == 200
            assert "node" in detail_resp.json()

        # ── Step 5: Generate plan (AC-5) ──
        mock_llm.side_effect = None
        mock_llm.return_value = LLM_PLAN
        plan_resp = await client.post("/api/plan/generate", json={"date": target_date})
        assert plan_resp.status_code == 200
        plan = plan_resp.json()
        assert len(plan["items"]) >= 1
        assert all(p["priority"] in ("high", "medium", "low") for p in plan["items"])
        assert len(plan["suggestions"]) >= 1

        plan_id = plan["id"]
        edit_resp = await client.put(f"/api/plan/{plan_id}", json={
            "items": [{"title": "用户修改的计划", "priority": "high", "reason": "自定义"}],
        })
        assert edit_resp.status_code == 200
        assert edit_resp.json()["items"][0]["title"] == "用户修改的计划"


class TestManualInputPipeline:
    """E2E: manual input → analysis → summary"""

    @patch("app.services.llm_service.LLMService.complete_json", new_callable=AsyncMock)
    async def test_manual_to_summary(self, mock_llm, client):
        entries = [
            {"timestamp": "2026-04-03T09:00:00", "title": "写周报", "content": "总结本周工作", "duration_minutes": 30},
            {"timestamp": "2026-04-03T10:00:00", "title": "读论文", "content": "BERT 论文精读", "duration_minutes": 90},
            {"timestamp": "2026-04-03T12:00:00", "title": "午饭", "content": "食堂", "duration_minutes": 40},
        ]
        ingest_resp = await client.post("/api/ingest/manual", json={"entries": entries})
        assert ingest_resp.json()["imported_count"] == 3

        mock_llm.return_value = {
            "events": [
                {"event_index": 0, "category": "work", "intent": "工作汇报", "tags": ["周报"], "confidence": 0.9},
                {"event_index": 1, "category": "study", "intent": "论文学习", "tags": ["NLP", "BERT"], "confidence": 0.95},
                {"event_index": 2, "category": "life", "intent": "午餐", "tags": ["健康"], "confidence": 0.85},
            ]
        }
        await client.post("/api/analysis/run", json={"date": "2026-04-03"})

        mock_llm.return_value = {
            "timeline_md": "## 时间线\n- 09:00 写周报\n- 10:00 读 BERT 论文\n- 12:00 午饭",
            "progress_md": "## 事项进展\n### 周报\n- 完成本周工作总结",
            "knowledge_md": "## 新知识\n- BERT: 双向 Transformer 预训练模型",
            "time_distribution": {"work": 20, "study": 55, "life": 25},
        }
        summary = await client.post("/api/summary/generate", json={"date": "2026-04-03"})
        assert summary.status_code == 200
        assert "BERT" in summary.json()["knowledge_md"]


class TestChromeUploadPipeline:
    """E2E: Chrome history upload → query events"""

    async def test_chrome_upload_and_query(self, client):
        import json, io
        chrome_data = [
            {"url": "https://docs.python.org", "title": "Python Docs", "visit_time": "2026-04-02T14:00:00", "visit_duration_seconds": 1800},
            {"url": "https://react.dev", "title": "React Docs", "visit_time": "2026-04-02T15:00:00", "visit_duration_seconds": 2400},
        ]
        file_content = json.dumps(chrome_data).encode()
        resp = await client.post(
            "/api/ingest/chrome",
            files={"file": ("history.json", io.BytesIO(file_content), "application/json")},
        )
        assert resp.status_code == 200
        assert resp.json()["imported_count"] == 2

        events = await client.get("/api/events", params={"date": "2026-04-02", "aggregate_browser": False})
        assert events.json()["total"] == 2
        urls = [e["url"] for e in events.json()["items"]]
        assert "https://docs.python.org" in urls
