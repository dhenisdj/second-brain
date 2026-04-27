import sqlite3
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from app.services import browser_collector, chrome_collector, safari_collector


def _apple_seconds(dt: datetime) -> float:
    return (dt - safari_collector.APPLE_EPOCH).total_seconds()


class TestChromeCollector:
    def test_browser_event_fields_use_url_when_title_is_missing(self):
        fields = chrome_collector._build_browser_event_fields(
            "https://corp.example.com/work/items/MB-123?project=second-brain",
            "",
        )

        assert fields["title"].startswith("corp.example.com")
        assert "MB 123" in fields["title"]
        assert "页面线索" in fields["content"]
        assert "project: second-brain" in fields["content"]

    def test_collect_chrome_history_enriches_google_auth_redirect(self, tmp_path, monkeypatch):
        target_url = "https://corp.example.com/app/projects/alpha?ticket=MB-123&token=secret-value"
        auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?continue={quote(target_url, safe='')}&state=opaque"
        db_path = tmp_path / "History"
        visit_dt = datetime.now(timezone.utc) - timedelta(hours=1)

        conn = sqlite3.connect(db_path)
        try:
            conn.execute("CREATE TABLE urls (id INTEGER PRIMARY KEY, url TEXT, title TEXT)")
            conn.execute(
                """
                CREATE TABLE visits (
                    id INTEGER PRIMARY KEY,
                    url INTEGER,
                    visit_time INTEGER,
                    visit_duration INTEGER
                )
                """
            )
            conn.execute(
                "INSERT INTO urls (id, url, title) VALUES (1, ?, ?)",
                (auth_url, "Sign in - Google Accounts"),
            )
            conn.execute(
                "INSERT INTO visits (url, visit_time, visit_duration) VALUES (1, ?, ?)",
                (chrome_collector._datetime_to_webkit(visit_dt), 120_000_000),
            )
            conn.commit()
        finally:
            conn.close()

        fetched_urls = []
        monkeypatch.setattr(chrome_collector, "_find_history_dbs", lambda: [db_path])

        def fake_batch_fetch(urls):
            fetched_urls.extend(urls)
            return {}

        monkeypatch.setattr(chrome_collector, "_batch_fetch_contents", fake_batch_fetch)

        result = chrome_collector.collect_chrome_history(days=2)

        assert result["total"] == 1
        event = result["events"][0]
        assert fetched_urls == ["https://corp.example.com/app/projects/alpha?ticket=MB-123"]
        assert event["source"] == "chrome"
        assert event["url"] == "https://corp.example.com/app/projects/alpha?ticket=MB-123"
        assert event["auth_redirect"] is True
        assert event["title"].startswith("登录后访问")
        assert "认证跳转" in event["content"]
        assert "corp.example.com" in event["content"]
        assert "ticket: MB-123" in event["content"]
        assert "secret-value" not in event["content"]
        assert "token=" not in event["url"]


class TestSafariCollector:
    def test_collect_safari_history_reads_local_db(self, tmp_path, monkeypatch):
        db_path = tmp_path / "History.db"
        conn = sqlite3.connect(db_path)
        try:
            conn.execute("CREATE TABLE history_items (id INTEGER PRIMARY KEY, url TEXT, title TEXT)")
            conn.execute(
                """
                CREATE TABLE history_visits (
                    id INTEGER PRIMARY KEY,
                    history_item INTEGER,
                    visit_time REAL,
                    load_successful INTEGER,
                    title TEXT
                )
                """
            )
            conn.execute(
                "INSERT INTO history_items (id, url, title) VALUES (1, ?, ?)",
                ("https://developer.apple.com/documentation", "Apple Docs"),
            )
            conn.execute(
                "INSERT INTO history_visits (history_item, visit_time, load_successful, title) VALUES (1, ?, 1, ?)",
                (_apple_seconds(datetime.now(timezone.utc) - timedelta(hours=1)), "Safari 标题"),
            )
            conn.commit()
        finally:
            conn.close()

        monkeypatch.setattr(safari_collector, "SAFARI_HISTORY_DB", db_path)
        monkeypatch.setattr(safari_collector, "_batch_fetch_contents", lambda urls: {urls[0]: "抓取内容"})

        result = safari_collector.collect_safari_history(days=2)

        assert result["total"] == 1
        assert result["events"][0]["source"] == "safari"
        assert result["events"][0]["title"] == "Safari 标题"
        assert result["events"][0]["content"] == "页面正文摘要：抓取内容"


class TestBrowserCollector:
    def test_collect_browser_history_tolerates_partial_failures(self, monkeypatch):
        monkeypatch.setattr(
            browser_collector,
            "collect_chrome_history",
            lambda days: {
                "events": [
                    {
                        "source": "chrome",
                        "visit_time": "2026-04-03T10:00:00+08:00",
                        "title": "Chrome 页",
                        "url": "https://example.com",
                        "content": "example",
                    }
                ],
                "date_range": ["2026-04-03", "2026-04-03"],
            },
        )

        def _raise_permission(_days):
            raise PermissionError("Safari 访问被拒绝")

        monkeypatch.setattr(browser_collector, "collect_safari_history", _raise_permission)

        result = browser_collector.collect_browser_history(days=2)

        assert result["total"] == 1
        assert result["collected_sources"] == ["chrome"]
        assert result["source_breakdown"] == {"chrome": 1}
        assert result["warnings"] == ["Safari 访问被拒绝"]
