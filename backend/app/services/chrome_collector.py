import shutil
import sqlite3
import tempfile
import re
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, unquote, urljoin, urlparse

import httpx

logger = logging.getLogger(__name__)

CHROME_BASE_DIRS = {
    "darwin": Path.home() / "Library" / "Application Support" / "Google" / "Chrome",
}

WEBKIT_EPOCH = datetime(1601, 1, 1, tzinfo=timezone.utc)

MIN_VISIT_DURATION_US = 5_000_000  # 5 seconds in microseconds
FETCH_TIMEOUT = 5
MAX_CONTENT_LEN = 500
MAX_CONCURRENT_FETCHES = 8

AUTH_DOMAINS = {
    "accounts.google.com",
    "login.microsoftonline.com",
    "auth0.com",
}

SKIP_DOMAINS = {
    "localhost", "127.0.0.1", "0.0.0.0",
    "chrome.google.com", *AUTH_DOMAINS,
}

REDIRECT_PARAM_NAMES = {
    "continue",
    "continue_url",
    "redirect",
    "redirect_uri",
    "redirect_url",
    "return",
    "return_to",
    "returnurl",
    "return_url",
    "target",
    "url",
    "next",
    "destination",
    "dest",
    "relaystate",
}

NOISY_QUERY_KEYS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "gclid",
    "fbclid",
    "msclkid",
    "ved",
    "ei",
    "sa",
    "source",
    "authuser",
    "hl",
    "pli",
    "usp",
}

SENSITIVE_QUERY_KEYS = {
    "code",
    "state",
    "token",
    "access_token",
    "refresh_token",
    "id_token",
    "client_secret",
    "password",
    "passwd",
    "session",
    "sessionid",
    "cookie",
    "csrf",
    "samlrequest",
    "samlresponse",
    "sig",
    "signature",
    "credential",
    "assertion",
    "jwt",
}

SENSITIVE_QUERY_KEY_FRAGMENTS = (
    "token",
    "secret",
    "password",
    "session",
    "cookie",
    "csrf",
    "saml",
    "signature",
    "credential",
    "assertion",
    "jwt",
)


class _TextExtractor(HTMLParser):
    """Minimal HTML-to-text parser using stdlib only."""

    SKIP_TAGS = {"script", "style", "noscript", "head", "meta", "link", "svg", "path"}

    def __init__(self):
        super().__init__()
        self._pieces: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag.lower() in self.SKIP_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag):
        if tag.lower() in self.SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data):
        if self._skip_depth == 0:
            text = data.strip()
            if text:
                self._pieces.append(text)

    def get_text(self) -> str:
        raw = " ".join(self._pieces)
        return re.sub(r"\s+", " ", raw).strip()


def _extract_text_from_html(html: str) -> str:
    parser = _TextExtractor()
    try:
        parser.feed(html)
    except Exception:
        return ""
    return parser.get_text()


def _hostname_matches(hostname: str | None, domains: set[str]) -> bool:
    if not hostname:
        return False
    normalized = hostname.lower().removeprefix("www.")
    return any(normalized == domain or normalized.endswith(f".{domain}") for domain in domains)


def _is_auth_url(url: str) -> bool:
    try:
        return _hostname_matches(urlparse(url).hostname, AUTH_DOMAINS)
    except Exception:
        return False


def _decode_url_value(value: str) -> str:
    current = value.strip()
    for _ in range(3):
        decoded = unquote(current)
        if decoded == current:
            break
        current = decoded
    return current


def _extract_nested_url(value: str, base_url: str) -> str | None:
    decoded = _decode_url_value(value)
    if decoded.startswith(("http://", "https://")):
        return decoded
    if decoded.startswith("/"):
        return urljoin(base_url, decoded)
    return None


def _iter_url_params(url: str):
    parsed = urlparse(url)
    for raw_params in (parsed.query, parsed.fragment):
        for key, value in parse_qsl(raw_params, keep_blank_values=False):
            yield key, value


