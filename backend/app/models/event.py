import uuid
from datetime import datetime
from sqlalchemy import String, Text, Integer, DateTime, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Event(Base):
    __tablename__ = "events"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    source: Mapped[str] = mapped_column(String, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str | None] = mapped_column(String, nullable=True)
    duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    raw_data: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    analyses: Mapped[list["Analysis"]] = relationship("Analysis", back_populates="event", cascade="all, delete-orphan")
