from sqlalchemy import select
from sqlalchemy.orm import Session

from sanad_api.models import ReviewEvent, Segment
from sanad_api.services.memory import upsert_memory_from_review
from sanad_api.services.risk import score_translation


def approve_segment(db: Session, segment_id: str, *, text: str | None, actor: str) -> Segment:
    segment = db.scalar(select(Segment).where(Segment.id == segment_id))
    if not segment or not segment.translation:
        raise ValueError("Segment or translation not found.")

    translation = segment.translation
    before = translation.approved_text or translation.candidate_text
    approved_text = (text if text is not None else translation.candidate_text).strip()
    if not approved_text:
        raise ValueError("Approved translation text must not be empty.")
    event_type = "edit_and_approve" if approved_text != translation.candidate_text else "approve"
    _refresh_risk(segment, approved_text)

    translation.candidate_text = approved_text
    translation.approved_text = approved_text
    translation.status = "approved"
    segment.status = "approved"

    event = ReviewEvent(
        document_id=segment.document_id,
        segment_id=segment.id,
        translation_id=translation.id,
        event_type=event_type,
        before_text=before,
        after_text=approved_text,
        actor=actor,
    )
    db.add(event)
    db.flush()

    memory_entry = upsert_memory_from_review(
        db,
        segment=segment,
        target_text=approved_text,
        review_event=event,
        actor=actor,
    )
    translation.memory_entry_id = memory_entry.id
    db.commit()
    db.refresh(segment)
    return segment


def approve_segment_globally(db: Session, segment_id: str, *, text: str | None, actor: str) -> tuple[Segment, int]:
    """Approve a segment and propagate the same translation to all identical unapproved segments in the document."""
    # 1. Approve the target segment
    main_segment = approve_segment(db, segment_id, text=text, actor=actor)
    source_text = main_segment.source_text
    document_id = main_segment.document_id
    approved_text = main_segment.translation.approved_text

    # 2. Find identical unapproved segments in the same document
    identical_segments = db.scalars(
        select(Segment).where(
            Segment.document_id == document_id,
            Segment.source_text == source_text,
            Segment.id != segment_id,
            Segment.status != "approved"
        )
    ).all()

    count = 0
    for other in identical_segments:
        # We use the same text for all
        approve_segment(db, other.id, text=approved_text, actor=actor)
        count += 1

    return main_segment, count


def update_candidate_translation(db: Session, segment_id: str, *, candidate_text: str) -> Segment:
    segment = db.scalar(select(Segment).where(Segment.id == segment_id))
    if not segment or not segment.translation:
        raise ValueError("Segment or translation not found.")

    translation = segment.translation
    before = translation.approved_text or translation.candidate_text
    cleaned = candidate_text.strip()
    if not cleaned:
        raise ValueError("Candidate translation text must not be empty.")

    was_approved = segment.status == "approved"
    translation.candidate_text = cleaned
    _refresh_risk(segment, cleaned)

    if was_approved:
        segment.status = "needs_review"
        translation.status = "needs_review"
        translation.approved_text = None
        translation.memory_entry_id = None
        segment.document.export_file_uri = None
    else:
        segment.status = "needs_review" if translation.risk_score else "pending"
        translation.status = "needs_review" if translation.risk_score else "candidate"

    db.add(
        ReviewEvent(
            document_id=segment.document_id,
            segment_id=segment.id,
            translation_id=translation.id,
            event_type="edit",
            before_text=before,
            after_text=cleaned,
            actor="demo-reviewer",
        )
    )
    db.commit()
    db.refresh(segment)
    return segment


def approve_unflagged(db: Session, document_id: str, *, actor: str = "demo-reviewer") -> int:
    segments = db.scalars(select(Segment).where(Segment.document_id == document_id)).all()
    count = 0
    for segment in segments:
        translation = segment.translation
        if not translation:
            continue
        if segment.status == "approved":
            continue
        if translation.risk_score != 0:
            continue
        approve_segment(db, segment.id, text=translation.candidate_text, actor=actor)
        count += 1
    return count


def _refresh_risk(segment: Segment, translated_text: str) -> None:
    if not segment.translation:
        return
    risk_score, risk_reasons = score_translation(
        source_text=segment.source_text,
        translated_text=translated_text,
        protected_entities=segment.protected_entities_json or [],
        glossary_hits=segment.glossary_hits_json or [],
    )
    segment.translation.risk_score = risk_score
    segment.translation.risk_reasons_json = risk_reasons
