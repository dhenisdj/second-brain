import logging
import os
import re
import json
from datetime import datetime, timedelta, timezone
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)

CALENDAR_SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
SCOPES = CALENDAR_SCOPES + GMAIL_SCOPES
SCOPE_LABELS = {
    CALENDAR_SCOPES[0]: "Google Calendar 只读",
    GMAIL_SCOPES[0]: "Gmail 只读",
}
GMAIL_API_SLUG = "gmail.googleapis.com"
CALENDAR_API_SLUG = "calendar-json.googleapis.com"
CRED_DIR = Path(os.getenv("SECOND_BRAIN_CREDENTIALS_DIR", Path(__file__).parent.parent.parent / "credentials"))
CLIENT_SECRET_PATH = CRED_DIR / "google_credentials.json"
TOKEN_PATH = CRED_DIR / "gcal_token.json"
_PENDING_OAUTH_FLOWS: dict[str, InstalledAppFlow] = {}


class GoogleApiNotEnabledError(RuntimeError):
    def __init__(
        self,
        api_slug: str,
        api_label: str,
        project_id: str | None = None,
        message: str | None = None,
    ):
        self.api_slug = api_slug
        self.api_label = api_label
        self.project_id = project_id or get_google_client_project_id()
        self.action_url = build_google_api_enable_url(api_slug, self.project_id)
        super().__init__(
            message
            or f"{api_label} 尚未在 Google Cloud 项目中启用，请打开 Google Cloud Console 开启后等待几分钟再重试。"
        )

    def to_detail(self) -> dict:
        return {
            "code": "google_api_disabled",
            "message": str(self),
            "action_label": f"开启 {self.api_label}",
            "action_url": self.action_url,
            "project_id": self.project_id,
        }


def _validate_client_secret_payload(payload: dict) -> None:
    if not isinstance(payload, dict):
        raise ValueError("Google OAuth 凭据必须是 JSON 对象")

    client_config = payload.get("installed") or payload.get("web")
    if not isinstance(client_config, dict):
        raise ValueError("凭据文件缺少 installed 或 web 配置")

    required = {"client_id", "client_secret", "auth_uri", "token_uri"}
    missing = sorted(key for key in required if not client_config.get(key))
    if missing:
        raise ValueError(f"凭据文件缺少字段：{', '.join(missing)}")


def has_google_client_credentials() -> bool:
    return CLIENT_SECRET_PATH.exists()


def _load_google_client_config() -> dict:
    if not CLIENT_SECRET_PATH.exists():
        return {}
    try:
        payload = json.loads(CLIENT_SECRET_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload.get("installed") or payload.get("web") or {}


def get_google_client_project_id() -> str:
    return str(_load_google_client_config().get("project_id") or "").strip()


def build_google_api_enable_url(api_slug: str, project_id: str | None = None) -> str:
    project = (project_id or get_google_client_project_id() or "").strip()
    url = f"https://console.cloud.google.com/apis/library/{api_slug}"
    if project:
        url += f"?project={quote(project)}"
    return url


def _extract_project_id_from_google_error(message: str) -> str:
    patterns = [
        r"[?&]project=([A-Za-z0-9:_-]+)",
        r"\bproject\s+([A-Za-z0-9:_-]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, message)
        if match:
            return match.group(1).strip()
    return ""


def raise_google_api_not_enabled(exc: HttpError, api_slug: str, api_label: str) -> None:
    if getattr(exc.resp, "status", None) != 403:
        return

    raw_content = getattr(exc, "content", b"") or b""
    if isinstance(raw_content, bytes):
        content = raw_content.decode("utf-8", errors="replace")
    else:
        content = str(raw_content)
    error_text = f"{exc} {content}"

    disabled_markers = (
        "accessNotConfigured",
        "has not been used",
        "it is disabled",
    )
    if not any(marker in error_text for marker in disabled_markers):
        return

    raise GoogleApiNotEnabledError(
        api_slug=api_slug,
        api_label=api_label,
        project_id=_extract_project_id_from_google_error(error_text),
    ) from exc


def execute_google_request(request, api_slug: str, api_label: str) -> dict:
    try:
        return request.execute()
    except HttpError as exc:
        raise_google_api_not_enabled(exc, api_slug, api_label)
        raise


def _scope_set(value) -> set[str]:
    if not value:
        return set()
    if isinstance(value, str):
        return set(value.split())
    return set(value)


def _granted_scope_set(creds: Credentials) -> set[str]:
    return _scope_set(getattr(creds, "granted_scopes", None)) or _scope_set(getattr(creds, "scopes", None))


def _token_has_scopes(creds: Credentials, required_scopes: list[str] | None = None) -> bool:
    scopes = set(required_scopes or SCOPES)
    granted = _granted_scope_set(creds)
    if not granted:
        return False
    return scopes.issubset(granted)


def _scope_label(scope: str) -> str:
    return SCOPE_LABELS.get(scope, scope)


def _missing_scope_message(missing_scopes: list[str]) -> str:
    missing = "、".join(_scope_label(scope) for scope in missing_scopes)
    return (
        f"Google 授权未包含 {missing} 权限。请确认 OAuth 同意屏幕允许该权限，"
        "并在 Google 授权页面勾选同意后重试。"
    )


def _validate_google_token_scopes(creds: Credentials, required_scopes: list[str] | None = None) -> None:
    required = required_scopes or SCOPES
    granted = _granted_scope_set(creds)
    missing = [scope for scope in required if scope not in granted]
    if missing:
        raise ValueError(_missing_scope_message(missing))


def _scope_warning_to_value_error(exc: Warning) -> ValueError:
    new_scopes = _scope_set(getattr(exc, "new_scope", None))
    if new_scopes:
        missing = [scope for scope in SCOPES if scope not in new_scopes]
        if missing:
            return ValueError(_missing_scope_message(missing))
    return ValueError("Google 返回的授权权限与请求不一致，请回到配置页重新授权 Google 数据源")


def _fetch_token_allowing_scope_diff(flow: InstalledAppFlow, code: str):
    previous = os.environ.get("OAUTHLIB_RELAX_TOKEN_SCOPE")
    os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"
    try:
        return flow.fetch_token(code=code)
    finally:
        if previous is None:
            os.environ.pop("OAUTHLIB_RELAX_TOKEN_SCOPE", None)
        else:
            os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = previous


def has_google_authorized_token(required_scopes: list[str] | None = None) -> bool:
    if not TOKEN_PATH.exists():
        return False
    try:
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH))
    except Exception:
        return False
    return bool(creds and (creds.valid or creds.refresh_token) and _token_has_scopes(creds, required_scopes))


