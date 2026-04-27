import asyncio
from unittest.mock import AsyncMock, patch


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
    async def test_summary_async_job_persists_and_completes(self, mock_generate_summary, mock_refresh_graph, client):
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
        assert finished["result"]["graph_job_id"]

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
