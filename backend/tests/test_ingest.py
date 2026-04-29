"""AC-1: 数据采集 — 多模式数据输入"""

import json
import io
from datetime import datetime
import pytest
from conftest import SAMPLE_MANUAL_ENTRIES, SAMPLE_CHROME_HISTORY
from app.models.event import Event
from app.models.analysis import Analysis
from app.services.chrome_devtools_collector import ChromeDevtoolsUnavailable
from app.services.gcal_collector import GoogleApiNotEnabledError
from app.services.ingest_service import get_events_by_date


class TestManualIngest:
    """AC-1(c): 手动输入活动记录"""

    async def test_manual_ingest_success(self, client):
        resp = await client.post("/api/ingest/manual", json={"entries": SAMPLE_MANUAL_ENTRIES})
        assert resp.status_code == 200
        data = resp.json()
        assert data["imported_count"] == 3

    async def test_manual_ingest_empty_entries(self, client):
        resp = await client.post("/api/ingest/manual", json={"entries": []})
        assert resp.status_code == 200
        assert resp.json()["imported_count"] == 0

    async def test_manual_ingest_missing_required_fields(self, client):
        resp = await client.post("/api/ingest/manual", json={
            "entries": [{"content": "只有内容，缺 timestamp 和 title"}]
        })
        assert resp.status_code == 422

    async def test_manual_ingest_persists_to_db(self, client):
        await client.post("/api/ingest/manual", json={"entries": SAMPLE_MANUAL_ENTRIES})
        resp = await client.get("/api/events", params={"date": "2026-04-03"})
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 3
        assert items[0]["source"] == "manual"

    async def test_manual_ingest_stores_duration(self, client):
        await client.post("/api/ingest/manual", json={"entries": SAMPLE_MANUAL_ENTRIES})
        resp = await client.get("/api/events", params={"date": "2026-04-03"})
        durations = [e["duration_minutes"] for e in resp.json()["items"]]
        assert 30 in durations
        assert 60 in durations


