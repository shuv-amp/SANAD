import re
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload

from sanad_api.config import get_settings
from sanad_api.models import Document, ReviewEvent, Segment, Translation
from sanad_api.services.docx_io import parse_docx
from sanad_api.services.glossary import find_glossary_hits
from sanad_api.services.memory import find_memory_entry, record_memory_usage
from sanad_api.services.normalization import normalize_text
from sanad_api.services.pdf_document_io import PDF_DOCUMENT_TYPES, parse_pdf_document
from sanad_api.services.protection import detect_protected_entities
from sanad_api.services.providers import (
    ProviderContractError,
    TranslationBatchRequest,
    TranslationSegmentRequest,
    get_provider,
    validate_provider_results,
)
from sanad_api.services.risk import count_preserved_protected_entities, score_translation
from sanad_api.services.tabular_document_io import TABULAR_DOCUMENT_TYPES, parse_tabular_document
from sanad_api.services.text_document_io import TEXT_DOCUMENT_TYPES, parse_text_document

_HASH_LABEL_RE = re.compile(r"^\s*#\d+\s*$")


@dataclass(frozen=True)
class PreparedSegment:
    sequence: int
    segment_type: str
    source_text: str
    normalized_source: str
    location_json: dict
    protected_entities: list[dict]
    glossary_hits: list[dict]
    memory_entry_id: str | None
    memory_target_text: str | None
    translation_source_type: str
    provider_name: str
    candidate_text: str
    approved_text: str | None
    risk_score: float
    risk_reasons: list[dict]
    segment_status: str
    translation_status: str


