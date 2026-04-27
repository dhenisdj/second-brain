import uuid
from datetime import datetime
from sqlalchemy import String, Text, Float, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Analysis(Base):
    __tablename__ = "analyses"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    event_id: Mapped[str] = mapped_column(String, ForeignKey("events.id", ondelete="CASCADE"), index=True)
    category: Mapped[str] = mapped_column(String, nullable=False)
    intent: Mapped[str] = mapped_column(Text, nullable=False)
    tags: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    event: Mapped["Event"] = relationship("Event", back_populates="analyses")
