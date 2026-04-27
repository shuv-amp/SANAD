from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from sanad_api.models import MemoryEntry, ReviewEvent, Segment
from sanad_api.services.normalization import normalize_text


def find_memory_entry(
    db: Session,
    *,
    source_lang: str,
    target_lang: str,
    domain: str,
    subdomain: str,
    normalized_source: str,
) -> MemoryEntry | None:
    entry = db.scalar(
        select(MemoryEntry).where(
            MemoryEntry.is_active.is_(True),
            MemoryEntry.source_lang == source_lang,
            MemoryEntry.target_lang == target_lang,
            MemoryEntry.domain == domain,
            MemoryEntry.subdomain == subdomain,
            MemoryEntry.normalized_source == normalized_source,
        )
    )
    return entry


def record_memory_usage(db: Session, entry: MemoryEntry) -> MemoryEntry:
    if entry:
        entry.times_used += 1
        entry.last_used_at = datetime.now(UTC)
        db.flush()
    return entry


def lookup_memory(
    db: Session,
    *,
    source_lang: str,
    target_lang: str,
    domain: str,
    subdomain: str,
    normalized_source: str,
) -> MemoryEntry | None:
    entry = find_memory_entry(
        db,
        source_lang=source_lang,
        target_lang=target_lang,
        domain=domain,
        subdomain=subdomain,
        normalized_source=normalized_source,
    )
    if entry:
        record_memory_usage(db, entry)
    return entry


def upsert_memory_from_review(
    db: Session,
    *,
    segment: Segment,
    target_text: str,
    review_event: ReviewEvent,
    actor: str,
) -> MemoryEntry:
    document = segment.document
    normalized_source = normalize_text(segment.source_text)
    entry = db.scalar(
        select(MemoryEntry).where(
            MemoryEntry.is_active.is_(True),
            MemoryEntry.source_lang == document.source_lang,
            MemoryEntry.target_lang == document.target_lang,
            MemoryEntry.domain == document.domain,
            MemoryEntry.subdomain == document.subdomain,
            MemoryEntry.normalized_source == normalized_source,
        )
    )
    if entry:
        entry.target_text = target_text
        entry.approved_by = actor
        entry.approved_at = datetime.now(UTC)
        entry.created_from_document_id = document.id
        entry.created_from_segment_id = segment.id
        entry.created_from_review_event_id = review_event.id
        return entry

    entry = MemoryEntry(
        source_lang=document.source_lang,
        target_lang=document.target_lang,
        domain=document.domain,
        subdomain=document.subdomain,
        source_text=segment.source_text,
        normalized_source=normalized_source,
        target_text=target_text,
        created_from_document_id=document.id,
        created_from_segment_id=segment.id,
        created_from_review_event_id=review_event.id,
        approved_by=actor,
    )
    db.add(entry)
    db.flush()
    return entry
