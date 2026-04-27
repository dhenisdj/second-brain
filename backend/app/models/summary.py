import uuid
from datetime import datetime, date
from sqlalchemy import String, Text, Date, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class DailySummary(Base):
    __tablename__ = "daily_summaries"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    date: Mapped[date] = mapped_column(Date, unique=True, index=True)
    timeline_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    progress_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    knowledge_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    time_distribution: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_llm_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
