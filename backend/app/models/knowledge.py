import uuid
from datetime import date
from sqlalchemy import String, Text, Integer, Float, Date, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class KGNode(Base):
    __tablename__ = "kg_nodes"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    type: Mapped[str] = mapped_column(String, nullable=False)
    properties: Mapped[str | None] = mapped_column(Text, nullable=True)
    first_seen: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_seen: Mapped[date | None] = mapped_column(Date, nullable=True)
    mention_count: Mapped[int] = mapped_column(Integer, default=0)


class KGEdge(Base):
    __tablename__ = "kg_edges"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    source_id: Mapped[str] = mapped_column(String, ForeignKey("kg_nodes.id"), index=True)
    target_id: Mapped[str] = mapped_column(String, ForeignKey("kg_nodes.id"), index=True)
    relation: Mapped[str] = mapped_column(String, nullable=False)
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    context: Mapped[str | None] = mapped_column(Text, nullable=True)


class KGEvidence(Base):
    __tablename__ = "kg_evidences"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    node_id: Mapped[str] = mapped_column(String, ForeignKey("kg_nodes.id"), index=True)
    summary_id: Mapped[str | None] = mapped_column(String, ForeignKey("daily_summaries.id"), nullable=True, index=True)
    event_id: Mapped[str | None] = mapped_column(String, ForeignKey("events.id"), nullable=True, index=True)
    source_type: Mapped[str] = mapped_column(String, nullable=False)
    mention_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
