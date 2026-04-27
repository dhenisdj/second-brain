import logging
import shutil
import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.services.chrome_collector import (
    _batch_fetch_contents,
    _build_browser_event_fields,
    _effective_url,
    _should_skip_record,
)

logger = logging.getLogger(__name__)

SAFARI_HISTORY_DB = Path.home() / "Library" / "Safari" / "History.db"
APPLE_EPOCH = datetime(2001, 1, 1, tzinfo=timezone.utc)


def _build_permission_error() -> PermissionError:
    return PermissionError(
        "Safari 历史记录访问被系统拒绝。请为运行当前应用的终端或 Python 解释器授予“完全磁盘访问权限”。"
    )


def _datetime_to_apple_seconds(dt: datetime) -> float:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (dt - APPLE_EPOCH).total_seconds()


def _apple_seconds_to_datetime(seconds: float | int) -> datetime:
    return APPLE_EPOCH + timedelta(seconds=float(seconds))


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    cursor = conn.execute(f"PRAGMA table_info({table})")
    return {row[1] for row in cursor.fetchall()}


def _read_safari_rows(db_path: Path, start_seconds: float, end_seconds: float) -> list[tuple]:
    tmp_copy = Path(tempfile.gettempdir()) / "morebrain_safari_history.db"
    try:
        shutil.copy2(db_path, tmp_copy)
    except PermissionError as exc:
        raise _build_permission_error() from exc
    except OSError as exc:
        if "not permitted" in str(exc).lower():
            raise _build_permission_error() from exc
        raise

    conn = sqlite3.connect(str(tmp_copy))
    try:
        item_columns = _table_columns(conn, "history_items")
        visit_columns = _table_columns(conn, "history_visits")
        item_title_expr = "hi.title" if "title" in item_columns else "NULL"
        visit_title_expr = "hv.title" if "title" in visit_columns else "NULL"
        load_successful_filter = "AND COALESCE(hv.load_successful, 1) = 1" if "load_successful" in visit_columns else ""

        query = f"""
            SELECT hi.url, COALESCE({visit_title_expr}, {item_title_expr}, hi.url) AS title, hv.visit_time
            FROM history_visits hv
            JOIN history_items hi ON hv.history_item = hi.id
            WHERE hv.visit_time >= ? AND hv.visit_time < ?
            {load_successful_filter}
            ORDER BY hv.visit_time
        """
        cursor = conn.execute(query, (start_seconds, end_seconds))
        return cursor.fetchall()
    except sqlite3.OperationalError as exc:
        if "authorization denied" in str(exc).lower():
            raise _build_permission_error() from exc
        raise
    finally:
        conn.close()
        tmp_copy.unlink(missing_ok=True)


def collect_safari_history(days: int = 2) -> dict:
    """Read local Safari history for the past N days."""
    if not SAFARI_HISTORY_DB.exists():
        raise FileNotFoundError(
            f"Safari 历史记录数据库不存在：{SAFARI_HISTORY_DB}"
        )

    now = datetime.now(timezone.utc)
    start = now - timedelta(days=days)
    start_seconds = _datetime_to_apple_seconds(start)
    end_seconds = _datetime_to_apple_seconds(now)

    rows = _read_safari_rows(SAFARI_HISTORY_DB, start_seconds, end_seconds)

    raw_events = []
    seen = set()
    for url, title, visit_time in rows:
        cleaned_title = (title or "").strip()
        if not url:
            continue
        if _should_skip_record(url, cleaned_title):
            continue
        if not cleaned_title and not _build_browser_event_fields(url, cleaned_title).get("content"):
            continue
        dedup_key = (url, float(visit_time))
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        raw_events.append((url, cleaned_title, float(visit_time)))

    urls = [_effective_url(row[0]) for row in raw_events]
    content_map = _batch_fetch_contents(urls)

    events = []
    for url, title, visit_time in raw_events:
        ts = _apple_seconds_to_datetime(visit_time)
        effective = _effective_url(url)
        event_fields = _build_browser_event_fields(
            url,
            title,
            content_map.get(effective),
        )
        events.append(
            {
                "source": "safari",
                "visit_time": ts.astimezone().isoformat(),
                **event_fields,
            }
        )

    events.sort(key=lambda event: event["visit_time"])
    dates = sorted({event["visit_time"][:10] for event in events}) if events else []
    logger.info("Collected %s Safari history events", len(events))

    return {
        "events": events,
        "total": len(events),
        "date_range": [dates[0], dates[-1]] if dates else [],
    }