async def process_document(db: Session, document: Document) -> Document:
    try:
        if document.file_type == "docx":
            parsed_segments = parse_docx(Path(document.original_file_uri))
        elif document.file_type in PDF_DOCUMENT_TYPES:
            parsed_segments = parse_pdf_document(Path(document.original_file_uri))
        elif document.file_type in TABULAR_DOCUMENT_TYPES:
            parsed_segments = parse_tabular_document(Path(document.original_file_uri), document.file_type)
        elif document.file_type in TEXT_DOCUMENT_TYPES:
            parsed_segments = parse_text_document(Path(document.original_file_uri), document.file_type)
        else:
            raise ValueError(f"SANAD does not support processing for file type {document.file_type!r}.")
    except Exception as exc:
        document.status = "failed"
        db.commit()
        if document.file_type == "docx":
            raise ValueError("Could not parse this DOCX. Use a simpler text-based DOCX fixture for the V1 demo.") from exc
        if document.file_type in PDF_DOCUMENT_TYPES:
            raise ValueError(
                "Could not parse this PDF. SANAD currently supports text-based PDFs, not scanned or image-only PDFs."
            ) from exc
        raise ValueError(
            f"Could not parse this {document.file_type.upper()} file. Use a cleaner text-based document or import it as DOCX."
        ) from exc

    if not parsed_segments:
        document.status = "failed"
        db.commit()
        raise ValueError(
            "No translatable text was found. SANAD does not support scanned/image-only files or empty documents."
        )

    document.status = "processing"
    db.flush()

    prepared_segments: list[PreparedSegment] = []
    unmatched: list[tuple[int, str, str, list[dict], list[dict]]] = []
    for parsed in parsed_segments:
        normalized_source = normalize_text(parsed.source_text)
        glossary_hits = find_glossary_hits(
            db,
            source_text=parsed.source_text,
            source_lang=document.source_lang,
            target_lang=document.target_lang,
            domain=document.domain,
            subdomain=document.subdomain,
        )
        protected_entities = detect_protected_entities(parsed.source_text, glossary_hits)
        memory_entry = find_memory_entry(
            db,
            source_lang=document.source_lang,
            target_lang=document.target_lang,
            domain=document.domain,
            subdomain=document.subdomain,
            normalized_source=normalized_source,
        )
        if memory_entry:
            prepared_segments.append(
                PreparedSegment(
                    sequence=parsed.sequence,
                    segment_type=parsed.segment_type,
                    source_text=parsed.source_text,
                    normalized_source=normalized_source,
                    location_json=parsed.location_json,
                    protected_entities=protected_entities,
                    glossary_hits=glossary_hits,
                    memory_entry_id=memory_entry.id,
                    memory_target_text=memory_entry.target_text,
                    translation_source_type="memory",
                    provider_name="translation_memory",
                    candidate_text=memory_entry.target_text,
                    approved_text=memory_entry.target_text,
                    risk_score=0,
                    risk_reasons=[],
                    segment_status="approved",
                    translation_status="memory_applied",
                )
            )
        else:
            unmatched.append(
                (
                    parsed.sequence,
                    parsed.segment_type,
                    parsed.source_text,
                    protected_entities,
                    glossary_hits,
                )
            )

    provider_results: dict[int, tuple[str, float, list[dict]]] = {}
    provider_tier_by_sequence: dict[int, str] = {}
    effective_provider_name = "fixture"
    if unmatched:
        try:
            provider = get_provider(get_settings().active_provider)
            effective_provider_name = provider.name
            request = TranslationBatchRequest(
                source_lang=document.source_lang,
                target_lang=document.target_lang,
                domain=document.domain,
                subdomain=document.subdomain,
                segments=[
                    TranslationSegmentRequest(
                        segment_id=str(sequence),
                        source_text=source_text,
                        protected_entities=protected_entities,
                        glossary_hits=glossary_hits,
                    )
                    for sequence, _, source_text, protected_entities, glossary_hits in unmatched
                ],
            )
            results = await provider.translate_batch(request)
            validate_provider_results(request, results)
        except (NotImplementedError, ProviderContractError, ValueError) as exc:
            document.status = "failed"
            db.commit()
            raise ValueError(f"Translation provider failed before review: {exc}") from exc

        provider_by_sequence = {int(result.segment_id): result.translated_text for result in results}
        for result in results:
            provider_tier_by_sequence[int(result.segment_id)] = getattr(result, "provider_tier", "unknown")
        for sequence, _, source_text, protected_entities, glossary_hits in unmatched:
            translated_text = _stabilize_structured_segment(source_text, provider_by_sequence[sequence])
            risk_score, risk_reasons = score_translation(
                source_text=source_text,
                translated_text=translated_text,
                protected_entities=protected_entities,
                glossary_hits=glossary_hits,
            )
            # Add info-level note when fixture fallback was used
            tier = provider_tier_by_sequence.get(sequence, "unknown")
            if tier == "fixture_fallback":
                risk_reasons = list(risk_reasons) + [{
                    "code": "api_fallback",
                    "label": "Offline fallback",
                    "detail": "Translation used offline fixture because the TMT API was unavailable.",
                }]
            provider_results[sequence] = (translated_text, risk_score, risk_reasons)

    for parsed in parsed_segments:
        if any(item.sequence == parsed.sequence for item in prepared_segments):
            continue
        normalized_source = normalize_text(parsed.source_text)
        glossary_hits = find_glossary_hits(
            db,
            source_text=parsed.source_text,
            source_lang=document.source_lang,
            target_lang=document.target_lang,
            domain=document.domain,
            subdomain=document.subdomain,
        )
        protected_entities = detect_protected_entities(parsed.source_text, glossary_hits)
        translated_text, risk_score, risk_reasons = provider_results[parsed.sequence]
        prepared_segments.append(
            PreparedSegment(
                sequence=parsed.sequence,
                segment_type=parsed.segment_type,
                source_text=parsed.source_text,
                normalized_source=normalized_source,
                location_json=parsed.location_json,
                protected_entities=protected_entities,
                glossary_hits=glossary_hits,
                memory_entry_id=None,
                memory_target_text=None,
                translation_source_type="provider",
                provider_name=provider_tier_by_sequence.get(parsed.sequence, effective_provider_name),
                candidate_text=translated_text,
                approved_text=None,
                risk_score=risk_score,
                risk_reasons=risk_reasons,
                segment_status="needs_review" if risk_score else "pending",
                translation_status="needs_review" if risk_score else "candidate",
            )
        )

    existing_segment_ids = db.scalars(select(Segment.id).where(Segment.document_id == document.id)).all()
    if existing_segment_ids:
        db.execute(delete(Translation).where(Translation.segment_id.in_(existing_segment_ids)))
    db.execute(delete(ReviewEvent).where(ReviewEvent.document_id == document.id))
    db.execute(delete(Segment).where(Segment.document_id == document.id))
    document.export_file_uri = None
    db.flush()

    for prepared in sorted(prepared_segments, key=lambda item: item.sequence):
        segment = Segment(
            document_id=document.id,
            sequence=prepared.sequence,
            segment_type=prepared.segment_type,
            source_text=prepared.source_text,
            normalized_source=prepared.normalized_source,
            location_json=prepared.location_json,
            protected_entities_json=prepared.protected_entities,
            glossary_hits_json=prepared.glossary_hits,
            status=prepared.segment_status,
        )
        db.add(segment)
        db.flush()
        if prepared.memory_entry_id:
            entry = find_memory_entry(
                db,
                source_lang=document.source_lang,
                target_lang=document.target_lang,
                domain=document.domain,
                subdomain=document.subdomain,
                normalized_source=prepared.normalized_source,
            )
            if entry:
                record_memory_usage(db, entry)

        db.add(
            Translation(
                segment_id=segment.id,
                candidate_text=prepared.candidate_text,
                approved_text=prepared.approved_text,
                source_type=prepared.translation_source_type,
                provider_name=prepared.provider_name,
                memory_entry_id=prepared.memory_entry_id,
                risk_score=prepared.risk_score,
                risk_reasons_json=prepared.risk_reasons,
                status=prepared.translation_status,
            )
        )

    document.status = "processed"
    db.commit()
    db.refresh(document)
    return document