def _extract_redirect_target(url: str, depth: int = 0) -> str | None:
    if depth >= 3:
        return None

    try:
        params = list(_iter_url_params(url))
    except Exception:
        return None

    for key, value in params:
        normalized_key = key.lower().replace("-", "_")
        if normalized_key not in REDIRECT_PARAM_NAMES:
            continue

        nested_url = _extract_nested_url(value, url)
        if not nested_url:
            continue

        deeper = _extract_redirect_target(nested_url, depth + 1) if _is_auth_url(nested_url) else None
        return deeper or nested_url

    return None


def _effective_url(url: str) -> str:
    return _extract_redirect_target(url) or url


def _is_sensitive_query_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return normalized in SENSITIVE_QUERY_KEYS or any(part in normalized for part in SENSITIVE_QUERY_KEY_FRAGMENTS)


def _is_noisy_query_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return normalized in NOISY_QUERY_KEYS or normalized.startswith("utm_")


def _clean_query_value(value: str) -> str | None:
    cleaned = _decode_url_value(value).replace("_", " ").strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    if len(cleaned) < 2 or len(cleaned) > 120:
        return None
    if re.fullmatch(r"[A-Za-z0-9_\-./+=]{32,}", cleaned):
        return None
    return cleaned


def _safe_query_parts(url: str) -> list[str]:
    parts = []
    try:
        params = list(_iter_url_params(url))
    except Exception:
        return parts

    for key, value in params:
        if len(parts) >= 4:
            break
        if _is_sensitive_query_key(key) or _is_noisy_query_key(key):
            continue

        nested_url = _extract_nested_url(value, url)
        if nested_url:
            nested_desc = _url_to_description(nested_url)
            if nested_desc:
                parts.append(f"{key.replace('_', ' ')}: {nested_desc}")
            continue

        cleaned_value = _clean_query_value(value)
        if cleaned_value:
            parts.append(f"{key.replace('_', ' ')}: {cleaned_value}")

    return parts


def _sanitize_url_for_storage(url: str, depth: int = 0) -> str:
    try:
        parsed = urlparse(url)
    except Exception:
        return url

    safe_params = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=False):
        if _is_sensitive_query_key(key) or _is_noisy_query_key(key):
            continue

        nested_url = _extract_nested_url(value, url)
        if nested_url and depth < 2:
            safe_params.append((key, _sanitize_url_for_storage(nested_url, depth + 1)))
            continue

        if len(value) > 180:
            continue

        safe_params.append((key, value))

    return parsed._replace(query=urlencode(safe_params), fragment="").geturl()


def _shorten_text(text: str, limit: int) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: max(0, limit - 3)].rstrip() + "..."


def _description_to_title(description: str) -> str:
    if not description:
        return "浏览页面"
    return _shorten_text(description.replace(" - ", " / "), 120)


def _is_noisy_auth_title(title: str) -> bool:
    normalized = title.strip().lower()
    if not normalized:
        return True
    return any(
        marker in normalized
        for marker in (
            "sign in",
            "signin",
            "log in",
            "login",
            "google accounts",
            "google account",
            "continue to",
            "loading",
            "sso",
            "oauth",
        )
    )


def _compose_browser_content(
    *,
    original_url: str,
    effective_url: str,
    original_title: str,
    title: str,
    fetched_content: str | None,
    visit_duration_seconds: int | None,
) -> str:
    parts: list[str] = []
    effective_desc = _url_to_description(effective_url)

    if original_url != effective_url:
        parts.append("认证跳转：通过 Google/SSO 登录后进入目标页面")
        if effective_desc:
            parts.append(f"目标页面：{effective_desc}")

    if original_title and original_title != title and not _is_noisy_auth_title(original_title):
        parts.append(f"浏览器标题：{original_title}")

    if fetched_content:
        parts.append(f"页面正文摘要：{fetched_content}")
    elif effective_desc:
        parts.append(f"页面线索：{effective_desc}")

    if visit_duration_seconds:
        parts.append(f"停留时长：约 {visit_duration_seconds} 秒")

    unique_parts = []
    for part in parts:
        if part and part not in unique_parts:
            unique_parts.append(part)

    return _shorten_text(" | ".join(unique_parts), 900)


