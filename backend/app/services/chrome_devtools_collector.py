import json
import logging
import time
from datetime import datetime, timedelta, timezone
from ipaddress import ip_address
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request
from urllib.request import urlopen
from urllib.parse import quote, urlparse

from app.services.chrome_collector import (
    MIN_VISIT_DURATION_US,
    SKIP_DOMAINS,
    _datetime_to_webkit,
    _description_to_title,
    _effective_url,
    _find_history_dbs,
    _hostname_matches,
    _read_one_db,
    _sanitize_url_for_storage,
    _shorten_text,
    _url_to_description,
    _webkit_to_datetime,
)

logger = logging.getLogger(__name__)

DEFAULT_DEVTOOLS_HOST = "127.0.0.1"
DEFAULT_DEVTOOLS_PORT = 9222
DEFAULT_CHROME_MCP_URL = "http://127.0.0.1:12306/mcp"
DEVTOOLS_HTTP_TIMEOUT = 2
DEVTOOLS_WS_TIMEOUT = 4
DEVTOOLS_NAVIGATION_TIMEOUT = 12
DEVTOOLS_RENDER_SETTLE_MS = 1600
MCP_HTTP_TIMEOUT = 30
MAX_EVENT_CONTENT_LEN = 9000
DEFAULT_HISTORY_RENDER_LIMIT = 80

LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}

DEFAULT_INTRANET_DOMAINS = {
    "shopee.io",
    "shopee.com",
    "sea.com",
    "seagroup.com",
    "seamoney.io",
    "garena.com",
}

INTRANET_HOST_SUFFIXES = (
    ".corp",
    ".internal",
    ".intranet",
    ".local",
    ".lan",
)

RENDERED_PAGE_SNAPSHOT_JS = r"""
(() => {
  const normalize = value => String(value || '').replace(/\s+/g, ' ').trim();
  const truncate = (value, limit) => {
    const text = normalize(value);
    return text.length > limit ? `${text.slice(0, Math.max(0, limit - 3)).trim()}...` : text;
  };
  const textOf = el => truncate(el && (el.innerText || el.textContent), 1200);

  const metaDescriptions = Array.from(document.querySelectorAll(
    'meta[name="description"], meta[property="og:description"], meta[name="twitter:description"]'
  )).map(el => truncate(el.getAttribute('content'), 500)).filter(Boolean);

  const headings = Array.from(document.querySelectorAll('h1, h2, h3'))
    .map(textOf)
    .filter(Boolean)
    .slice(0, 20);

  const mainText = Array.from(document.querySelectorAll('main, article, [role="main"], #content, .content'))
    .map(el => truncate(el.innerText || el.textContent, 3500))
    .filter(text => text.length > 40)
    .sort((a, b) => b.length - a.length)[0] || '';

  const tableText = Array.from(document.querySelectorAll('table'))
    .slice(0, 5)
    .map(table => Array.from(table.querySelectorAll('tr'))
      .slice(0, 10)
      .map(row => Array.from(row.querySelectorAll('th,td'))
        .slice(0, 8)
        .map(cell => truncate(cell.innerText || cell.textContent, 100))
        .filter(Boolean)
        .join(' | '))
      .filter(Boolean)
      .join('\n'))
    .filter(Boolean)
    .join('\n\n');

  const sensitiveField = label => /password|passwd|token|secret|credential|cookie|csrf|saml|jwt|key/i.test(label || '');
  const fieldText = Array.from(document.querySelectorAll('input, textarea, select, [role="textbox"], [aria-label], [data-testid]'))
    .slice(0, 80)
    .map(el => {
      const label = normalize(
        el.getAttribute('aria-label') ||
        el.getAttribute('name') ||
        el.getAttribute('placeholder') ||
        el.getAttribute('data-testid') ||
        el.id ||
        ''
      );
      const value = normalize(el.value || el.getAttribute('value') || el.innerText || el.textContent || '');
      if ((!label && !value) || sensitiveField(label) || sensitiveField(value)) return '';
      if (value && value.length > 180) return `${label}: ${truncate(value, 180)}`;
      return label && value ? `${label}: ${value}` : (label || value);
    })
    .filter(Boolean)
    .filter((item, index, arr) => arr.indexOf(item) === index)
    .slice(0, 40)
    .join('\n');

  const listText = Array.from(document.querySelectorAll('ul, ol, dl'))
    .slice(0, 12)
    .map(el => truncate(el.innerText || el.textContent, 800))
    .filter(text => text.length > 30)
    .join('\n\n');

  const bodyText = truncate(document.body ? document.body.innerText : '', 6000);

  return {
    url: location.href,
    title: document.title || '',
    language: document.documentElement.lang || '',
    meta_descriptions: metaDescriptions,
    headings,
    main_text: mainText,
    table_text: truncate(tableText, 3000),
    field_text: truncate(fieldText, 3000),
    list_text: truncate(listText, 2500),
    body_text: bodyText,
    visible_text_length: normalize(document.body ? document.body.innerText : '').length,
    captured_at: new Date().toISOString()
  };
})()
"""