def has_google_calendar_authorized_token() -> bool:
    return has_google_authorized_token(CALENDAR_SCOPES)


def has_google_gmail_authorized_token() -> bool:
    return has_google_authorized_token(GMAIL_SCOPES)


def check_google_calendar_api_enabled() -> bool | None:
    try:
        service = _build_service(
            required_scopes=CALENDAR_SCOPES,
            missing_scope_message="Google Calendar 尚未完成授权，请先在配置页点击“授权 Google 数据源”",
        )
        execute_google_request(
            service.calendarList().list(maxResults=1),
            CALENDAR_API_SLUG,
            "Google Calendar API",
        )
        return True
    except GoogleApiNotEnabledError:
        return False
    except (FileNotFoundError, PermissionError):
        return None
    except Exception:
        logger.info("Google Calendar API readiness check failed", exc_info=True)
        return None


def check_google_gmail_api_enabled() -> bool | None:
    try:
        service = _build_service(
            service_name="gmail",
            version="v1",
            required_scopes=GMAIL_SCOPES,
            missing_scope_message="Gmail 尚未完成读取授权，请在配置页重新授权 Google 数据源",
        )
        execute_google_request(
            service.users().getProfile(userId="me"),
            GMAIL_API_SLUG,
            "Gmail API",
        )
        return True
    except GoogleApiNotEnabledError:
        return False
    except (FileNotFoundError, PermissionError):
        return None
    except Exception:
        logger.info("Gmail API readiness check failed", exc_info=True)
        return None