def _build_browser_event_fields(
    url: str,
    title: str,
    fetched_content: str | None = None,
    visit_duration_seconds: int | None = None,
) -> dict:
    cleaned_title = (title or "").strip()
    normalized_url = _effective_url(url)
    stored_url = _sanitize_url_for_storage(normalized_url)
    stored_original_url = _sanitize_url_for_storage(url)
    is_auth_redirect = normalized_url != url
    description = _url_to_description(stored_url)

    if is_auth_redirect and _is_noisy_auth_title(cleaned_title):
        cleaned_title = f"登录后访问 {_description_to_title(description)}"
    elif not cleaned_title:
        cleaned_title = _description_to_title(description)

    content = _compose_browser_content(
        original_url=url,
        effective_url=stored_url,
        original_title=(title or "").strip(),
        title=cleaned_title,
        fetched_content=fetched_content,
        visit_duration_seconds=visit_duration_seconds,
    )

    fields = {
        "title": cleaned_title,
        "url": stored_url,
        "content": content,
    }
    if normalized_url != url:
        fields["original_url"] = stored_original_url
        fields["auth_redirect"] = True
    return fields


def _should_skip_record(url: str, title: str) -> bool:
    if not _is_auth_url(url):
        return False
    if _extract_redirect_target(url):
        return False
    return _is_noisy_auth_title(title)


def _fetch_page_content(url: str) -> str | None:
    """Fetch a URL and extract its main text content."""
    try:
        parsed = urlparse(url)
        if _hostname_matches(parsed.hostname, SKIP_DOMAINS):
            return None
        if parsed.scheme not in ("http", "https"):
            return None

        with httpx.Client(timeout=FETCH_TIMEOUT, follow_redirects=True) as client:
            resp = client.get(url, headers={"User-Agent": "Mozilla/5.0 MoreBrain/1.0"})
            if resp.status_code >= 400:
                return None
            if _hostname_matches(urlparse(str(resp.url)).hostname, SKIP_DOMAINS):
                return None
            content_type = resp.headers.get("content-type", "")
            if "text/html" not in content_type:
                return None
            text = _extract_text_from_html(resp.text)
            if len(text) > MAX_CONTENT_LEN:
                text = text[:MAX_CONTENT_LEN] + "..."
            return text if len(text) > 20 else None
    except Exception:
        return None


def _batch_fetch_contents(urls: list[str]) -> dict[str, str]:
    """Fetch page contents concurrently, returns url -> content mapping."""
    unique_urls = list(set(urls))
    results: dict[str, str] = {}

    with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_FETCHES) as executor:
        future_to_url = {executor.submit(_fetch_page_content, u): u for u in unique_urls}
        for future in as_completed(future_to_url):
            url = future_to_url[future]
            try:
                content = future.result()
                if content:
                    results[url] = content
            except Exception:
                pass

    logger.info(f"Fetched content for {len(results)}/{len(unique_urls)} URLs")
    return results


def _url_to_description(url: str) -> str:
    """Extract a human-readable description from a URL as fallback content."""
    try:
        parsed = urlparse(url)
    except Exception:
        return ""

    domain = (parsed.hostname or "").lower().removeprefix("www.")
    path = unquote(parsed.path).strip("/")

    parts = []
    for seg in path.split("/"):
        if not seg or seg.isdigit() or len(seg) <= 1:
            continue
        cleaned = seg.replace("-", " ").replace("_", " ")
        for ext in (".html", ".htm", ".php", ".aspx", ".jsp"):
            cleaned = cleaned.removesuffix(ext)
        if cleaned:
            parts.append(cleaned)

    query_parts = _safe_query_parts(url)

    desc_items = []
    if domain:
        desc_items.append(domain)
    if parts:
        desc_items.append(" / ".join(parts[-3:]))
    if query_parts:
        desc_items.append("（" + ", ".join(query_parts[:3]) + "）")

    return " - ".join(desc_items) if desc_items else ""