class TestChromeIngest:
    """AC-1(b): 上传 Chrome 浏览历史 JSON 文件"""

    async def test_chrome_upload_json(self, client):
        file_content = json.dumps(SAMPLE_CHROME_HISTORY).encode()
        resp = await client.post(
            "/api/ingest/chrome",
            files={"file": ("history.json", io.BytesIO(file_content), "application/json")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["imported_count"] == 2
        assert "date_range" in data

    async def test_chrome_upload_invalid_format(self, client):
        resp = await client.post(
            "/api/ingest/chrome",
            files={"file": ("bad.json", io.BytesIO(b"not json"), "application/json")},
        )
        assert resp.status_code == 400

    async def test_chrome_events_have_url(self, client):
        file_content = json.dumps(SAMPLE_CHROME_HISTORY).encode()
        await client.post(
            "/api/ingest/chrome",
            files={"file": ("history.json", io.BytesIO(file_content), "application/json")},
        )
        resp = await client.get("/api/events", params={"date": "2026-04-03", "source": "chrome"})
        urls = [e["url"] for e in resp.json()["items"] if e.get("url")]
        assert len(urls) >= 1
        assert any("arxiv.org" in u for u in urls)

    async def test_chrome_reimport_skips_duplicates(self, client):
        file_content = json.dumps(SAMPLE_CHROME_HISTORY).encode()
        await client.post(
            "/api/ingest/chrome",
            files={"file": ("history.json", io.BytesIO(file_content), "application/json")},
        )
        resp = await client.post(
            "/api/ingest/chrome",
            files={"file": ("history.json", io.BytesIO(file_content), "application/json")},
        )
        assert resp.status_code == 200
        assert resp.json()["imported_count"] == 0
        assert resp.json()["skipped_count"] == 2

    async def test_browser_local_defaults_to_two_days(self, client, monkeypatch):
        captured = {}

        def fake_collect_browser_history(days):
            captured["days"] = days
            return {"events": [], "date_range": [], "collected_sources": ["chrome"], "warnings": []}

        monkeypatch.setattr("app.routers.ingest.collect_browser_history", fake_collect_browser_history)

        resp = await client.post("/api/ingest/browser-local", json={})

        assert resp.status_code == 200
        assert captured["days"] == 2
        assert resp.json()["collected_sources"] == ["chrome"]

    async def test_chrome_devtools_ingests_rendered_tabs(self, client, monkeypatch):
        captured = {}

        def fake_collect_chrome_rendered_tabs(host, port, days):
            captured["host"] = host
            captured["port"] = port
            captured["days"] = days
            return {
                "events": [
                    {
                        "source": "chrome",
                        "visit_time": "2026-04-28T10:15:00+08:00",
                        "title": "内网项目页",
                        "url": "https://corp.example.com/project/MB-123",
                        "content": "主内容：需求评审、上线计划、风险项",
                        "capture_method": "chrome_devtools",
                    }
                ],
                "date_range": ["2026-04-28", "2026-04-28"],
                "collected_sources": ["chrome"],
                "source_breakdown": {"chrome": 1},
                "warnings": [],
            }

        monkeypatch.setattr("app.routers.ingest.collect_chrome_rendered_tabs", fake_collect_chrome_rendered_tabs)

        resp = await client.post("/api/ingest/chrome-devtools", json={})

        assert resp.status_code == 200
        data = resp.json()
        assert data["imported_count"] == 1
        assert captured == {"host": "127.0.0.1", "port": 9222, "days": 2}

        events_resp = await client.get("/api/events", params={"date": "2026-04-28", "source": "chrome"})
        items = events_resp.json()["items"]
        assert items[0]["title"] == "内网项目页"
        assert "上线计划" in items[0]["content"]

    async def test_chrome_devtools_returns_bad_request_when_unavailable(self, client, monkeypatch):
        def fake_collect_chrome_rendered_tabs(_host, _port, _days):
            raise ChromeDevtoolsUnavailable("无法连接 Chrome DevTools")

        monkeypatch.setattr("app.routers.ingest.collect_chrome_rendered_tabs", fake_collect_chrome_rendered_tabs)

        resp = await client.post("/api/ingest/chrome-devtools", json={})

        assert resp.status_code == 400
        assert "DevTools" in resp.json()["detail"]

    async def test_chrome_devtools_history_ingests_rendered_history_pages(self, client, monkeypatch):
        captured = {}

        def fake_collect_chrome_mcp_history_rendered_pages(days, max_pages, offset, domains, intranet_only):
            captured.update({
                "days": days,
                "max_pages": max_pages,
                "offset": offset,
                "domains": domains,
                "intranet_only": intranet_only,
            })
            return {
                "events": [
                    {
                        "source": "chrome",
                        "visit_time": "2026-04-28T10:15:00",
                        "title": "SWP Kafka Approval",
                        "url": "https://space.shopee.io/utility/swp/detail/9280780",
                        "content": "页面字段：Project: chatbot_data | Topic name: fact_queue",
                        "capture_method": "chrome_devtools_history",
                    }
                ],
                "date_range": ["2026-04-28", "2026-04-28"],
                "collected_sources": ["chrome"],
                "source_breakdown": {"chrome": 1},
                "warnings": [],
                "candidate_count": 3,
                "captured_count": 1,
                "offset": offset,
                "batch_size": max_pages,
                "next_offset": offset + 3,
                "has_more": False,
            }

        monkeypatch.setattr(
            "app.routers.ingest.collect_chrome_mcp_history_rendered_pages",
            fake_collect_chrome_mcp_history_rendered_pages,
        )

        resp = await client.post("/api/ingest/chrome-devtools-history", json={"max_pages": 25})

        assert resp.status_code == 200
        data = resp.json()
        assert data["imported_count"] == 1
        assert data["candidate_count"] == 3
        assert data["captured_count"] == 1
        assert data["next_offset"] == 3
        assert data["has_more"] is False
        assert captured == {
            "days": 2,
            "max_pages": 25,
            "offset": 0,
            "domains": None,
            "intranet_only": True,
        }

    async def test_chrome_devtools_history_updates_existing_browser_content(self, client, monkeypatch):
        seed = [
            {
                "visit_time": "2026-04-28T10:15:00",
                "title": "Old title",
                "url": "https://space.shopee.io/utility/swp/detail/9280780",
                "content": "页面线索：space.shopee.io",
            }
        ]
        await client.post(
            "/api/ingest/chrome",
            files={"file": ("history.json", io.BytesIO(json.dumps(seed).encode()), "application/json")},
        )

        def fake_collect_chrome_mcp_history_rendered_pages(*_args, **_kwargs):
            return {
                "events": [
                    {
                        "source": "chrome",
                        "visit_time": "2026-04-28T10:15:00",
                        "title": "Rendered SWP Detail",
                        "url": "https://space.shopee.io/utility/swp/detail/9280780",
                        "content": "页面字段：Project: chatbot_data | Topic name: fact_queue | Kafka SRE Approval",
                        "capture_method": "chrome_devtools_history",
                    }
                ],
                "date_range": ["2026-04-28", "2026-04-28"],
                "collected_sources": ["chrome"],
                "source_breakdown": {"chrome": 1},
                "warnings": [],
                "candidate_count": 1,
                "captured_count": 1,
            }

        monkeypatch.setattr(
            "app.routers.ingest.collect_chrome_mcp_history_rendered_pages",
            fake_collect_chrome_mcp_history_rendered_pages,
        )

        resp = await client.post("/api/ingest/chrome-devtools-history", json={})

        assert resp.status_code == 200
        assert resp.json()["imported_count"] == 0
        assert resp.json()["updated_count"] == 1
        events_resp = await client.get("/api/events", params={"date": "2026-04-28", "source": "chrome"})
        item = events_resp.json()["items"][0]
        assert item["title"] == "Rendered SWP Detail"
        assert "Kafka SRE Approval" in item["content"]


class TestGCalIngest:
    async def test_gcal_defaults_to_two_days(self, client, monkeypatch):
        captured = {}

        async def fake_get_all_settings(_db):
            return {"google_user_email": "tester@example.com"}

        def fake_collect_gcal_events(user_email, days):
            assert user_email == "tester@example.com"
            captured["days"] = days
            return {"events": [], "date_range": []}

        monkeypatch.setattr("app.routers.settings._get_all_settings", fake_get_all_settings)
        monkeypatch.setattr("app.routers.ingest.collect_gcal_events", fake_collect_gcal_events)

        resp = await client.post("/api/ingest/gcal", json={})

        assert resp.status_code == 200
        assert resp.json() == {"imported_count": 0, "date_range": []}
        assert captured["days"] == 2

    async def test_collect_configured_sources_aggregates_enabled_sources(self, client, monkeypatch):
        async def fake_get_all_settings(_db):
            return {
                "chrome_history_enabled": True,
                "safari_history_enabled": False,
                "google_calendar_enabled": True,
                "google_user_email": "tester@example.com",
            }

        def fake_collect_chrome_history(days):
            assert days == 2
            return {
                "events": [
                    {
                        "source": "chrome",
                        "visit_time": "2026-04-03T09:15:00",
                        "title": "Python 文档",
                        "url": "https://docs.python.org/3/",
                    }
                ],
                "date_range": ["2026-04-03", "2026-04-03"],
            }

        def fake_collect_gcal_events(user_email, days):
            assert user_email == "tester@example.com"
            assert days == 2
            return {
                "events": [
                    {
                        "timestamp": "2026-04-03T10:00:00",
                        "title": "项目例会",
                        "content": "同步进展",
                        "duration_minutes": 30,
                    }
                ],
                "date_range": ["2026-04-03", "2026-04-03"],
            }

        monkeypatch.setattr("app.routers.settings._get_all_settings", fake_get_all_settings)
        monkeypatch.setattr("app.routers.ingest.collect_chrome_history", fake_collect_chrome_history)
        monkeypatch.setattr("app.routers.ingest.collect_gcal_events", fake_collect_gcal_events)
        monkeypatch.setattr("app.routers.ingest.has_google_client_credentials", lambda: True)
        monkeypatch.setattr("app.routers.ingest.has_google_calendar_authorized_token", lambda: True)

        resp = await client.post("/api/ingest/collect", json={})

        assert resp.status_code == 200
        data = resp.json()
        assert data["imported_count"] == 2
        assert data["date_range"] == ["2026-04-03", "2026-04-03"]
        chrome_result = next(item for item in data["source_results"] if item["source"] == "chrome")
        safari_result = next(item for item in data["source_results"] if item["source"] == "safari")
        gcal_result = next(item for item in data["source_results"] if item["source"] == "gcal")
        assert chrome_result["status"] == "success"
        assert chrome_result["imported_count"] == 1
        assert safari_result["status"] == "disabled"
        assert gcal_result["status"] == "success"
        assert gcal_result["imported_count"] == 1

    async def test_collect_configured_sources_requires_enabled_source(self, client, monkeypatch):
        async def fake_get_all_settings(_db):
            return {
                "chrome_history_enabled": False,
                "safari_history_enabled": False,
                "google_calendar_enabled": False,
                "git_activity_enabled": False,
                "google_user_email": "",
            }

        monkeypatch.setattr("app.routers.settings._get_all_settings", fake_get_all_settings)

        resp = await client.post("/api/ingest/collect", json={})

        assert resp.status_code == 400
        assert resp.json()["detail"] == "请先在配置页启用至少一个数据源"

    async def test_collect_configured_sources_marks_misconfigured_gcal(self, client, monkeypatch):
        async def fake_get_all_settings(_db):
            return {
                "chrome_history_enabled": True,
                "safari_history_enabled": False,
                "google_calendar_enabled": True,
                "google_user_email": "",
            }

        def fake_collect_chrome_history(days):
            assert days == 2
            return {
                "events": [],
                "date_range": [],
            }

        monkeypatch.setattr("app.routers.settings._get_all_settings", fake_get_all_settings)
        monkeypatch.setattr("app.routers.ingest.collect_chrome_history", fake_collect_chrome_history)

        resp = await client.post("/api/ingest/collect", json={})

        assert resp.status_code == 200
        data = resp.json()
        chrome_result = next(item for item in data["source_results"] if item["source"] == "chrome")
        assert chrome_result["status"] == "success"
        gcal_result = next(item for item in data["source_results"] if item["source"] == "gcal")
        assert gcal_result["status"] == "misconfigured"
        assert "Google 邮箱地址" in gcal_result["message"]
        assert any("Google 日历" in warning for warning in data["warnings"])

    async def test_collect_configured_sources_marks_misconfigured_gcal_without_authorization(self, client, monkeypatch):
        async def fake_get_all_settings(_db):
            return {
                "chrome_history_enabled": False,
                "safari_history_enabled": False,
                "google_calendar_enabled": True,
                "google_user_email": "tester@example.com",
            }

        monkeypatch.setattr("app.routers.settings._get_all_settings", fake_get_all_settings)
        monkeypatch.setattr("app.routers.ingest.has_google_client_credentials", lambda: True)
        monkeypatch.setattr("app.routers.ingest.has_google_calendar_authorized_token", lambda: False)

        resp = await client.post("/api/ingest/collect", json={})

        assert resp.status_code == 200
        data = resp.json()
        gcal_result = next(item for item in data["source_results"] if item["source"] == "gcal")
        assert gcal_result["status"] == "misconfigured"
        assert "授权" in gcal_result["message"]
        assert any("Google 日历" in warning for warning in data["warnings"])

    async def test_collect_configured_sources_supports_safari_only(self, client, monkeypatch):
        async def fake_get_all_settings(_db):
            return {
                "chrome_history_enabled": False,
                "safari_history_enabled": True,
                "google_calendar_enabled": False,
                "google_user_email": "",
            }

        def fake_collect_safari_history(days):
            assert days == 2
            return {
                "events": [
                    {
                        "source": "safari",
                        "visit_time": "2026-04-03T09:30:00",
                        "title": "Apple Docs",
                        "url": "https://developer.apple.com/documentation",
                    }
                ],
                "date_range": ["2026-04-03", "2026-04-03"],
            }

        monkeypatch.setattr("app.routers.settings._get_all_settings", fake_get_all_settings)
        monkeypatch.setattr("app.routers.ingest.collect_safari_history", fake_collect_safari_history)

        resp = await client.post("/api/ingest/collect", json={})

        assert resp.status_code == 200
        data = resp.json()
        chrome_result = next(item for item in data["source_results"] if item["source"] == "chrome")
        safari_result = next(item for item in data["source_results"] if item["source"] == "safari")
        assert chrome_result["status"] == "disabled"
        assert safari_result["status"] == "success"
        assert safari_result["imported_count"] == 1

    async def test_collect_configured_sources_supports_git_only(self, client, monkeypatch):
        async def fake_get_all_settings(_db):
            return {
                "chrome_history_enabled": False,
                "safari_history_enabled": False,
                "google_calendar_enabled": False,
                "git_activity_enabled": True,
                "git_repo_paths": "/tmp/project-a",
                "git_author_filter": "tester@example.com",
                "google_user_email": "",
            }

        def fake_collect_git_activity(repo_paths, days, author_filter=None):
            assert repo_paths == ["/tmp/project-a"]
            assert days == 2
            assert author_filter == "tester@example.com"
            return {
                "events": [
                    {
                        "source": "git",
                        "timestamp": "2026-04-03T11:20:00",
                        "title": "project-a: add git source",
                        "content": "commit abc12345 | author Tester <tester@example.com>",
                        "url": "https://git.example.com/team/project-a/-/commit/abc12345",
                        "commit_hash": "abc12345",
                        "repo_name": "project-a",
                        "repo_path": "/tmp/project-a",
                    }
                ],
                "date_range": ["2026-04-03", "2026-04-03"],
                "warnings": [],
                "repositories": [{"path": "/tmp/project-a", "status": "success", "count": 1}],
            }

        monkeypatch.setattr("app.routers.settings._get_all_settings", fake_get_all_settings)
        monkeypatch.setattr("app.routers.ingest.collect_git_activity", fake_collect_git_activity)

        resp = await client.post("/api/ingest/collect", json={})

        assert resp.status_code == 200
        data = resp.json()
        git_result = next(item for item in data["source_results"] if item["source"] == "git")
        assert git_result["status"] == "success"
        assert git_result["imported_count"] == 1
        assert data["date_range"] == ["2026-04-03", "2026-04-03"]

        events_resp = await client.get("/api/events", params={"date": "2026-04-03", "source": "git"})
        assert events_resp.status_code == 200
        assert events_resp.json()["items"][0]["source"] == "git"

    async def test_collect_configured_sources_marks_misconfigured_git_without_paths(self, client, monkeypatch):
        async def fake_get_all_settings(_db):
            return {
                "chrome_history_enabled": False,
                "safari_history_enabled": False,
                "google_calendar_enabled": False,
                "git_activity_enabled": True,
                "git_repo_paths": "",
                "git_author_filter": "",
                "google_user_email": "",
            }

        monkeypatch.setattr("app.routers.settings._get_all_settings", fake_get_all_settings)

        resp = await client.post("/api/ingest/collect", json={})

        assert resp.status_code == 200
        data = resp.json()
        git_result = next(item for item in data["source_results"] if item["source"] == "git")
        assert git_result["status"] == "misconfigured"
        assert "Git 仓库或工作区路径" in git_result["message"]

    async def test_gmail_defaults_to_two_days(self, client, monkeypatch):
        captured = {}

        async def fake_get_all_settings(_db):
            return {"google_user_email": "tester@example.com"}

        def fake_collect_gmail_messages(user_email, days, max_messages):
            assert user_email == "tester@example.com"
            captured["days"] = days
            captured["max_messages"] = max_messages
            return {"events": [], "date_range": []}

        monkeypatch.setattr("app.routers.settings._get_all_settings", fake_get_all_settings)
        monkeypatch.setattr("app.routers.ingest.collect_gmail_messages", fake_collect_gmail_messages)

        resp = await client.post("/api/ingest/gmail", json={})

        assert resp.status_code == 200
        assert resp.json() == {"imported_count": 0, "skipped_count": 0, "date_range": []}
        assert captured["days"] == 2
        assert captured["max_messages"] == 100

    async def test_collect_configured_sources_supports_gmail_only(self, client, monkeypatch):
        async def fake_get_all_settings(_db):
            return {
                "chrome_history_enabled": False,
                "safari_history_enabled": False,
                "google_calendar_enabled": False,
                "gmail_enabled": True,
                "git_activity_enabled": False,
                "google_user_email": "tester@example.com",
            }

        def fake_collect_gmail_messages(user_email, days, max_messages):
            assert user_email == "tester@example.com"
            assert days == 2
            assert max_messages == 100
            return {
                "events": [
                    {
                        "source": "gmail",
                        "timestamp": "2026-04-03T13:15:00",
                        "title": "Kafka approval",
                        "content": "发件人: alice@example.com\n正文:\nPlease review the Kafka request",
                        "url": "https://mail.google.com/mail/u/tester@example.com/#all/msg-1",
                        "message_id": "msg-1",
                    }
                ],
                "date_range": ["2026-04-03", "2026-04-03"],
            }

        monkeypatch.setattr("app.routers.settings._get_all_settings", fake_get_all_settings)
        monkeypatch.setattr("app.routers.ingest.has_google_client_credentials", lambda: True)
        monkeypatch.setattr("app.routers.ingest.has_google_gmail_authorized_token", lambda: True)
        monkeypatch.setattr("app.routers.ingest.collect_gmail_messages", fake_collect_gmail_messages)

        resp = await client.post("/api/ingest/collect", json={})

        assert resp.status_code == 200
        data = resp.json()
        gmail_result = next(item for item in data["source_results"] if item["source"] == "gmail")
        assert gmail_result["status"] == "success"
        assert gmail_result["imported_count"] == 1

        events_resp = await client.get("/api/events", params={"date": "2026-04-03", "source": "gmail"})
        assert events_resp.status_code == 200
        assert events_resp.json()["items"][0]["source"] == "gmail"

    async def test_collect_configured_sources_marks_misconfigured_gmail_without_authorization(self, client, monkeypatch):
        async def fake_get_all_settings(_db):
            return {
                "chrome_history_enabled": False,
                "safari_history_enabled": False,
                "google_calendar_enabled": False,
                "gmail_enabled": True,
                "git_activity_enabled": False,
                "google_user_email": "tester@example.com",
            }

        monkeypatch.setattr("app.routers.settings._get_all_settings", fake_get_all_settings)
        monkeypatch.setattr("app.routers.ingest.has_google_client_credentials", lambda: True)
        monkeypatch.setattr("app.routers.ingest.has_google_gmail_authorized_token", lambda: False)

        resp = await client.post("/api/ingest/collect", json={})

        assert resp.status_code == 200
        data = resp.json()
        gmail_result = next(item for item in data["source_results"] if item["source"] == "gmail")
        assert gmail_result["status"] == "misconfigured"
        assert "授权" in gmail_result["message"]

    async def test_gmail_api_disabled_returns_actionable_detail(self, client, monkeypatch):
        async def fake_get_all_settings(_db):
            return {"google_user_email": "tester@example.com"}

        def fake_collect_gmail_messages(_user_email, _days, _max_messages):
            raise GoogleApiNotEnabledError(
                api_slug="gmail.googleapis.com",
                api_label="Gmail API",
                project_id="208574075633",
            )

        monkeypatch.setattr("app.routers.settings._get_all_settings", fake_get_all_settings)
        monkeypatch.setattr("app.routers.ingest.collect_gmail_messages", fake_collect_gmail_messages)

        resp = await client.post("/api/ingest/gmail", json={})

        assert resp.status_code == 400
        detail = resp.json()["detail"]
        assert detail["code"] == "google_api_disabled"
        assert detail["action_label"] == "开启 Gmail API"
        assert "gmail.googleapis.com" in detail["action_url"]
        assert "project=208574075633" in detail["action_url"]

    async def test_collect_configured_sources_marks_gmail_api_disabled_as_actionable(self, client, monkeypatch):
        async def fake_get_all_settings(_db):
            return {
                "chrome_history_enabled": False,
                "safari_history_enabled": False,
                "google_calendar_enabled": False,
                "gmail_enabled": True,
                "git_activity_enabled": False,
                "google_user_email": "tester@example.com",
            }

        def fake_collect_gmail_messages(_user_email, _days, _max_messages):
            raise GoogleApiNotEnabledError(
                api_slug="gmail.googleapis.com",
                api_label="Gmail API",
                project_id="208574075633",
            )

        monkeypatch.setattr("app.routers.settings._get_all_settings", fake_get_all_settings)
        monkeypatch.setattr("app.routers.ingest.has_google_client_credentials", lambda: True)
        monkeypatch.setattr("app.routers.ingest.has_google_gmail_authorized_token", lambda: True)
        monkeypatch.setattr("app.routers.ingest.collect_gmail_messages", fake_collect_gmail_messages)

        resp = await client.post("/api/ingest/collect", json={})

        assert resp.status_code == 200
        gmail_result = next(item for item in resp.json()["source_results"] if item["source"] == "gmail")
        assert gmail_result["status"] == "misconfigured"
        assert gmail_result["code"] == "google_api_disabled"
        assert gmail_result["action_label"] == "开启 Gmail API"
        assert "project=208574075633" in gmail_result["action_url"]


class TestEventQuery:
    """事件查询接口"""

    async def test_query_events_by_date(self, client):
        await client.post("/api/ingest/manual", json={"entries": SAMPLE_MANUAL_ENTRIES})
        resp = await client.get("/api/events", params={"date": "2026-04-03"})
        assert resp.status_code == 200
        body = resp.json()
        assert "items" in body
        assert "total" in body
        assert body["total"] == 3

    async def test_query_events_empty_date(self, client):
        resp = await client.get("/api/events", params={"date": "2020-01-01"})
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    async def test_query_events_pagination(self, client):
        await client.post("/api/ingest/manual", json={"entries": SAMPLE_MANUAL_ENTRIES})
        resp = await client.get("/api/events", params={"date": "2026-04-03", "page": 1, "size": 2})
        assert resp.status_code == 200
        assert len(resp.json()["items"]) == 2

    async def test_query_events_invalid_date_format(self, client):
        resp = await client.get("/api/events", params={"date": "not-a-date"})
        assert resp.status_code == 422

    async def test_query_browser_source_returns_all_browser_events(self, db_session):
        db_session.add_all(
            [
                Event(
                    source="chrome",
                    timestamp=datetime.fromisoformat("2026-04-03T09:00:00"),
                    title="Chrome 文档",
                    url="https://docs.python.org",
                ),
                Event(
                    source="safari",
                    timestamp=datetime.fromisoformat("2026-04-03T09:30:00"),
                    title="Safari 文档",
                    url="https://developer.apple.com/documentation",
                ),
                Event(
                    source="manual",
                    timestamp=datetime.fromisoformat("2026-04-03T10:00:00"),
                    title="线下讨论",
                ),
            ]
        )
        await db_session.commit()

        result = await get_events_by_date(db_session, "2026-04-03", source="browser")

        assert result["total"] == 2
        assert {item["source"] for item in result["items"]} == {"chrome", "safari"}

    async def test_query_events_aggregates_multiple_browser_sources(self, db_session):
        db_session.add_all(
            [
                Event(
                    source="chrome",
                    timestamp=datetime.fromisoformat("2026-04-03T09:00:00"),
                    title="Chrome 文档",
                    url="https://docs.python.org/3/",
                ),
                Event(
                    source="safari",
                    timestamp=datetime.fromisoformat("2026-04-03T09:20:00"),
                    title="Safari 文档",
                    url="https://docs.python.org/3/tutorial/",
                ),
            ]
        )
        await db_session.commit()

        result = await get_events_by_date(db_session, "2026-04-03")

        assert result["total"] == 1
        assert result["items"][0]["source"] == "browser"
        assert result["items"][0]["visit_count"] == 2

    async def test_query_events_can_return_raw_browser_events(self, db_session):
        db_session.add_all(
            [
                Event(
                    source="chrome",
                    timestamp=datetime.fromisoformat("2026-04-03T09:00:00"),
                    title="Chrome 文档",
                    url="https://docs.python.org/3/",
                ),
                Event(
                    source="safari",
                    timestamp=datetime.fromisoformat("2026-04-03T09:20:00"),
                    title="Safari 文档",
                    url="https://docs.python.org/3/tutorial/",
                ),
            ]
        )
        await db_session.commit()

        result = await get_events_by_date(db_session, "2026-04-03", aggregate_browser=False)

        assert result["total"] == 2
        assert {item["source"] for item in result["items"]} == {"chrome", "safari"}

    async def test_query_events_uses_latest_analysis_when_duplicates_exist(self, db_session):
        event = Event(
            source="manual",
            timestamp=datetime.fromisoformat("2026-04-03T09:00:00"),
            title="团队站会",
            content="同步项目进展",
            duration_minutes=30,
        )
        db_session.add(event)
        await db_session.flush()

        db_session.add_all(
            [
                Analysis(
                    event_id=event.id,
                    category="work",
                    intent="旧标签",
                    tags='["old"]',
                    confidence=0.2,
                    created_at=datetime.fromisoformat("2026-04-03T09:01:00"),
                ),
                Analysis(
                    event_id=event.id,
                    category="work",
                    intent="最新标签",
                    tags='["new"]',
                    confidence=0.95,
                    created_at=datetime.fromisoformat("2026-04-03T09:02:00"),
                ),
            ]
        )
        await db_session.commit()

        result = await get_events_by_date(db_session, "2026-04-03", source="manual")

        assert result["total"] == 1
        assert result["items"][0]["analysis"]["intent"] == "最新标签"
