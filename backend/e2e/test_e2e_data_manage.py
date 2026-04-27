"""
E2E Scenario 3: Data Management — AC-7

Verifies data overview, single-event deletion, and full-day deletion.
"""

import pytest
from unittest.mock import AsyncMock, patch


class TestDataLifecycle:
    """E2E: ingest → overview → delete event → delete day"""

    @patch("app.services.llm_service.LLMService.complete_json", new_callable=AsyncMock)
    async def test_full_data_lifecycle(self, mock_llm, client):
        # ── Ingest data ──
        entries = [
            {"timestamp": "2026-04-03T09:00:00", "title": "Meeting", "duration_minutes": 30},
            {"timestamp": "2026-04-03T10:00:00", "title": "Coding", "duration_minutes": 120},
            {"timestamp": "2026-04-03T14:00:00", "title": "Reading", "duration_minutes": 60},
        ]
        await client.post("/api/ingest/manual", json={"entries": entries})

        # ── Run analysis ──
        mock_llm.return_value = {
            "events": [
                {"event_index": 0, "category": "work", "intent": "会议", "tags": ["工作"], "confidence": 0.9},
                {"event_index": 1, "category": "work", "intent": "编程", "tags": ["开发"], "confidence": 0.9},
                {"event_index": 2, "category": "study", "intent": "阅读", "tags": ["学习"], "confidence": 0.9},
            ]
        }
        await client.post("/api/analysis/run", json={"date": "2026-04-03"})

        # ── Check overview (AC-7) ──
        overview = await client.get("/api/data/overview", params={"start": "2026-04-01", "end": "2026-04-05"})
        assert overview.status_code == 200
        days = overview.json()["days"]
        day = next(d for d in days if d["date"] == "2026-04-03")
        assert day["event_count"] == 3
        assert day["has_analysis"] is True

        # ── Delete single event ──
        events = await client.get("/api/events", params={"date": "2026-04-03"})
        first_id = events.json()["items"][0]["id"]
        del_resp = await client.delete(f"/api/data/events/{first_id}")
        assert del_resp.status_code == 200

        events_after = await client.get("/api/events", params={"date": "2026-04-03"})
        assert events_after.json()["total"] == 2
        remaining_ids = [e["id"] for e in events_after.json()["items"]]
        assert first_id not in remaining_ids

        # ── Delete entire day ──
        del_day = await client.delete("/api/data/day/2026-04-03")
        assert del_day.status_code == 200
        deleted = del_day.json()["deleted"]
        assert deleted["events"] == 2
        assert deleted["analyses"] >= 1

        # ── Verify empty ──
        final = await client.get("/api/events", params={"date": "2026-04-03"})
        assert final.json()["total"] == 0

    async def test_delete_nonexistent_returns_404(self, client):
        resp = await client.delete("/api/data/events/nonexistent-id-12345")
        assert resp.status_code == 404

    async def test_delete_empty_day_returns_zero(self, client):
        resp = await client.delete("/api/data/day/2020-01-01")
        assert resp.status_code == 200
        assert resp.json()["deleted"]["events"] == 0