def _find_history_dbs() -> list[Path]:
    """Find all Chrome History database files across all profiles."""
    import platform
    system = platform.system().lower()
    base = CHROME_BASE_DIRS.get(system)
    if base is None:
        raise FileNotFoundError(f"Unsupported OS: {system}. Currently only macOS is supported.")
    if not base.exists():
        raise FileNotFoundError(
            f"Chrome data directory not found at {base}. "
            "Make sure Google Chrome is installed."
        )

    candidates = ["Default", "Profile 1", "Profile 2", "Profile 3",
                   "Profile 4", "Profile 5", "Profile 6", "Profile 7"]
    found = []
    for profile in candidates:
        history = base / profile / "History"
        if history.exists():
            found.append(history)

    if not found:
        raise FileNotFoundError(
            f"No Chrome History database found in {base}. "
            "Make sure you have at least one Chrome profile."
        )
    return found


def _webkit_to_datetime(webkit_ts: int) -> datetime:
    return WEBKIT_EPOCH + timedelta(microseconds=webkit_ts)


def _datetime_to_webkit(dt: datetime) -> int:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int((dt - WEBKIT_EPOCH).total_seconds() * 1_000_000)


def _read_one_db(db_path: Path, start_webkit: int, end_webkit: int) -> list[tuple]:
    tmp_copy = Path(tempfile.gettempdir()) / f"morebrain_chrome_{db_path.parent.name}"
    shutil.copy2(db_path, tmp_copy)
    conn = sqlite3.connect(str(tmp_copy))
    try:
        cursor = conn.execute(
            """
            SELECT u.url, u.title, v.visit_time, v.visit_duration
            FROM visits v
            JOIN urls u ON v.url = u.id
            WHERE v.visit_time >= ? AND v.visit_time < ?
            ORDER BY v.visit_time
            """,
            (start_webkit, end_webkit),
        )
        return cursor.fetchall()
    finally:
        conn.close()
        tmp_copy.unlink(missing_ok=True)


def collect_chrome_history(days: int = 2) -> dict:
    """Read local Chrome history for the past N days across all profiles,
    then fetch page content for each URL."""
    db_paths = _find_history_dbs()

    now = datetime.now(timezone.utc)
    start = now - timedelta(days=days)
    start_webkit = _datetime_to_webkit(start)
    end_webkit = _datetime_to_webkit(now)

    all_rows = []
    for db_path in db_paths:
        try:
            all_rows.extend(_read_one_db(db_path, start_webkit, end_webkit))
        except Exception:
            continue

    raw_events = []
    seen = set()
    for url, title, visit_time, visit_duration in all_rows:
        if visit_duration < MIN_VISIT_DURATION_US:
            continue
        if not url:
            continue
        cleaned_title = (title or "").strip()
        if _should_skip_record(url, cleaned_title):
            continue
        if not cleaned_title and not _url_to_description(_sanitize_url_for_storage(_effective_url(url))):
            continue
        dedup_key = (url, visit_time)
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        raw_events.append((url, cleaned_title, visit_time, visit_duration))

    urls = [_sanitize_url_for_storage(_effective_url(e[0])) for e in raw_events]
    content_map = _batch_fetch_contents(urls)

    events = []
    for url, title, visit_time, visit_duration in raw_events:
        ts = _webkit_to_datetime(visit_time)
        visit_duration_seconds = int(visit_duration / 1_000_000)
        effective = _sanitize_url_for_storage(_effective_url(url))
        event_fields = _build_browser_event_fields(
            url,
            title,
            content_map.get(effective),
            visit_duration_seconds,
        )

        events.append({
            "source": "chrome",
            "visit_time": ts.astimezone().isoformat(),
            **event_fields,
            "visit_duration_seconds": visit_duration_seconds,
        })

    events.sort(key=lambda e: e["visit_time"])
    dates = sorted({e["visit_time"][:10] for e in events}) if events else []

    return {
        "events": events,
        "total": len(events),
        "date_range": [dates[0], dates[-1]] if dates else [],
    }
