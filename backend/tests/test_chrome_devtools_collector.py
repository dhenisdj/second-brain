from datetime import datetime, timezone

from app.services import chrome_devtools_collector


def test_collect_chrome_rendered_tabs_uses_history_time_and_sanitizes_url(monkeypatch):
    monkeypatch.setattr(
        chrome_devtools_collector,
        "_list_targets",
        lambda host, port: [
            {
                "type": "page",
                "url": "https://corp.example.com/app/item?id=MB-123&token=secret-value",
                "title": "Old title",
                "webSocketDebuggerUrl": "ws://devtools/page/1",
            }
        ],
    )
    monkeypatch.setattr(
        chrome_devtools_collector,
        "_evaluate_tab_snapshot",
        lambda _ws_url: {
            "url": "https://corp.example.com/app/item?id=MB-123&token=secret-value",
            "title": "Rendered title",
            "headings": ["Project Alpha", "Deploy checklist"],
            "meta_descriptions": ["Internal project page"],
            "main_text": "Reviewed deployment status and remaining validation tasks.",
            "table_text": "Owner | Status\nData team | Ready",
            "body_text": "Project Alpha Deploy checklist Reviewed deployment status and remaining validation tasks.",
            "visible_text_length": 96,
            "captured_at": "2026-04-28T12:00:00+00:00",
        },
    )
    monkeypatch.setattr(
        chrome_devtools_collector,
        "_latest_history_by_url",
        lambda _urls, _days: {
            "https://corp.example.com/app/item?id=MB-123": {
                "visit_time": datetime(2026, 4, 28, 10, 30, tzinfo=timezone.utc),
                "visit_duration_seconds": 480,
                "history_title": "History title",
            }
        },
    )

    result = chrome_devtools_collector.collect_chrome_rendered_tabs(days=2)

    assert result["total"] == 1
    event = result["events"][0]
    assert datetime.fromisoformat(event["visit_time"]).astimezone(timezone.utc) == datetime(
        2026, 4, 28, 10, 30, tzinfo=timezone.utc
    )
    assert event["title"] == "Rendered title"
    assert event["url"] == "https://corp.example.com/app/item?id=MB-123"
    assert event["visit_duration_seconds"] == 480
    assert event["capture_method"] == "chrome_devtools"
    assert "Project Alpha" in event["content"]
    assert "Owner | Status" in event["content"]
    assert "secret-value" not in event["url"]


def test_collect_chrome_rendered_tabs_returns_empty_when_no_pages(monkeypatch):
    monkeypatch.setattr(chrome_devtools_collector, "_list_targets", lambda host, port: [])

    result = chrome_devtools_collector.collect_chrome_rendered_tabs()

    assert result["total"] == 0
    assert result["events"] == []
    assert result["source_breakdown"] == {"chrome": 0}


def test_collect_chrome_history_rendered_pages_replays_intranet_history(monkeypatch):
    closed_targets = []
    navigated_urls = []

    monkeypatch.setattr(
        chrome_devtools_collector,
        "_history_candidates",
        lambda **_kwargs: [
            {
                "url": "https://space.shopee.io/utility/swp/detail/9280780",
                "title": "SWP-9280780",
                "visit_time": datetime(2026, 4, 28, 10, 30, tzinfo=timezone.utc),
                "visit_duration_seconds": 360,
            }
        ],
    )
    monkeypatch.setattr(
        chrome_devtools_collector,
        "_new_target",
        lambda _host, _port: {"id": "target-1", "webSocketDebuggerUrl": "ws://devtools/page/temp"},
    )

    def fake_navigate(_ws_url, url):
        navigated_urls.append(url)
        return {
            "url": url,
            "requested_url": url,
            "title": "Kafka SRE Approval",
            "headings": ["Apply Modify Kafka Topic Bandwidth Quota"],
            "field_text": "Project: chatbot_data\nTopic name: di.shopee_inhouse__fact_queue_tab",
            "table_text": "Current | Target\n1 MB/s | 10 MB/s",
            "body_text": "Kafka SRE Approval Project chatbot_data Topic name di.shopee_inhouse__fact_queue_tab",
            "visible_text_length": 128,
            "captured_at": "2026-04-28T12:00:00+00:00",
        }

    monkeypatch.setattr(chrome_devtools_collector, "_navigate_and_snapshot", fake_navigate)
    monkeypatch.setattr(
        chrome_devtools_collector,
        "_close_target",
        lambda _host, _port, target_id: closed_targets.append(target_id),
    )

    result = chrome_devtools_collector.collect_chrome_history_rendered_pages(days=2, max_pages=10)

    assert navigated_urls == ["https://space.shopee.io/utility/swp/detail/9280780"]
    assert closed_targets == ["target-1"]
    assert result["candidate_count"] == 1
    assert result["captured_count"] == 1
    event = result["events"][0]
    assert event["capture_method"] == "chrome_devtools_history"
    assert event["history_replay"] is True
    assert event["title"] == "Kafka SRE Approval"
    assert event["visit_duration_seconds"] == 360
    assert "Project: chatbot_data" in event["content"]
    assert "Current | Target" in event["content"]