def save_google_client_credentials(content: bytes) -> dict:
    try:
        payload = json.loads(content.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise ValueError("凭据文件必须是 UTF-8 编码的 JSON") from exc
    except json.JSONDecodeError as exc:
        raise ValueError("凭据文件不是合法 JSON") from exc

    _validate_client_secret_payload(payload)
    CRED_DIR.mkdir(parents=True, exist_ok=True)
    CLIENT_SECRET_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    TOKEN_PATH.unlink(missing_ok=True)

    client_config = payload.get("installed") or payload.get("web") or {}
    return {
        "google_credentials_configured": True,
        "google_calendar_authorized": False,
        "google_gmail_authorized": False,
        "client_id": client_config.get("client_id", ""),
    }


class _HTMLToTextParser(HTMLParser):
    BLOCK_TAGS = {"p", "div", "br", "li", "ul", "ol", "tr", "table"}
    SKIP_TAGS = {"style", "script", "head"}

    def __init__(self):
        super().__init__()
        self._parts: list[str] = []
        self._skip_depth = 0
        self._current_href: str | None = None
        self._link_text: list[str] = []

    def _append_newline(self):
        if not self._parts:
            return
        if not self._parts[-1].endswith("\n"):
            self._parts.append("\n")

    def _append_text(self, text: str):
        text = re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()
        if not text:
            return
        if self._parts and not self._parts[-1].endswith(("\n", " ", "(", "（")):
            self._parts.append(" ")
        self._parts.append(text)

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in self.SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth > 0:
            return
        if tag in self.BLOCK_TAGS:
            self._append_newline()
        if tag == "a":
            attrs_dict = dict(attrs)
            self._current_href = attrs_dict.get("href")
            self._link_text = []

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in self.SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
            return
        if self._skip_depth > 0:
            return
        if tag == "a":
            text = " ".join(self._link_text).strip()
            href = (self._current_href or "").strip()
            if href:
                if text and text != href:
                    self._append_text(f"{text} ({href})")
                else:
                    self._append_text(href)
            elif text:
                self._append_text(text)
            self._current_href = None
            self._link_text = []
        if tag in {"p", "div", "li", "tr"}:
            self._append_newline()

    def handle_data(self, data):
        if self._skip_depth > 0:
            return
        text = re.sub(r"\s+", " ", data.replace("\xa0", " ")).strip()
        if not text:
            return
        if self._current_href is not None:
            self._link_text.append(text)
        else:
            self._append_text(text)

    def get_text(self) -> str:
        lines = []
        for raw_line in unescape("".join(self._parts)).splitlines():
            line = re.sub(r"\s+", " ", raw_line).strip()
            if line:
                lines.append(line)
        return "\n".join(lines)


def _html_to_text(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    if "<" not in text and ">" not in text:
        return re.sub(r"\s+", " ", unescape(text.replace("\xa0", " "))).strip()

    parser = _HTMLToTextParser()
    try:
        parser.feed(text)
        parser.close()
    except Exception:
        return re.sub(r"<[^>]+>", " ", unescape(text))
    return parser.get_text()


def build_google_authorization_url(redirect_uri: str) -> dict:
    if not CLIENT_SECRET_PATH.exists():
        raise FileNotFoundError(
            f"Google OAuth2 凭据文件未找到: {CLIENT_SECRET_PATH}\n"
            "请在 Google Cloud Console 创建 OAuth2 桌面应用凭据，"
            "下载 JSON 文件后在配置页上传保存。"
        )

    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET_PATH), SCOPES)
    flow.redirect_uri = redirect_uri
    authorization_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    _PENDING_OAUTH_FLOWS[state] = flow
    return {
        "authorization_url": authorization_url,
        "state": state,
        "redirect_uri": redirect_uri,
    }


def complete_google_authorization(state: str, code: str) -> dict:
    flow = _PENDING_OAUTH_FLOWS.pop(state, None)
    if not flow:
        raise ValueError("Google 授权状态已过期，请回到配置页重新发起授权")

    try:
        _fetch_token_allowing_scope_diff(flow, code)
    except Warning as exc:
        raise _scope_warning_to_value_error(exc) from exc

    creds = flow.credentials
    _validate_google_token_scopes(creds, SCOPES)
    CRED_DIR.mkdir(parents=True, exist_ok=True)
    tmp_path = TOKEN_PATH.with_suffix(".tmp")
    tmp_path.write_text(creds.to_json(), encoding="utf-8")
    tmp_path.replace(TOKEN_PATH)
    logger.info("OAuth2 authorization completed, token saved")
    return {"google_calendar_authorized": True, "google_gmail_authorized": True}


def _get_credentials(
    allow_interactive: bool = False,
    required_scopes: list[str] | None = None,
    missing_scope_message: str | None = None,
) -> Credentials:
    """Get valid OAuth2 credentials."""
    creds = None

    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH))

    if creds and not _token_has_scopes(creds, required_scopes or SCOPES):
        raise PermissionError(
            missing_scope_message
            or "Google 授权权限不完整，请在配置页重新授权 Google 数据源"
        )

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            TOKEN_PATH.write_text(creds.to_json())
            return creds
        except Exception:
            logger.warning("Token refresh failed, re-authorizing")

    if not CLIENT_SECRET_PATH.exists():
        raise FileNotFoundError(
            f"Google OAuth2 凭据文件未找到: {CLIENT_SECRET_PATH}\n"
            "请在 Google Cloud Console 创建 OAuth2 桌面应用凭据，"
            "下载 JSON 文件后在配置页上传保存。"
        )

    if not allow_interactive:
        raise PermissionError("Google 尚未完成授权，请先在配置页点击“授权 Google 数据源”")

    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET_PATH), SCOPES)
    creds = flow.run_local_server(port=8090, open_browser=True)
    TOKEN_PATH.write_text(creds.to_json())
    logger.info("OAuth2 authorization completed, token saved")
    return creds


def _build_service(
    service_name: str = "calendar",
    version: str = "v3",
    required_scopes: list[str] | None = None,
    missing_scope_message: str | None = None,
):
    creds = _get_credentials(
        required_scopes=required_scopes,
        missing_scope_message=missing_scope_message,
    )
    return build(service_name, version, credentials=creds, cache_discovery=False)


