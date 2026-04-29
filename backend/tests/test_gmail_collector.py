import base64
from sqlalchemy import select

from app.models.event import Event
from app.services.gmail_collector import _extract_message_body, _format_message_content
from app.services.ingest_service import ingest_gmail


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii").rstrip("=")


class TestGmailContentExtraction:
    def test_extract_message_body_prefers_plain_text(self):
        payload = {
            "mimeType": "multipart/alternative",
            "parts": [
                {"mimeType": "text/html", "body": {"data": _b64("<p>HTML body</p>")}},
                {"mimeType": "text/plain", "body": {"data": _b64("Plain body\nwith details")}},
            ],
        }

        assert _extract_message_body(payload) == "Plain body\nwith details"

    def test_format_message_content_keeps_message_metadata(self):
        message = {
            "snippet": "Approval reminder",
            "labelIds": ["INBOX"],
            "payload": {
                "mimeType": "multipart/mixed",
                "parts": [
                    {"mimeType": "text/plain", "body": {"data": _b64("Please review the Kafka request")}},
                    {"filename": "request.pdf", "mimeType": "application/pdf", "body": {}},
                ],
            },
        }
        headers = {
            "from": "alice@example.com",
            "to": "bob@example.com",
            "subject": "Kafka approval",
        }

        content = _format_message_content(message, headers)
        assert "发件人: alice@example.com" in content
        assert "收件人: bob@example.com" in content
        assert "摘要: Approval reminder" in content
        assert "Please review the Kafka request" in content
        assert "附件: request.pdf" in content


class TestGmailIngestUpdate:
    async def test_reingest_updates_existing_message_by_url(self, db_session):
        event = {
            "timestamp": "2026-04-21T16:00:00+08:00",
            "title": "Kafka approval",
            "content": "old content",
            "url": "https://mail.google.com/mail/u/test@example.com/#all/msg-1",
            "message_id": "msg-1",
        }
        await ingest_gmail(db_session, [event])

        await ingest_gmail(db_session, [{**event, "content": "new content"}])

        result = await db_session.execute(select(Event).where(Event.source == "gmail"))
        stored = result.scalar_one()
        assert stored.content == "new content"
