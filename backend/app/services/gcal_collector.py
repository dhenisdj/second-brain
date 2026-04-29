import logging
import os
import re
import json
from datetime import datetime, timedelta, timezone
from html import unescape
from html.parser import HTMLParser
from pathlib import Path

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

CALENDAR_SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
SCOPES = CALENDAR_SCOPES + GMAIL_SCOPES
CRED_DIR = Path(os.getenv("SECOND_BRAIN_CREDENTIALS_DIR", Path(__file__).parent.parent.parent / "credentials"))
CLIENT_SECRET_PATH = CRED_DIR / "google_credentials.json"
TOKEN_PATH = CRED_DIR / "gcal_token.json"
_PENDING_OAUTH_FLOWS: dict[str, InstalledAppFlow] = {}


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


def _token_has_scopes(creds: Credentials, required_scopes: list[str] | None = None) -> bool:
    scopes = set(required_scopes or SCOPES)
    granted = set(getattr(creds, "granted_scopes", None) or getattr(creds, "scopes", None) or [])
    if not granted:
        return False
    return scopes.issubset(granted)


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

    flow.fetch_token(code=code)
    creds = flow.credentials
    CRED_DIR.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
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
        cal_list = service.calendarList().list().execute()
        for cal in cal_list.get("items", []):
            role = cal.get("accessRole", "")
            if role in ("owner", "writer", "reader"):
                calendar_ids.append(cal["id"])
    except Exception:
        calendar_ids = ["primary"]

    if not calendar_ids:
        calendar_ids = ["primary"]

    all_events = []
    for cal_id in calendar_ids:
        page_token = None
        while True:
            result = service.events().list(
                calendarId=cal_id,
                timeMin=time_min,
                timeMax=time_max,
                singleEvents=True,
                orderBy="startTime",
                maxResults=250,
                pageToken=page_token,
            ).execute()

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
