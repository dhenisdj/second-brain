import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, patch

from app.database import get_session_factory
from app.models.event import Event
from app.services import job_service
from app.services.job_executor import schedule_job


async def _wait_for_job(client, job_id: str, attempts: int = 20):
    for _ in range(attempts):
        resp = await client.get(f"/api/jobs/{job_id}")
        assert resp.status_code == 200
        data = resp.json()
        if data["status"] in {"completed", "failed"}:
            return data
        await asyncio.sleep(0.05)
    raise AssertionError(f"Job {job_id} did not finish in time")


class TestBackgroundJobs:
    @patch("app.services.job_executor.graph_service.refresh_graph_for_date", new_callable=AsyncMock)
    @patch("app.services.job_executor.summary_service.generate_summary", new_callable=AsyncMock)
    @patch("app.services.job_executor.analysis_service.run_analysis", new_callable=AsyncMock)
    async def test_summary_async_job_persists_and_completes(
        self,
        mock_run_analysis,
        mock_generate_summary,
        mock_refresh_graph,
        client,
    ):
        mock_run_analysis.return_value = {"analyzed_count": 3, "categories": {"work": 3}}
        mock_generate_summary.return_value = {
            "id": "summary-1",
            "date": "2026-04-03",
            "timeline_md": "## 时间线",
            "progress_md": "## 进展",
            "knowledge_md": "## 知识",
            "time_distribution": {"work": 100},
        }
        mock_refresh_graph.return_value = {"date": "2026-04-03", "summary_id": "summary-1", "event_count": 3}

        start_resp = await client.post("/api/summary/generate-async", json={"date": "2026-04-03"})
        assert start_resp.status_code == 202
        job = start_resp.json()

        assert job["job_type"] == "summary.generate"
        assert job["status"] in {"pending", "running"}
        assert job["payload"]["date"] == "2026-04-03"

        finished = await _wait_for_job(client, job["id"])
        assert finished["status"] == "completed"
        assert finished["result"]["id"] == "summary-1"
        assert finished["result"]["analysis"]["analyzed_count"] == 3
        assert finished["result"]["graph_job_id"]
        mock_run_analysis.assert_awaited_once()

        status_resp = await client.get("/api/summary/status/2026-04-03")
        assert status_resp.status_code == 200
        assert status_resp.json()["id"] == job["id"]

    @patch("app.services.job_executor.plan_service.generate_plan", new_callable=AsyncMock)
    async def test_plan_async_job_completes(self, mock_generate_plan, client):
        mock_generate_plan.return_value = {
            "id": "plan-1",
            "date": "2026-04-04",
            "items": [{"title": "跟进", "priority": "high", "reason": "重要"}],
            "suggestions": [],
        }

        start_resp = await client.post("/api/plan/generate-async", json={"date": "2026-04-03"})
        assert start_resp.status_code == 202

        finished = await _wait_for_job(client, start_resp.json()["id"])
        assert finished["status"] == "completed"
        assert finished["result"]["id"] == "plan-1"

    @patch("app.services.job_executor.graph_service.rebuild_graph", new_callable=AsyncMock)
    async def test_graph_rebuild_async_job_completes(self, mock_rebuild_graph, client):
        mock_rebuild_graph.return_value = {
            "cleared": {"nodes": 1, "edges": 2, "evidences": 3},
            "rebuilt_dates": ["2026-04-03"],
            "graph_counts": {"nodes": 4, "edges": 2, "evidences": 6},
        }

        start_resp = await client.post("/api/knowledge/rebuild-async")
        assert start_resp.status_code == 202

        finished = await _wait_for_job(client, start_resp.json()["id"])
        assert finished["status"] == "completed"
        assert finished["result"]["graph_counts"]["nodes"] == 4

        list_resp = await client.get("/api/jobs?limit=5")
        assert list_resp.status_code == 200
        assert len(list_resp.json()["items"]) >= 1

    @patch("app.services.job_executor.graph_service.refresh_graph_for_date", new_callable=AsyncMock)
    @patch("app.services.job_executor.plan_service.generate_plan", new_callable=AsyncMock)
    @patch("app.services.job_executor.summary_service.generate_summary", new_callable=AsyncMock)
    @patch("app.services.job_executor.analysis_service.run_analysis", new_callable=AsyncMock)
    @patch("app.services.job_executor.ingest_configured_sources", new_callable=AsyncMock)
    async def test_daily_pipeline_collects_summarizes_and_plans(
        self,
        mock_collect,
        mock_run_analysis,
        mock_generate_summary,
        mock_generate_plan,
        mock_refresh_graph,
        client,
    ):
        mock_collect.return_value = {
            "imported_count": 2,
            "skipped_count": 1,
            "date_range": ["2026-04-03", "2026-04-03"],
            "source_results": [],
            "warnings": [],
        }
        mock_run_analysis.return_value = {"analyzed_count": 2, "categories": {"work": 2}}
        mock_generate_summary.return_value = {
            "id": "summary-1",
            "date": "2026-04-03",
            "timeline_md": "## 时间线",
            "progress_md": "## 进展",
            "knowledge_md": "## 知识",
            "time_distribution": {"work": 100},
        }
        mock_generate_plan.return_value = {
            "id": "plan-1",
            "date": "2026-04-04",
            "items": [{"title": "跟进", "priority": "high", "reason": "重要"}],
            "suggestions": [],
        }
        mock_refresh_graph.return_value = {"date": "2026-04-03", "summary_id": "summary-1", "event_count": 2}

        session_factory = get_session_factory()
        async with session_factory() as db:
            db.add(Event(
                source="manual",
                timestamp=datetime.fromisoformat("2026-04-03T09:00:00"),
                title="晨会",
                content="同步当天工作",
            ))
            await db.commit()
            job, _ = await job_service.enqueue_job(
                db,
                job_type=job_service.JOB_TYPE_DAILY_PIPELINE,
                payload={"date": "2026-04-03", "collect_days": 2},
                resource_key=job_service.daily_pipeline_resource_key("2026-04-03"),
            )

        schedule_job(job["id"])
        finished = await _wait_for_job(client, job["id"])

        assert finished["status"] == "completed"
        assert finished["result"]["collection"]["imported_count"] == 2
        assert finished["result"]["summary"]["id"] == "summary-1"
        assert finished["result"]["summary"]["analysis"]["analyzed_count"] == 2
        assert finished["result"]["plan"]["id"] == "plan-1"
        collect_req = mock_collect.await_args.args[0]
        assert collect_req.target_date == "2026-04-03"

    @patch("app.services.job_executor.graph_service.refresh_graph_for_date", new_callable=AsyncMock)
    @patch("app.services.job_executor.plan_service.generate_plan", new_callable=AsyncMock)
    @patch("app.services.job_executor.summary_service.generate_summary", new_callable=AsyncMock)
    @patch("app.services.job_executor.analysis_service.run_analysis", new_callable=AsyncMock)
    @patch("app.services.job_executor.ingest_configured_sources", new_callable=AsyncMock)
    async def test_day_refresh_collects_and_summarizes_without_planning(
        self,
        mock_collect,
        mock_run_analysis,
        mock_generate_summary,
        mock_generate_plan,
        mock_refresh_graph,
        client,
    ):
        mock_collect.return_value = {
            "imported_count": 1,
            "skipped_count": 0,
            "date_range": ["2026-04-03", "2026-04-03"],
            "source_results": [],
            "warnings": [],
        }
        mock_run_analysis.return_value = {"analyzed_count": 1, "categories": {"work": 1}}
        mock_generate_summary.return_value = {
            "id": "summary-1",
            "date": "2026-04-03",
            "timeline_md": "## 时间线",
            "progress_md": "## 进展",
            "knowledge_md": "## 知识",
            "time_distribution": {"work": 100},
        }
        mock_refresh_graph.return_value = {"date": "2026-04-03", "summary_id": "summary-1", "event_count": 1}

        session_factory = get_session_factory()
        async with session_factory() as db:
            db.add(Event(
                source="manual",
                timestamp=datetime.fromisoformat("2026-04-03T10:00:00"),
                title="开发",
                content="刷新当天总结",
            ))
            await db.commit()
            job, _ = await job_service.enqueue_job(
                db,
                job_type=job_service.JOB_TYPE_DAY_REFRESH,
                payload={"date": "2026-04-03", "collect_days": 1, "bucket": "1200"},
                resource_key=job_service.day_refresh_resource_key("2026-04-03", "1200"),
            )

        schedule_job(job["id"])
        finished = await _wait_for_job(client, job["id"])

        assert finished["status"] == "completed"
        assert finished["result"]["summary"]["id"] == "summary-1"
        assert "plan" not in finished["result"]
        mock_generate_plan.assert_not_awaited()
        collect_req = mock_collect.await_args.args[0]
        assert collect_req.target_date == "2026-04-03"