def _stabilize_structured_segment(source_text: str, translated_text: str) -> str:
    if _HASH_LABEL_RE.fullmatch(source_text):
        return source_text.strip()
    return translated_text


def document_counts(db: Session, document_id: str) -> dict[str, int]:
    segments = _document_segments(db, document_id)
    counts = {
        "segments": len(segments),
        "approved": 0,
        "needs_review": 0,
        "pending": 0,
        "memory_applied": 0,
    }
    for segment in segments:
        if segment.translation and segment.translation.status == "memory_applied":
            counts["memory_applied"] += 1
        if segment.status == "approved":
            counts["approved"] += 1
        elif segment.status == "needs_review":
            counts["needs_review"] += 1
        else:
            counts["pending"] += 1
    return counts


def document_trust_summary(db: Session, document_id: str) -> dict[str, int]:
    segments = _document_segments(db, document_id)
    summary = {
        "total_segments": len(segments),
        "approved_segments": 0,
        "memory_reused_segments": 0,
        "protected_values_total": 0,
        "protected_values_preserved": 0,
        "unresolved_review_flags": 0,
    }

    for segment in segments:
        translation = segment.translation
        if segment.status == "approved":
            summary["approved_segments"] += 1
        if not translation:
            continue
        if translation.status == "memory_applied":
            summary["memory_reused_segments"] += 1

        effective_text = (translation.approved_text or translation.candidate_text or "").strip()
        if effective_text and segment.protected_entities_json:
            preserved, total = count_preserved_protected_entities(segment.protected_entities_json, effective_text)
            summary["protected_values_preserved"] += preserved
            summary["protected_values_total"] += total

        if segment.status != "approved" and translation.risk_reasons_json:
            summary["unresolved_review_flags"] += 1

    return summary


def _document_segments(db: Session, document_id: str) -> list[Segment]:
    return db.scalars(
        select(Segment)
        .where(Segment.document_id == document_id)
        .options(selectinload(Segment.translation))
        .order_by(Segment.sequence)
    ).all()
