import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sanad_api.database import Base


def uuid_str() -> str:
    return str(uuid.uuid4())


def utc_now() -> datetime:
    return datetime.now(UTC)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class Document(Base, TimestampMixin):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_type: Mapped[str] = mapped_column(String(16), nullable=False)
    source_lang: Mapped[str] = mapped_column(String(32), nullable=False)
    target_lang: Mapped[str] = mapped_column(String(32), nullable=False)
    domain: Mapped[str] = mapped_column(String(96), nullable=False)
    subdomain: Mapped[str] = mapped_column(String(96), default="__none__", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="uploaded", nullable=False)
    original_file_uri: Mapped[str] = mapped_column(Text, nullable=False)
    export_file_uri: Mapped[str | None] = mapped_column(Text)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    doc_metadata: Mapped[dict] = mapped_column("metadata_json", JSON, default=dict, nullable=False)

    segments: Mapped[list["Segment"]] = relationship(back_populates="document", cascade="all, delete-orphan")
    review_events: Mapped[list["ReviewEvent"]] = relationship(back_populates="document", cascade="all, delete-orphan")


class Segment(Base, TimestampMixin):
    __tablename__ = "segments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    segment_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_text: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_source: Mapped[str] = mapped_column(Text, nullable=False)
    location_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    protected_entities_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    glossary_hits_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)

    document: Mapped[Document] = relationship(back_populates="segments")
    translation: Mapped["Translation | None"] = relationship(
        back_populates="segment", cascade="all, delete-orphan", uselist=False
    )

    __table_args__ = (Index("ix_segments_document_sequence", "document_id", "sequence"),)


class Translation(Base, TimestampMixin):
    __tablename__ = "translations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    segment_id: Mapped[str] = mapped_column(ForeignKey("segments.id", ondelete="CASCADE"), unique=True, nullable=False)
    candidate_text: Mapped[str] = mapped_column(Text, nullable=False)
    approved_text: Mapped[str | None] = mapped_column(Text)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_name: Mapped[str] = mapped_column(String(64), nullable=False)
    memory_entry_id: Mapped[str | None] = mapped_column(ForeignKey("memory_entries.id"))
    risk_score: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    risk_reasons_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="candidate", nullable=False)

    segment: Mapped[Segment] = relationship(back_populates="translation")
    memory_entry: Mapped["MemoryEntry | None"] = relationship()


class MemoryEntry(Base, TimestampMixin):
    __tablename__ = "memory_entries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    source_lang: Mapped[str] = mapped_column(String(32), nullable=False)
    target_lang: Mapped[str] = mapped_column(String(32), nullable=False)
    domain: Mapped[str] = mapped_column(String(96), nullable=False)
    subdomain: Mapped[str] = mapped_column(String(96), default="__none__", nullable=False)
    source_text: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_source: Mapped[str] = mapped_column(Text, nullable=False)
    target_text: Mapped[str] = mapped_column(Text, nullable=False)
    created_from_document_id: Mapped[str | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"))
    created_from_segment_id: Mapped[str | None] = mapped_column(ForeignKey("segments.id", ondelete="SET NULL"))
    created_from_review_event_id: Mapped[str | None] = mapped_column(ForeignKey("review_events.id", ondelete="SET NULL"))
    approved_by: Mapped[str] = mapped_column(String(96), default="demo-reviewer", nullable=False)
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    times_used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    source_document: Mapped[Document | None] = relationship(foreign_keys=[created_from_document_id])

    __table_args__ = (
        Index(
            "uq_memory_active_scope",
            "source_lang",
            "target_lang",
            "domain",
            "subdomain",
            "normalized_source",
            unique=True,
            sqlite_where=text("is_active = 1"),
            postgresql_where=text("is_active = true"),
        ),
    )


class ReviewEvent(Base):
    __tablename__ = "review_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    segment_id: Mapped[str] = mapped_column(ForeignKey("segments.id", ondelete="CASCADE"), nullable=False)
    translation_id: Mapped[str] = mapped_column(ForeignKey("translations.id", ondelete="CASCADE"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    before_text: Mapped[str | None] = mapped_column(Text)
    after_text: Mapped[str] = mapped_column(Text, nullable=False)
    actor: Mapped[str] = mapped_column(String(96), default="demo-reviewer", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    document: Mapped[Document] = relationship(back_populates="review_events")


class GlossaryTerm(Base, TimestampMixin):
    __tablename__ = "glossary_terms"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    source_lang: Mapped[str] = mapped_column(String(32), nullable=False)
    target_lang: Mapped[str] = mapped_column(String(32), nullable=False)
    domain: Mapped[str] = mapped_column(String(96), nullable=False)
    subdomain: Mapped[str] = mapped_column(String(96), default="__none__", nullable=False)
    source_term: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_source_term: Mapped[str] = mapped_column(String(255), nullable=False)
    target_term: Mapped[str] = mapped_column(String(255), nullable=False)
    term_type: Mapped[str] = mapped_column(String(48), default="term", nullable=False)
    case_sensitive: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "source_lang",
            "target_lang",
            "domain",
            "subdomain",
            "normalized_source_term",
            name="uq_glossary_scope_term",
        ),
    )


class Job(Base, TimestampMixin):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    job_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