def test_collect_chrome_mcp_history_rendered_pages_reuses_mcp_session(monkeypatch):
    captured = {}
    closed_tabs = []

    monkeypatch.setattr(chrome_devtools_collector, "_mcp_initialize", lambda _endpoint: "session-1")
    monkeypatch.setattr(chrome_devtools_collector, "_mcp_close", lambda _endpoint, _session_id: None)

    def fake_candidates(session_id, **kwargs):
        captured["session_id"] = session_id
        captured["kwargs"] = kwargs
        return [
            {
                "url": "https://space.shopee.io/utility/swp/detail/9280780",
                "title": "SWP-9280780",
                "visit_time": datetime(2026, 4, 28, 10, 30, tzinfo=timezone.utc),
                "visit_duration_seconds": None,
            }
        ]

    monkeypatch.setattr(chrome_devtools_collector, "_mcp_history_candidates", fake_candidates)
    tab_snapshots = iter([
        {1: "https://existing.example.com/"},
        {
            1: "https://existing.example.com/",
            99: "https://space.shopee.io/utility/swp/detail/9280780",
        },
    ])
    monkeypatch.setattr(
        chrome_devtools_collector,
        "_mcp_tabs_by_id",
        lambda *_args, **_kwargs: next(tab_snapshots),
    )
    monkeypatch.setattr(
        chrome_devtools_collector,
        "_mcp_close_tabs",
        lambda _endpoint, _session_id, tab_ids, **_kwargs: closed_tabs.append(tab_ids),
    )
    monkeypatch.setattr(
        chrome_devtools_collector,
        "_mcp_page_snapshot",
        lambda session_id, candidate, **_kwargs: {
            "url": candidate["url"],
            "requested_url": candidate["url"],
            "title": "Space Workflow Platform | SPACE",
            "headings": ["Space Workflow Platform | SPACE"],
            "main_text": "Apply Modify Kafka Topic Bandwidth Quota Project chatbot_data Kafka SRE Approval",
            "body_text": "Apply Modify Kafka Topic Bandwidth Quota Project chatbot_data Kafka SRE Approval",
            "visible_text_length": 84,
            "captured_at": "2026-04-28T12:00:00+00:00",
        },
    )

    result = chrome_devtools_collector.collect_chrome_mcp_history_rendered_pages(
        days=2,
        max_pages=20,
        domains=["shopee.io"],
    )

    assert captured["session_id"] == "session-1"
    assert captured["kwargs"]["domains"] == ["shopee.io"]
    assert result["collector"] == "chrome_mcp"
    assert result["candidate_count"] == 1
    assert closed_tabs == [[99]]
    event = result["events"][0]
    assert event["capture_method"] == "chrome_mcp_history"
    assert "chatbot_data" in event["content"]


def test_is_probable_intranet_url_supports_custom_domains():
    assert chrome_devtools_collector._is_probable_intranet_url(
        "https://jira.company.example/browse/MB-1",
        domains=["company.example"],
    )
    assert not chrome_devtools_collector._is_probable_intranet_url(
        "https://github.com/org/repo",
        domains=["company.example"],
    )
