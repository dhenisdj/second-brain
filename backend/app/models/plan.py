import uuid
from datetime import datetime, date
from sqlalchemy import String, Text, Date, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Plan(Base):
    __tablename__ = "plans"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    date: Mapped[date] = mapped_column(Date, index=True)
    summary_id: Mapped[str | None] = mapped_column(String, ForeignKey("daily_summaries.id"), nullable=True)
    items: Mapped[str] = mapped_column(Text, nullable=False)
    suggestions: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
