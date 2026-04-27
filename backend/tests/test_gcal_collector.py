from sqlalchemy import select

from app.models.event import Event
from app.services.gcal_collector import _html_to_text, _format_event_content
from app.services.ingest_service import ingest_gcal


class TestGCalContentCleaning:
    def test_html_to_text_keeps_main_content(self):
        raw = (
            '<p>zoom&nbsp;<a href="https://sea.zoom.us/j/123" target="_blank">'
            "<u><u>https://sea.zoom.us/j/123</u></u></a><br>"
            "一、需求进展；<br>二、DOD问题进展；"
            '<a href="https://docs.google.com/spreadsheets/d/abc">DOD</a></p>'
        )
        cleaned = _html_to_text(raw)

        assert "https://sea.zoom.us/j/123" in cleaned
        assert "一、需求进展；" in cleaned
        assert "二、DOD问题进展；" in cleaned
        assert "DOD (https://docs.google.com/spreadsheets/d/abc)" in cleaned
        assert "<a" not in cleaned

    def test_format_event_content_keeps_useful_sections(self):
        event = {
            "description": '<p>Discuss launch plan<br><a href="https://example.com/doc">Meeting Notes</a></p>',
            "attendees": [{"email": "alice@example.com", "responseStatus": "accepted"}],
            "location": "Room A",
            "attachments": [{"title": "Agenda"}],
        }

        content = _format_event_content(event)
        assert "Discuss launch plan" in content
        assert "Meeting Notes (https://example.com/doc)" in content
        assert "参会人:" in content
        assert "地点: Room A" in content
        assert "附件: Agenda" in content


class TestGCalIngestUpdate:
    async def test_reingest_updates_existing_event_content(self, db_session):
        await ingest_gcal(
            db_session,
            [
                {
                    "timestamp": "2026-04-21T16:00:00+08:00",
                    "title": "Weekly Catch Up",
                    "content": "<p>old html</p>",
                    "duration_minutes": 60,
                }
            ],
        )

        await ingest_gcal(
            db_session,
            [
                {
                    "timestamp": "2026-04-21T16:00:00+08:00",
                    "title": "Weekly Catch Up",
                    "content": "clean text",
                    "duration_minutes": 45,
                }
            ],
        )

        result = await db_session.execute(select(Event).where(Event.source == "gcal"))
        event = result.scalar_one()
        assert event.content == "clean text"
        assert event.duration_minutes == 45
