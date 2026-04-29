import base64
import logging
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote

from app.services.gcal_collector import GMAIL_API_SLUG, GMAIL_SCOPES, _build_service, _html_to_text, execute_google_request

logger = logging.getLogger(__name__)

DEFAULT_MAX_MESSAGES = 100
BODY_LIMIT = 4000


def _decode_body(data: str | None) -> str:
    if not data:
        return ""
    try:
        padded = data + "=" * (-len(data) % 4)
        return base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8", errors="replace")
    except Exception:
        return ""


def _headers_to_dict(headers: list[dict] | None) -> dict[str, str]:
    result: dict[str, str] = {}
    for header in headers or []:
        name = (header.get("name") or "").lower()
        value = header.get("value") or ""
        if name:
            result[name] = value
    return result


def _iter_parts(payload: dict):
    yield payload
    for part in payload.get("parts") or []:
        yield from _iter_parts(part)


def _extract_message_body(payload: dict) -> str:
    plain_parts: list[str] = []
    html_parts: list[str] = []

    for part in _iter_parts(payload):
        if part.get("filename"):
            continue
        mime_type = (part.get("mimeType") or "").lower()
        data = (part.get("body") or {}).get("data")
        if not data:
            continue
        decoded = _decode_body(data)
        if not decoded:
            continue
        if mime_type == "text/plain":
            plain_parts.append(decoded)
        elif mime_type == "text/html":
            html_parts.append(_html_to_text(decoded))

    text = "\n".join(part.strip() for part in plain_parts if part.strip())
    if not text:
        text = "\n".join(part.strip() for part in html_parts if part.strip())
    lines = [" ".join(line.split()) for line in text.splitlines()]
    return "\n".join(line for line in lines if line).strip()


def _extract_attachments(payload: dict) -> list[str]:
    filenames: list[str] = []
    for part in _iter_parts(payload):
        filename = (part.get("filename") or "").strip()
        if filename:
            filenames.append(filename)
    return filenames


def _parse_message_time(headers: dict[str, str], internal_date: str | None) -> datetime:
    date_header = headers.get("date")
    if date_header:
        try:
            parsed = parsedate_to_datetime(date_header)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone()
        except Exception:
            pass

    if internal_date:
        try:
            return datetime.fromtimestamp(int(internal_date) / 1000, tz=timezone.utc).astimezone()
        except Exception:
            pass

    return datetime.now().astimezone()


def _message_url(user_email: str, message_id: str) -> str:
    account = quote(user_email or "0", safe="@.")
    return f"https://mail.google.com/mail/u/{account}/#all/{message_id}"


def _format_message_content(message: dict, headers: dict[str, str]) -> str:
    sections: list[str] = []

    sender = headers.get("from", "").strip()
    recipients = headers.get("to", "").strip()
    cc = headers.get("cc", "").strip()
    if sender:
        sections.append(f"发件人: {sender}")
    if recipients:
        sections.append(f"收件人: {recipients}")
    if cc:
        sections.append(f"抄送: {cc}")

    labels = [label for label in message.get("labelIds", []) if label not in {"UNREAD", "IMPORTANT"}]
    if labels:
        sections.append(f"标签: {', '.join(labels[:8])}")

    snippet = (message.get("snippet") or "").strip()
    if snippet:
        sections.append(f"摘要: {snippet}")

    body = _extract_message_body(message.get("payload") or {})
    if body:
        if len(body) > BODY_LIMIT:
            body = body[:BODY_LIMIT].rstrip() + "..."
        sections.append(f"正文:\n{body}")

    attachments = _extract_attachments(message.get("payload") or {})
    if attachments:
        sections.append(f"附件: {', '.join(attachments[:10])}")

    return "\n".join(sections)


def _build_query(days: int) -> str:
    start = (datetime.now().astimezone() - timedelta(days=days)).date()
    return f"after:{start.strftime('%Y/%m/%d')} -in:spam -in:trash"


def collect_gmail_messages(user_email: str, days: int = 2, max_messages: int = DEFAULT_MAX_MESSAGES) -> dict:
    """Collect recent Gmail messages through the shared Google OAuth token."""
    service = _build_service(
        "gmail",
        "v1",
        required_scopes=GMAIL_SCOPES,
        missing_scope_message="Gmail 尚未完成读取授权，请在配置页重新授权 Google 数据源",
    )

    query = _build_query(days)
    collected: list[dict] = []
    page_token = None

    while len(collected) < max_messages:
        page_size = min(100, max_messages - len(collected))
        result = execute_google_request(
            service.users().messages().list(
                userId="me",
                q=query,
                maxResults=page_size,
                pageToken=page_token,
            ),
            GMAIL_API_SLUG,
            "Gmail API",
        )

        message_refs = result.get("messages", [])
        if not message_refs:
            break

        for ref in message_refs:
            if len(collected) >= max_messages:
                break
            message = execute_google_request(
                service.users().messages().get(
                    userId="me",
                    id=ref["id"],
                    format="full",
                ),
                GMAIL_API_SLUG,
                "Gmail API",
            )
            headers = _headers_to_dict((message.get("payload") or {}).get("headers"))
            timestamp = _parse_message_time(headers, message.get("internalDate"))
            subject = headers.get("subject") or "（无主题）"
            collected.append({
                "source": "gmail",
                "timestamp": timestamp.isoformat(),
                "title": subject,
                "content": _format_message_content(message, headers),
                "url": _message_url(user_email, message.get("id", ref["id"])),
                "message_id": message.get("id", ref["id"]),
                "thread_id": message.get("threadId"),
                "labels": message.get("labelIds", []),
                "query": query,
            })

        page_token = result.get("nextPageToken")
        if not page_token:
            break

    collected.sort(key=lambda item: item["timestamp"])
    dates = sorted({item["timestamp"][:10] for item in collected})
    logger.info("Collected %s Gmail messages for %s", len(collected), user_email)

    return {
        "events": collected,
        "total": len(collected),
        "date_range": [dates[0], dates[-1]] if dates else [],
        "query": query,
    }