def _parse_event_time(event_time: dict) -> datetime | None:
    if "dateTime" in event_time:
        return datetime.fromisoformat(event_time["dateTime"])
    if "date" in event_time:
        return datetime.fromisoformat(event_time["date"])
    return None


def _format_attendees(attendees: list[dict]) -> str:
    parts = []
    for a in attendees:
        name = a.get("displayName") or a.get("email", "")
        status = a.get("responseStatus", "")
        if a.get("self"):
            continue
        label = name
        if status == "accepted":
            label += " (已接受)"
        elif status == "declined":
            label += " (已拒绝)"
        elif status == "tentative":
            label += " (待定)"
        parts.append(label)
    return ", ".join(parts)


def _format_event_content(event: dict) -> str:
    sections = []

    description = _html_to_text(event.get("description") or "")
    if description:
        if len(description) > 500:
            description = description[:500] + "..."
        sections.append(description)

    attendees = event.get("attendees", [])
    if attendees:
        sections.append(f"参会人: {_format_attendees(attendees)}")

    location = event.get("location", "").strip()
    if location:
        sections.append(f"地点: {location}")

    conference = event.get("conferenceData", {})
    entry_points = conference.get("entryPoints", [])
    for ep in entry_points:
        if ep.get("entryPointType") == "video":
            sections.append(f"会议链接: {ep.get('uri', '')}")
            break

    hangout = event.get("hangoutLink", "")
    if hangout and "会议链接" not in " ".join(sections):
        sections.append(f"会议链接: {hangout}")

    attachments = event.get("attachments", [])
    if attachments:
        att_names = [a.get("title", a.get("fileUrl", "")) for a in attachments[:5]]
        sections.append(f"附件: {', '.join(att_names)}")

    return "\n".join(sections)


def collect_gcal_events(user_email: str, days: int = 2) -> dict:
    """Collect Google Calendar events for the past N days via OAuth2."""
    service = _build_service(
        required_scopes=CALENDAR_SCOPES,
        missing_scope_message="Google Calendar 尚未完成授权，请先在配置页点击“授权 Google 数据源”",
    )

    local_now = datetime.now().astimezone()
    local_tz = local_now.tzinfo or timezone.utc
    start = local_now - timedelta(days=days)
    end_of_today = local_now.replace(hour=23, minute=59, second=59, microsecond=999999)
    time_min = start.isoformat()
    time_max = end_of_today.astimezone(local_tz).isoformat()

    calendar_ids = []
    try:
        cal_list = execute_google_request(
            service.calendarList().list(),
            CALENDAR_API_SLUG,
            "Google Calendar API",
        )
        for cal in cal_list.get("items", []):
            role = cal.get("accessRole", "")
            if role in ("owner", "writer", "reader"):
                calendar_ids.append(cal["id"])
    except GoogleApiNotEnabledError:
        raise
    except Exception:
        calendar_ids = ["primary"]

    if not calendar_ids:
        calendar_ids = ["primary"]

    all_events = []
    for cal_id in calendar_ids:
        page_token = None
        while True:
            result = execute_google_request(
                service.events().list(
                    calendarId=cal_id,
                    timeMin=time_min,
                    timeMax=time_max,
                    singleEvents=True,
                    orderBy="startTime",
                    maxResults=250,
                    pageToken=page_token,
                ),
                CALENDAR_API_SLUG,
                "Google Calendar API",
            )

            items = result.get("items", [])
            all_events.extend(items)

            page_token = result.get("nextPageToken")
            if not page_token:
                break

    events = []
    seen = set()
    for item in all_events:
        event_id = item.get("id", "")
        start_info = item.get("start", {})
        end_info = item.get("end", {})

        start_dt = _parse_event_time(start_info)
        end_dt = _parse_event_time(end_info)
        if not start_dt:
            continue

        dedup_key = (event_id, start_dt.isoformat())
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        summary = item.get("summary", "（无标题）")
        content = _format_event_content(item)

        duration_minutes = None
        if start_dt and end_dt:
            delta = end_dt - start_dt
            duration_minutes = max(1, int(delta.total_seconds() / 60))

        events.append({
            "timestamp": start_dt.isoformat(),
            "title": summary,
            "content": content,
            "duration_minutes": duration_minutes,
            "event_id": event_id,
        })

    events.sort(key=lambda e: e["timestamp"])
    dates = sorted({e["timestamp"][:10] for e in events}) if events else []

    logger.info(f"Collected {len(events)} calendar events for {user_email}")

    return {
        "events": events,
        "total": len(events),
        "date_range": [dates[0], dates[-1]] if dates else [],
    }