class ChromeDevtoolsUnavailable(RuntimeError):
    """Raised when a local Chrome DevTools endpoint cannot be used."""


def _ensure_loopback(host: str) -> str:
    normalized = (host or DEFAULT_DEVTOOLS_HOST).strip()
    if normalized not in LOOPBACK_HOSTS:
        raise ChromeDevtoolsUnavailable("Chrome DevTools 采集只允许连接本机地址。")
    return normalized


def _load_websocket_module():
    try:
        import websocket  # type: ignore
    except ImportError as exc:
        raise ChromeDevtoolsUnavailable(
            "缺少 websocket-client 依赖，请先安装 backend/requirements.txt。"
        ) from exc
    return websocket


def _list_targets(host: str, port: int) -> list[dict[str, Any]]:
    host = _ensure_loopback(host)
    try:
        with urlopen(f"http://{host}:{port}/json", timeout=DEVTOOLS_HTTP_TIMEOUT) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (OSError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise ChromeDevtoolsUnavailable(
            f"无法连接 Chrome DevTools {host}:{port}。请用 --remote-debugging-port={port} 启动已登录 Chrome。"
        ) from exc

    if not isinstance(payload, list):
        raise ChromeDevtoolsUnavailable("Chrome DevTools 返回了无法识别的标签页列表。")
    return payload


def _devtools_json_request(
    host: str,
    port: int,
    path: str,
    *,
    method: str = "GET",
) -> dict[str, Any]:
    host = _ensure_loopback(host)
    url = f"http://{host}:{port}{path}"
    try:
        request = Request(url, method=method)
        with urlopen(request, timeout=DEVTOOLS_HTTP_TIMEOUT) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (OSError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise ChromeDevtoolsUnavailable(f"Chrome DevTools 请求失败：{url}") from exc
    if not isinstance(payload, dict):
        raise ChromeDevtoolsUnavailable("Chrome DevTools 返回了无法识别的响应。")
    return payload


def _new_target(host: str, port: int, url: str = "about:blank") -> dict[str, Any]:
    path = f"/json/new?{quote(url, safe='')}"
    try:
        target = _devtools_json_request(host, port, path, method="PUT")
    except ChromeDevtoolsUnavailable:
        target = _devtools_json_request(host, port, path, method="GET")
    if not target.get("id") or not target.get("webSocketDebuggerUrl"):
        raise ChromeDevtoolsUnavailable("无法创建 Chrome DevTools 临时标签页。")
    return target


def _close_target(host: str, port: int, target_id: str) -> None:
    try:
        _devtools_json_request(host, port, f"/json/close/{quote(target_id, safe='')}")
    except ChromeDevtoolsUnavailable as exc:
        logger.debug("Failed to close Chrome DevTools target %s: %s", target_id, exc)


def _page_targets(targets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    pages = []
    for target in targets:
        url = str(target.get("url") or "")
        if target.get("type") != "page":
            continue
        if not url.startswith(("http://", "https://")):
            continue
        try:
            if _hostname_matches(urlparse(url).hostname, SKIP_DOMAINS):
                continue
        except Exception:
            continue
        if not target.get("webSocketDebuggerUrl"):
            continue
        pages.append(target)
    return pages


def _cdp_call(ws, call_id: int, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    ws.send(json.dumps({"id": call_id, "method": method, "params": params or {}}))
    while True:
        message = json.loads(ws.recv())
        if message.get("id") == call_id:
            return message


def _evaluate_snapshot_on_ws(ws, call_id: int) -> dict[str, Any]:
    response = _cdp_call(
        ws,
        call_id,
        "Runtime.evaluate",
        {
            "expression": RENDERED_PAGE_SNAPSHOT_JS,
            "returnByValue": True,
            "awaitPromise": True,
        },
    )
    if response.get("exceptionDetails"):
        raise RuntimeError("页面脚本执行失败")

    value = response.get("result", {}).get("result", {}).get("value")
    if not isinstance(value, dict):
        raise RuntimeError("页面没有返回可序列化的正文快照")
    return value


def _evaluate_tab_snapshot(websocket_url: str) -> dict[str, Any]:
    websocket = _load_websocket_module()
    ws = websocket.create_connection(websocket_url, timeout=DEVTOOLS_WS_TIMEOUT)
    try:
        return _evaluate_snapshot_on_ws(ws, 1)
    finally:
        ws.close()


def _wait_for_document_ready(ws, first_call_id: int) -> int:
    deadline = time.monotonic() + DEVTOOLS_NAVIGATION_TIMEOUT
    call_id = first_call_id
    while time.monotonic() < deadline:
        try:
            response = _cdp_call(
                ws,
                call_id,
                "Runtime.evaluate",
                {"expression": "document.readyState", "returnByValue": True},
            )
            state = response.get("result", {}).get("result", {}).get("value")
            call_id += 1
            if state in {"interactive", "complete"}:
                return call_id
        except Exception:
            call_id += 1
        time.sleep(0.25)
    return call_id


def _settle_spa(ws, call_id: int) -> int:
    try:
        _cdp_call(
            ws,
            call_id,
            "Runtime.evaluate",
            {
                "expression": f"new Promise(resolve => setTimeout(resolve, {DEVTOOLS_RENDER_SETTLE_MS}))",
                "awaitPromise": True,
                "returnByValue": True,
            },
        )
    except Exception:
        pass
    return call_id + 1


def _navigate_and_snapshot(websocket_url: str, url: str) -> dict[str, Any]:
    websocket = _load_websocket_module()
    ws = websocket.create_connection(websocket_url, timeout=DEVTOOLS_WS_TIMEOUT)
    try:
        _cdp_call(ws, 1, "Page.enable")
        _cdp_call(ws, 2, "Runtime.enable")
        response = _cdp_call(ws, 3, "Page.navigate", {"url": url})
        error_text = response.get("result", {}).get("errorText")
        if error_text:
            raise RuntimeError(error_text)
        next_call_id = _wait_for_document_ready(ws, 4)
        next_call_id = _settle_spa(ws, next_call_id)
        snapshot = _evaluate_snapshot_on_ws(ws, next_call_id)
        snapshot.setdefault("requested_url", url)
        return snapshot
    finally:
        ws.close()


def _stored_url(url: str) -> str:
    return _sanitize_url_for_storage(_effective_url(url))


def _latest_history_by_url(urls: list[str], days: int) -> dict[str, dict[str, Any]]:
    target_urls = {_stored_url(url) for url in urls if url}
    if not target_urls:
        return {}

    try:
        db_paths = _find_history_dbs()
    except FileNotFoundError:
        return {}

    now = datetime.now(timezone.utc)
    start = now - timedelta(days=days)
    start_webkit = _datetime_to_webkit(start)
    end_webkit = _datetime_to_webkit(now)
    latest: dict[str, dict[str, Any]] = {}

    for db_path in db_paths:
        try:
            rows = _read_one_db(db_path, start_webkit, end_webkit)
        except Exception as exc:
            logger.debug("Failed to read Chrome history for DevTools merge: %s", exc)
            continue

        for url, title, visit_time, visit_duration in rows:
            stored = _stored_url(url)
            if stored not in target_urls:
                continue
            current = latest.get(stored)
            if current and visit_time <= current["visit_webkit"]:
                continue
            latest[stored] = {
                "visit_webkit": visit_time,
                "visit_time": _webkit_to_datetime(visit_time),
                "visit_duration_seconds": int(visit_duration / 1_000_000) if visit_duration else None,
                "history_title": title or "",
            }

    return latest


def _normalize_domain_list(domains: list[str] | tuple[str, ...] | None) -> set[str]:
    normalized = set()
    for domain in domains or []:
        value = str(domain or "").strip().lower()
        value = value.removeprefix("http://").removeprefix("https://").strip("/")
        if value:
            normalized.add(value.removeprefix("www."))
    return normalized


def _is_private_host(hostname: str) -> bool:
    try:
        return ip_address(hostname).is_private
    except ValueError:
        return False


def _is_probable_intranet_url(
    url: str,
    domains: list[str] | tuple[str, ...] | None = None,
) -> bool:
    try:
        parsed = urlparse(_effective_url(url))
    except Exception:
        return False

    hostname = (parsed.hostname or "").lower().removeprefix("www.")
    if parsed.scheme not in {"http", "https"} or not hostname:
        return False
    if _hostname_matches(hostname, SKIP_DOMAINS):
        return False

    domain_filter = _normalize_domain_list(domains)
    if domain_filter:
        return _hostname_matches(hostname, domain_filter)

    if _hostname_matches(hostname, DEFAULT_INTRANET_DOMAINS):
        return True
    if _is_private_host(hostname):
        return True
    if "." not in hostname:
        return True
    return any(hostname.endswith(suffix) for suffix in INTRANET_HOST_SUFFIXES)


def _history_candidates(
    *,
    days: int,
    max_pages: int,
    offset: int = 0,
    domains: list[str] | tuple[str, ...] | None = None,
    intranet_only: bool = True,
) -> list[dict[str, Any]]:
    try:
        db_paths = _find_history_dbs()
    except FileNotFoundError:
        return []

    now = datetime.now(timezone.utc)
    start = now - timedelta(days=days)
    start_webkit = _datetime_to_webkit(start)
    end_webkit = _datetime_to_webkit(now)
    latest_by_url: dict[str, dict[str, Any]] = {}

    for db_path in db_paths:
        try:
            rows = _read_one_db(db_path, start_webkit, end_webkit)
        except Exception as exc:
            logger.debug("Failed to read Chrome history candidates: %s", exc)
            continue

        for url, title, visit_time, visit_duration in rows:
            if not url or not str(url).startswith(("http://", "https://")):
                continue
            if visit_duration and visit_duration < MIN_VISIT_DURATION_US:
                continue
            effective_url = _effective_url(str(url))
            if intranet_only and not _is_probable_intranet_url(effective_url, domains):
                continue

            stored_url = _sanitize_url_for_storage(effective_url)
            current = latest_by_url.get(stored_url)
            if current and visit_time <= current["visit_webkit"]:
                continue

            latest_by_url[stored_url] = {
                "url": stored_url,
                "raw_url": str(url),
                "title": (title or "").strip(),
                "visit_webkit": visit_time,
                "visit_time": _webkit_to_datetime(visit_time),
                "visit_duration_seconds": int(visit_duration / 1_000_000) if visit_duration else None,
            }

    candidates = sorted(latest_by_url.values(), key=lambda item: item["visit_webkit"], reverse=True)
    start = max(0, offset)
    end = start + max(1, max_pages) + 1
    return candidates[start:end]


def _parse_snapshot_time(value: Any) -> datetime:
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def _text_list(values: Any, limit: int = 10) -> list[str]:
    if not isinstance(values, list):
        return []
    result = []
    for value in values:
        text = " ".join(str(value or "").split())
        if text and text not in result:
            result.append(text)
        if len(result) >= limit:
            break
    return result


def _compose_rendered_content(snapshot: dict[str, Any]) -> str:
    parts: list[str] = []

    headings = _text_list(snapshot.get("headings"), limit=12)
    if headings:
        parts.append("页面标题结构：" + "；".join(_shorten_text(item, 120) for item in headings))

    meta = _text_list(snapshot.get("meta_descriptions"), limit=3)
    if meta:
        parts.append("页面描述：" + "；".join(_shorten_text(item, 240) for item in meta))

    main_text = _shorten_text(str(snapshot.get("main_text") or ""), 1800)
    table_text = _shorten_text(str(snapshot.get("table_text") or ""), 1600)
    field_text = _shorten_text(str(snapshot.get("field_text") or ""), 1800)
    list_text = _shorten_text(str(snapshot.get("list_text") or ""), 1400)
    body_text = _shorten_text(str(snapshot.get("body_text") or ""), 2600)

    if main_text:
        parts.append(f"主内容：{main_text}")
    if table_text and table_text not in main_text:
        parts.append(f"表格摘要：{table_text}")
    if field_text and field_text not in main_text and field_text not in table_text:
        parts.append(f"页面字段：{field_text}")
    if list_text and list_text not in main_text and list_text not in table_text:
        parts.append(f"列表摘要：{list_text}")
    if body_text and body_text not in main_text:
        parts.append(f"可见文本：{body_text}")

    content = " | ".join(part for part in parts if part)
    return _shorten_text(content, MAX_EVENT_CONTENT_LEN)


def _snapshot_to_event(snapshot: dict[str, Any], history: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    raw_url = str(snapshot.get("url") or "")
    if not raw_url.startswith(("http://", "https://")):
        return None
    if _hostname_matches(urlparse(raw_url).hostname, SKIP_DOMAINS):
        return None

    stored_url = _stored_url(raw_url)
    requested_url = str(snapshot.get("requested_url") or "")
    history_item = history.get(stored_url) or (history.get(_stored_url(requested_url)) if requested_url else None) or {}
    captured_at = _parse_snapshot_time(snapshot.get("captured_at"))
    visit_time = history_item.get("visit_time") or captured_at
    if visit_time.tzinfo is None:
        visit_time = visit_time.replace(tzinfo=timezone.utc)

    title = str(snapshot.get("title") or history_item.get("history_title") or "").strip()
    if not title:
        title = _description_to_title(_url_to_description(stored_url))

    content = _compose_rendered_content(snapshot)
    if not content:
        content = f"页面线索：{_url_to_description(stored_url)}"

    event = {
        "source": "chrome",
        "visit_time": visit_time.astimezone().isoformat(),
        "title": title,
        "url": stored_url,
        "content": content,
        "capture_method": "chrome_devtools",
        "captured_at": captured_at.astimezone().isoformat(),
        "rendered_text_chars": int(snapshot.get("visible_text_length") or 0),
    }

    duration_seconds = history_item.get("visit_duration_seconds")
    if duration_seconds:
        event["visit_duration_seconds"] = duration_seconds
    return event


def _dedupe_snapshots(snapshots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_url: dict[str, dict[str, Any]] = {}
    for snapshot in snapshots:
        raw_url = str(snapshot.get("url") or "")
        if not raw_url:
            continue
        stored = _stored_url(raw_url)
        current = by_url.get(stored)
        current_len = int(current.get("visible_text_length") or 0) if current else -1
        next_len = int(snapshot.get("visible_text_length") or 0)
        if current is None or next_len >= current_len:
            by_url[stored] = snapshot
    return list(by_url.values())


def _parse_mcp_sse_response(raw: str) -> dict[str, Any]:
    data_lines = []
    for line in raw.splitlines():
        if line.startswith("data:"):
            data_lines.append(line.removeprefix("data:").strip())
    if not data_lines:
        return {}
    try:
        payload = json.loads("\n".join(data_lines))
    except json.JSONDecodeError as exc:
        raise ChromeDevtoolsUnavailable("Chrome MCP 返回了无法解析的响应。") from exc
    if not isinstance(payload, dict):
        raise ChromeDevtoolsUnavailable("Chrome MCP 返回了无法识别的响应。")
    return payload


def _mcp_post(
    endpoint: str,
    payload: dict[str, Any],
    *,
    session_id: str | None = None,
    timeout: int = MCP_HTTP_TIMEOUT,
) -> tuple[dict[str, Any], str | None]:
    parsed = urlparse(endpoint)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in LOOPBACK_HOSTS:
        raise ChromeDevtoolsUnavailable("Chrome MCP 采集只允许连接本机 MCP 服务。")

    headers = {
        "content-type": "application/json",
        "accept": "application/json, text/event-stream",
    }
    if session_id:
        headers["mcp-session-id"] = session_id

    request = Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            next_session_id = resp.headers.get("mcp-session-id")
    except HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise ChromeDevtoolsUnavailable(f"Chrome MCP 请求失败：{error_body or exc.reason}") from exc
    except (OSError, URLError, TimeoutError) as exc:
        raise ChromeDevtoolsUnavailable(f"无法连接 Chrome MCP 服务 {endpoint}。请先在 Chrome 扩展中点击 Connect。") from exc

    return _parse_mcp_sse_response(raw), next_session_id


def _mcp_close(endpoint: str, session_id: str) -> None:
    parsed = urlparse(endpoint)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in LOOPBACK_HOSTS:
        return
    request = Request(endpoint, headers={"mcp-session-id": session_id}, method="DELETE")
    try:
        with urlopen(request, timeout=DEVTOOLS_HTTP_TIMEOUT):
            pass
    except Exception as exc:
        logger.debug("Failed to close Chrome MCP session: %s", exc)


def _mcp_initialize(endpoint: str = DEFAULT_CHROME_MCP_URL) -> str:
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "second-brain", "version": "0.1.0"},
        },
    }
    response, session_id = _mcp_post(endpoint, payload, timeout=DEVTOOLS_HTTP_TIMEOUT)
    if response.get("error"):
        raise ChromeDevtoolsUnavailable(f"Chrome MCP 初始化失败：{response['error']}")
    if not session_id:
        raise ChromeDevtoolsUnavailable("Chrome MCP 未返回会话 ID。")

    _mcp_post(
        endpoint,
        {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
        session_id=session_id,
        timeout=DEVTOOLS_HTTP_TIMEOUT,
    )
    return session_id


def _mcp_call_tool(
    endpoint: str,
    session_id: str,
    name: str,
    arguments: dict[str, Any] | None = None,
    *,
    call_id: int = 2,
    timeout: int = MCP_HTTP_TIMEOUT,
) -> dict[str, Any]:
    response, _ = _mcp_post(
        endpoint,
        {
            "jsonrpc": "2.0",
            "id": call_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments or {}},
        },
        session_id=session_id,
        timeout=timeout,
    )
    if response.get("error"):
        raise RuntimeError(str(response["error"]))
    result = response.get("result")
    if not isinstance(result, dict):
        raise RuntimeError("Chrome MCP 工具返回了无法识别的结果。")
    if result.get("isError"):
        content = result.get("content") or []
        message = content[0].get("text") if content and isinstance(content[0], dict) else None
        raise RuntimeError(message or f"Chrome MCP 工具 {name} 执行失败。")

    content = result.get("content") or []
    if not content or not isinstance(content[0], dict):
        return {}
    text = content[0].get("text")
    if not isinstance(text, str) or not text:
        return {}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {"text": text}
    return parsed if isinstance(parsed, dict) else {"value": parsed}


def _mcp_tabs_by_id(
    endpoint: str,
    session_id: str,
    *,
    call_id: int,
) -> dict[int, str]:
    payload = _mcp_call_tool(
        endpoint,
        session_id,
        "get_windows_and_tabs",
        {},
        call_id=call_id,
        timeout=DEVTOOLS_HTTP_TIMEOUT,
    )
    tabs: dict[int, str] = {}

    def collect_tab(tab: Any) -> None:
        if not isinstance(tab, dict):
            return
        raw_id = tab.get("tabId", tab.get("id"))
        try:
            tab_id = int(raw_id)
        except (TypeError, ValueError):
            return
        tabs[tab_id] = str(tab.get("url") or "")

    for tab in payload.get("tabs") or []:
        collect_tab(tab)
    for window in payload.get("windows") or []:
        if isinstance(window, dict):
            for tab in window.get("tabs") or []:
                collect_tab(tab)
    return tabs


def _urls_match_for_cleanup(url: str, target_urls: list[str]) -> bool:
    if not url:
        return False
    try:
        stored_url = _stored_url(url)
    except Exception:
        return False
    return any(stored_url == _stored_url(target_url) for target_url in target_urls if target_url)


def _mcp_close_tabs(
    endpoint: str,
    session_id: str,
    tab_ids: list[int],
    *,
    call_id: int,
) -> None:
    if not tab_ids:
        return
    _mcp_call_tool(
        endpoint,
        session_id,
        "chrome_close_tabs",
        {"tabIds": tab_ids},
        call_id=call_id,
        timeout=DEVTOOLS_HTTP_TIMEOUT,
    )


def _mcp_close_new_history_tabs(
    endpoint: str,
    session_id: str,
    before_tabs: dict[int, str],
    target_urls: list[str],
    *,
    call_id: int,
) -> int:
    try:
        after_tabs = _mcp_tabs_by_id(endpoint, session_id, call_id=call_id)
        call_id += 1
        new_tabs = {tab_id: url for tab_id, url in after_tabs.items() if tab_id not in before_tabs}
        close_ids = [
            tab_id
            for tab_id, url in new_tabs.items()
            if _urls_match_for_cleanup(url, target_urls)
        ]
        if not close_ids and len(new_tabs) == 1:
            close_ids = list(new_tabs)
        if close_ids:
            _mcp_close_tabs(endpoint, session_id, sorted(close_ids), call_id=call_id)
            call_id += 1
    except Exception as exc:
        logger.debug("Failed to close Chrome MCP history tabs: %s", exc)
    return call_id


def _mcp_history_time(value: Any) -> datetime:
    if isinstance(value, (int, float)) and value > 0:
        return datetime.fromtimestamp(value / 1000, timezone.utc)
    return datetime.now(timezone.utc)


def _mcp_history_candidates(
    session_id: str,
    *,
    days: int,
    max_pages: int,
    offset: int = 0,
    domains: list[str] | None,
    intranet_only: bool,
    endpoint: str = DEFAULT_CHROME_MCP_URL,
) -> list[dict[str, Any]]:
    queries = list(_normalize_domain_list(domains)) if domains else [""]
    if not queries:
        queries = [""]

    by_url: dict[str, dict[str, Any]] = {}
    call_id = 10
    fetch_limit = min(1000, max((max(0, offset) + max(1, max_pages) + 1) * 2, max_pages))
    for query in queries:
        payload = _mcp_call_tool(
            endpoint,
            session_id,
            "chrome_history",
            {
                "text": query,
                "startTime": f"{max(1, days)} days ago",
                "endTime": "now",
                "maxResults": fetch_limit,
                "excludeCurrentTabs": False,
            },
            call_id=call_id,
            timeout=MCP_HTTP_TIMEOUT,
        )
        call_id += 1

        for item in payload.get("items") or []:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "")
            if not url.startswith(("http://", "https://")):
                continue
            if intranet_only and not _is_probable_intranet_url(url, domains):
                continue
            stored_url = _sanitize_url_for_storage(_effective_url(url))
            visit_time = _mcp_history_time(item.get("lastVisitTime"))
            current = by_url.get(stored_url)
            if current and visit_time <= current["visit_time"]:
                continue
            by_url[stored_url] = {
                "url": stored_url,
                "raw_url": url,
                "title": str(item.get("title") or "").strip(),
                "visit_time": visit_time,
                "visit_duration_seconds": None,
                "visit_count": item.get("visitCount"),
            }

    candidates = sorted(by_url.values(), key=lambda item: item["visit_time"], reverse=True)
    start = max(0, offset)
    end = start + max(1, max_pages) + 1
    return candidates[start:end]


def _mcp_page_snapshot(
    session_id: str,
    candidate: dict[str, Any],
    *,
    endpoint: str = DEFAULT_CHROME_MCP_URL,
    call_id: int,
) -> dict[str, Any]:
    payload = _mcp_call_tool(
        endpoint,
        session_id,
        "chrome_get_web_content",
        {
            "url": candidate["url"],
            "background": True,
            "textContent": True,
            "htmlContent": False,
        },
        call_id=call_id,
        timeout=MCP_HTTP_TIMEOUT,
    )
    if payload.get("success") is False:
        raise RuntimeError(str(payload.get("error") or "Chrome MCP 页面正文读取失败"))

    article = payload.get("article") if isinstance(payload.get("article"), dict) else {}
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    text_content = str(payload.get("textContent") or payload.get("text") or "")
    title = str(payload.get("title") or article.get("title") or candidate.get("title") or "")
    meta_descriptions = [
        str(value).strip()
        for value in (article.get("excerpt"), metadata.get("description"))
        if str(value or "").strip()
    ]

    return {
        "url": str(payload.get("url") or candidate["url"]),
        "requested_url": candidate["url"],
        "title": title,
        "headings": [title] if title else [],
        "meta_descriptions": meta_descriptions,
        "main_text": text_content,
        "body_text": text_content,
        "visible_text_length": len(text_content),
        "captured_at": datetime.now(timezone.utc).isoformat(),
    }


def collect_chrome_mcp_history_rendered_pages(
    days: int = 2,
    max_pages: int = DEFAULT_HISTORY_RENDER_LIMIT,
    offset: int = 0,
    domains: list[str] | None = None,
    intranet_only: bool = True,
    endpoint: str = DEFAULT_CHROME_MCP_URL,
) -> dict[str, Any]:
    session_id = _mcp_initialize(endpoint)
    try:
        candidates = _mcp_history_candidates(
            session_id,
            days=days,
            max_pages=max_pages,
            offset=offset,
            domains=domains,
            intranet_only=intranet_only,
            endpoint=endpoint,
        )
        has_more = len(candidates) > max(1, max_pages)
        candidates = candidates[:max(1, max_pages)]
        if not candidates:
            label = "内网页面" if intranet_only else "Chrome 页面"
            return {
                "events": [],
                "total": 0,
                "date_range": [],
                "collected_sources": ["chrome"],
                "source_breakdown": {"chrome": 0},
                "warnings": [f"最近 {days} 天没有找到可采集的{label}历史记录"],
                "candidate_count": 0,
                "captured_count": 0,
                "offset": max(0, offset),
                "batch_size": max(1, max_pages),
                "next_offset": max(0, offset),
                "has_more": False,
                "collector": "chrome_mcp",
            }

        snapshots: list[dict[str, Any]] = []
        warnings: list[str] = []
        call_id = 100
        for candidate in candidates:
            before_tabs: dict[int, str] = {}
            target_urls = [str(candidate.get("url") or "")]
            try:
                before_tabs = _mcp_tabs_by_id(endpoint, session_id, call_id=call_id)
                call_id += 1
            except Exception as exc:
                logger.debug("Failed to snapshot Chrome tabs before MCP content fetch: %s", exc)

            try:
                snapshot = _mcp_page_snapshot(session_id, candidate, endpoint=endpoint, call_id=call_id)
                target_urls.append(str(snapshot.get("url") or ""))
                snapshots.append(snapshot)
            except Exception as exc:
                title = candidate.get("title") or candidate.get("url") or "Chrome 历史页面"
                warnings.append(f"{_shorten_text(str(title), 80)}：Chrome MCP 正文读取失败：{exc}")
            finally:
                call_id += 1
                if before_tabs:
                    call_id = _mcp_close_new_history_tabs(
                        endpoint,
                        session_id,
                        before_tabs,
                        target_urls,
                        call_id=call_id,
                    )

        snapshots = _dedupe_snapshots(snapshots)
        history = _history_map_from_candidates(candidates)
        events = []
        for snapshot in snapshots:
            event = _snapshot_to_event(snapshot, history)
            if event is None:
                continue
            event["capture_method"] = "chrome_mcp_history"
            event["history_replay"] = True
            events.append(event)

        events.sort(key=lambda event: event["visit_time"])
        dates = sorted({event["visit_time"][:10] for event in events}) if events else []

        return {
            "events": events,
            "total": len(events),
            "date_range": [dates[0], dates[-1]] if dates else [],
            "collected_sources": ["chrome"],
            "source_breakdown": {"chrome": len(events)},
            "warnings": warnings,
            "candidate_count": len(candidates),
            "captured_count": len(events),
            "offset": max(0, offset),
            "batch_size": max(1, max_pages),
            "next_offset": max(0, offset) + len(candidates),
            "has_more": has_more,
            "collector": "chrome_mcp",
        }
    finally:
        _mcp_close(endpoint, session_id)


def collect_chrome_rendered_tabs(
    host: str = DEFAULT_DEVTOOLS_HOST,
    port: int = DEFAULT_DEVTOOLS_PORT,
    days: int = 2,
) -> dict[str, Any]:
    """Collect rendered text from open Chrome tabs through the DevTools protocol.

    This complements the History sqlite collector: pages that require an
    authenticated browser session can be captured if the user has opened them
    in a Chrome instance launched with a local remote-debugging port.
    """
    targets = _page_targets(_list_targets(host, port))
    warnings: list[str] = []
    snapshots: list[dict[str, Any]] = []

    for target in targets:
        try:
            snapshot = _evaluate_tab_snapshot(str(target["webSocketDebuggerUrl"]))
        except Exception as exc:
            label = target.get("title") or target.get("url") or "Chrome 标签页"
            warnings.append(f"{label}：渲染内容读取失败：{exc}")
            continue

        snapshot.setdefault("url", target.get("url"))
        snapshot.setdefault("title", target.get("title"))
        snapshots.append(snapshot)

    snapshots = _dedupe_snapshots(snapshots)
    history = _latest_history_by_url([str(snapshot.get("url") or "") for snapshot in snapshots], days)

    events = [
        event
        for snapshot in snapshots
        if (event := _snapshot_to_event(snapshot, history)) is not None
    ]
    events.sort(key=lambda event: event["visit_time"])
    dates = sorted({event["visit_time"][:10] for event in events}) if events else []

    return {
        "events": events,
        "total": len(events),
        "date_range": [dates[0], dates[-1]] if dates else [],
        "collected_sources": ["chrome"],
        "source_breakdown": {"chrome": len(events)},
        "warnings": warnings,
    }


def _history_map_from_candidates(candidates: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    history: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        url = str(candidate.get("url") or "")
        if not url:
            continue
        history[_stored_url(url)] = {
            "visit_time": candidate.get("visit_time"),
            "visit_duration_seconds": candidate.get("visit_duration_seconds"),
            "history_title": candidate.get("title") or "",
        }
    return history


def collect_chrome_history_rendered_pages(
    host: str = DEFAULT_DEVTOOLS_HOST,
    port: int = DEFAULT_DEVTOOLS_PORT,
    days: int = 2,
    max_pages: int = DEFAULT_HISTORY_RENDER_LIMIT,
    offset: int = 0,
    domains: list[str] | None = None,
    intranet_only: bool = True,
) -> dict[str, Any]:
    """Replay recent Chrome history in an authenticated Chrome session.

    The local History database gives us candidate URLs and timestamps, while
    DevTools navigation reuses the already logged-in browser profile to read
    rendered intranet pages that plain HTTP requests cannot access.
    """
    candidates = _history_candidates(
        days=days,
        max_pages=max_pages,
        offset=offset,
        domains=domains,
        intranet_only=intranet_only,
    )
    warnings: list[str] = []
    has_more = len(candidates) > max(1, max_pages)
    candidates = candidates[:max(1, max_pages)]
    if not candidates:
        label = "内网页面" if intranet_only else "Chrome 页面"
        return {
            "events": [],
            "total": 0,
            "date_range": [],
            "collected_sources": ["chrome"],
            "source_breakdown": {"chrome": 0},
            "warnings": [f"最近 {days} 天没有找到可采集的{label}历史记录"],
            "candidate_count": 0,
            "captured_count": 0,
            "offset": max(0, offset),
            "batch_size": max(1, max_pages),
            "next_offset": max(0, offset),
            "has_more": False,
        }

    target = _new_target(host, port)
    target_id = str(target["id"])
    websocket_url = str(target["webSocketDebuggerUrl"])
    snapshots: list[dict[str, Any]] = []

    try:
        for candidate in candidates:
            url = str(candidate["url"])
            try:
                snapshot = _navigate_and_snapshot(websocket_url, url)
            except Exception as exc:
                title = candidate.get("title") or url
                warnings.append(f"{_shorten_text(str(title), 80)}：页面渲染采集失败：{exc}")
                continue

            snapshot.setdefault("url", url)
            snapshot.setdefault("requested_url", url)
            snapshot.setdefault("title", candidate.get("title") or "")
            snapshots.append(snapshot)
    finally:
        _close_target(host, port, target_id)

    snapshots = _dedupe_snapshots(snapshots)
    history = _history_map_from_candidates(candidates)
    events = []
    for snapshot in snapshots:
        event = _snapshot_to_event(snapshot, history)
        if event is None:
            continue
        event["capture_method"] = "chrome_devtools_history"
        event["history_replay"] = True
        events.append(event)

    events.sort(key=lambda event: event["visit_time"])
    dates = sorted({event["visit_time"][:10] for event in events}) if events else []

    return {
        "events": events,
        "total": len(events),
        "date_range": [dates[0], dates[-1]] if dates else [],
        "collected_sources": ["chrome"],
        "source_breakdown": {"chrome": len(events)},
        "warnings": warnings,
        "candidate_count": len(candidates),
        "captured_count": len(events),
        "offset": max(0, offset),
        "batch_size": max(1, max_pages),
        "next_offset": max(0, offset) + len(candidates),
        "has_more": has_more,
    }
