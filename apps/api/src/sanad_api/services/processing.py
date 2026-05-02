import re
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload

print("✅ sanad_api.services.processing module loaded")

from sanad_api.config import get_settings
from sanad_api.models import Document, ReviewEvent, Segment, Translation
from sanad_api.services.docx_io import ParsedSegment, parse_docx
from sanad_api.services.glossary import find_glossary_hits
from sanad_api.services.memory import find_memory_entry, record_memory_usage
from sanad_api.services.normalization import contains_devanagari, digits_to_ascii, normalize_text, to_devanagari_digits
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
_NUMERIC_LABEL_RE = re.compile(r"^\s*\d+(?:[.,:/-]\d+)*\s*$")
_SECTION_LABEL_RE = re.compile(r"^\s*\d+(?:\.\d+){1,4}\s*$")
_ROMAN_LABEL_RE = re.compile(r"^\s*[ivxlcdmIVXLCDM]{1,8}\s*$")
_DOT_LEADER_RE = re.compile(r"^\s*[.\u00b7•\-–—\s]{3,}\s*$")
_BULLET_ONLY_RE = re.compile(r"^\s*[•\-–—]\s*$")
_DATE_ENTITY_RE = re.compile(r"\b(?:\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]\d{2,4})\b")


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
    raw_candidate_text: str | None
    approved_text: str | None
    risk_score: float
    risk_reasons: list[dict]
    segment_status: str
    translation_status: str
    is_repaired: bool = False


async def process_document(db: Session, document: Document, *, progressive: bool = False) -> Document:
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
        logger.exception(f"❌ Document {document.id} processing failed: {exc}")
        document.status = "failed"
        document.doc_metadata = {
            **(document.doc_metadata or {}),
            "processing_error": str(exc),
        }
        db.commit()
        if document.file_type == "docx":
            raise ValueError("Could not parse this DOCX. Ensure it is a valid text-based DOCX file.") from exc
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
        stable_candidate = _stable_structured_candidate(parsed.source_text)
        if stable_candidate is not None:
            risk_score, risk_reasons = score_translation(
                source_text=parsed.source_text,
                translated_text=stable_candidate,
                protected_entities=protected_entities,
                glossary_hits=glossary_hits,
                target_lang=document.target_lang,
            )
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
                    translation_source_type="preserved",
                    provider_name="sanad_structural_preserve",
                    candidate_text=stable_candidate,
                    raw_candidate_text=stable_candidate,
                    approved_text=None,
                    risk_score=risk_score,
                    risk_reasons=risk_reasons,
                    segment_status="pending" if risk_score == 0 else "needs_review",
                    translation_status="candidate" if risk_score == 0 else "needs_review",
                    is_repaired=stable_candidate != parsed.source_text,
                )
            )
            if stable_candidate != parsed.source_text:
                print(f"[SANAD-AUDIT] Fast-track segment #{parsed.sequence} REPAIRED (localized)")
            continue
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
                    raw_candidate_text=memory_entry.target_text,
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

    document.doc_metadata = {
        **(document.doc_metadata or {}),
        "processing": {
            "total_segments": len(parsed_segments),
            "local_segments": len(prepared_segments),
            "provider_segments": len(unmatched),
        },
    }
    db.commit()
    db.refresh(document)

    if progressive:
        _reset_document_segments(db, document)
        prepared_by_sequence = {item.sequence: item for item in prepared_segments}
        for parsed in parsed_segments:
            prepared = prepared_by_sequence.get(parsed.sequence)
            if prepared:
                _insert_prepared_segment(db, document, prepared)
            else:
                _insert_placeholder_segment(db, document, parsed)
        db.commit()
        db.refresh(document)

    provider_results: dict[int, tuple[str, float, list[dict]]] = {}
    provider_tier_by_sequence: dict[int, str] = {}
    effective_provider_name = "fixture"
    if unmatched:
        try:
            provider = get_provider(get_settings().active_provider)
            effective_provider_name = provider.name
            completed_provider_segments = 0
            chunk_size = get_settings().tmt_provider_batch_size if progressive else len(unmatched)
            provider_chunks = (
                _progressive_provider_chunks(unmatched, chunk_size, get_settings().tmt_concurrency)
                if progressive
                else [unmatched]
            )
            for chunk in provider_chunks:
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
                        for sequence, _, source_text, protected_entities, glossary_hits in chunk
                    ],
                )
                results = await provider.translate_batch(request)
                for r in results:
                    if r.error:
                        print(f"❌ process_document Segment {r.segment_id} FAILED: {r.error}")
                validate_provider_results(request, results)
                provider_by_sequence = {}
                for result in results:
                    try:
                        provider_by_sequence[int(result.segment_id)] = result.translated_text
                    except (ValueError, TypeError) as exc:
                        print(f"❌ process_document ID conversion FAILED for '{result.segment_id}': {exc}")
                        raise
                for result in results:
                    provider_tier_by_sequence[int(result.segment_id)] = getattr(result, "provider_tier", "unknown")
                for sequence, segment_type, source_text, protected_entities, glossary_hits in chunk:
                    # Add source len for position shift detection
                    source_len = len(source_text)
                    enhanced_entities = [
                        {**e, "segment_source_len": source_len} for e in (protected_entities or [])
                    ]
                    raw_provider_text = provider_by_sequence[sequence]
                    raw_translated_text = raw_provider_text # TRUE RAW
                    translated_text, was_stabilized = _stabilize_structured_segment(
                        source_text, 
                        raw_provider_text,
                        protected_entities=enhanced_entities,
                        glossary_hits=glossary_hits,
                        target_lang=document.target_lang
                    )
                    translated_text = _strip_ai_chatter(translated_text)
                    risk_score, risk_reasons = score_translation(
                        source_text=source_text,
                        translated_text=translated_text,
                        protected_entities=enhanced_entities,
                        glossary_hits=glossary_hits,
                        target_lang=document.target_lang,
                    )
                    tier = provider_tier_by_sequence.get(sequence, "unknown")
                    if tier == "fixture_fallback":
                        risk_reasons = list(risk_reasons) + [{
                            "code": "api_fallback",
                            "label": "Offline fallback",
                            "detail": "Translation used offline fixture because the TMT API was unavailable.",
                        }]
                    
                    # --- Integrity Repair Pass ---
                    repaired_text = translated_text
                    is_repaired = was_stabilized
                    
                    repairable_reasons = [r for r in risk_reasons if r.get("repairable")]
                    if risk_score > 0 and repairable_reasons:
                        repaired_text, repair_flag = await _attempt_auto_repair(
                            provider,
                            document,
                            source_text,
                            translated_text,
                            risk_reasons,
                            enhanced_entities,
                            glossary_hits
                        )
                        if repair_flag and repaired_text != translated_text:
                            # Re-score after repair
                            new_risk_score, new_risk_reasons = score_translation(
                                source_text=source_text,
                                translated_text=repaired_text,
                                protected_entities=enhanced_entities,
                                glossary_hits=glossary_hits,
                                target_lang=document.target_lang,
                            )
                            if new_risk_score < risk_score:
                                # Improvement! Use repaired version
                                translated_text = repaired_text
                                risk_score = new_risk_score
                                risk_reasons = list(new_risk_reasons) + [{
                                    "code": "self_repaired",
                                    "label": "Self-repaired",
                                    "severity": "low",
                                    "detail": "SANAD detected an AI failure and automatically repaired the translation.",
                                }]
                                is_repaired = True
                    
                    # --- Master Sanitization (Hard-Surgical Fixes) ---
                    sanitized_text, was_sanitized = _apply_master_sanitization(source_text, translated_text, document.target_lang)
                    if was_sanitized:
                        translated_text = sanitized_text
                        is_repaired = True
                        # Final re-score if sanitized
                        risk_score, risk_reasons = score_translation(
                            source_text=source_text,
                            translated_text=translated_text,
                            protected_entities=enhanced_entities,
                            glossary_hits=glossary_hits,
                            target_lang=document.target_lang,
                        )
                    # ---------------------------------
                    
                    parsed = parsed_segments[sequence - 1]
                    prepared = PreparedSegment(
                        sequence=sequence,
                        segment_type=segment_type,
                        source_text=source_text,
                        normalized_source=normalize_text(source_text),
                        location_json=parsed.location_json,
                        protected_entities=enhanced_entities,
                        glossary_hits=glossary_hits,
                        memory_entry_id=None,
                        memory_target_text=None,
                        translation_source_type="provider",
                        provider_name=provider_tier_by_sequence.get(sequence, effective_provider_name),
                        candidate_text=translated_text,
                        raw_candidate_text=raw_translated_text,
                        approved_text=None,
                        risk_score=risk_score,
                        risk_reasons=risk_reasons,
                        segment_status="needs_review" if risk_score else "pending",
                        translation_status="needs_review" if risk_score else "candidate",
                        is_repaired=is_repaired,
                    )
                    
                    if progressive:
                        _upsert_prepared_segment(db, document, prepared)
                    else:
                        prepared_segments.append(prepared)
                        provider_results[sequence] = (translated_text, risk_score, risk_reasons)
                
                if progressive:
                    completed_provider_segments += len(chunk)
                    document.doc_metadata = {
                        **(document.doc_metadata or {}),
                        "processing": {
                            "total_segments": len(parsed_segments),
                            "local_segments": len(prepared_segments) + completed_provider_segments,
                            "provider_segments": len(unmatched),
                        },
                    }
                    # COMMIT ONCE PER CHUNK (instead of per segment)
                    db.commit()
        except (NotImplementedError, ProviderContractError, ValueError) as exc:
            document.status = "failed"
            db.commit()
            raise ValueError(f"Translation provider failed before review: {exc}") from exc

    if progressive:
        document.status = "processed"
        document.doc_metadata = {key: value for key, value in (document.doc_metadata or {}).items() if key != "processing"}
        db.commit()
        db.refresh(document)
        return document

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
                is_repaired=is_repaired,
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
                raw_candidate_text=prepared.raw_candidate_text,
                approved_text=prepared.approved_text,
                source_type=prepared.translation_source_type,
                provider_name=prepared.provider_name,
                memory_entry_id=prepared.memory_entry_id,
                risk_score=prepared.risk_score,
                risk_reasons_json=prepared.risk_reasons,
                status=prepared.translation_status, is_repaired=prepared.is_repaired,
            )
        )

    document.status = "processed"
    document.doc_metadata = {key: value for key, value in (document.doc_metadata or {}).items() if key != "processing"}
    db.commit()
    db.refresh(document)
    return document


def _processing_chunks(items: list, size: int) -> list[list]:
    chunk_size = max(1, size)
    return [items[index:index + chunk_size] for index in range(0, len(items), chunk_size)]


def _progressive_provider_chunks(items: list, regular_size: int, first_size: int) -> list[list]:
    if not items:
        return []
    first_chunk_size = max(1, min(len(items), first_size, regular_size))
    return [items[:first_chunk_size], *_processing_chunks(items[first_chunk_size:], regular_size)]


def _reset_document_segments(db: Session, document: Document) -> None:
    existing_segment_ids = db.scalars(select(Segment.id).where(Segment.document_id == document.id)).all()
    if existing_segment_ids:
        db.execute(delete(Translation).where(Translation.segment_id.in_(existing_segment_ids)))
    db.execute(delete(ReviewEvent).where(ReviewEvent.document_id == document.id))
    db.execute(delete(Segment).where(Segment.document_id == document.id))
    document.export_file_uri = None
    db.flush()


def _insert_placeholder_segment(db: Session, document: Document, parsed: ParsedSegment) -> Segment:
    glossary_hits = find_glossary_hits(
        db,
        source_text=parsed.source_text,
        source_lang=document.source_lang,
        target_lang=document.target_lang,
        domain=document.domain,
        subdomain=document.subdomain,
    )
    segment = Segment(
        document_id=document.id,
        sequence=parsed.sequence,
        segment_type=parsed.segment_type,
        source_text=parsed.source_text,
        normalized_source=normalize_text(parsed.source_text),
        location_json=parsed.location_json,
        protected_entities_json=detect_protected_entities(parsed.source_text, glossary_hits),
        glossary_hits_json=glossary_hits,
        status="pending",
    )
    db.add(segment)
    db.flush()
    return segment


def _insert_prepared_segment(db: Session, document: Document, prepared: PreparedSegment) -> Segment:
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
    _add_or_update_translation(db, segment, prepared)
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
    return segment


def _upsert_prepared_segment(db: Session, document: Document, prepared: PreparedSegment) -> Segment:
    segment = db.scalar(
        select(Segment).where(Segment.document_id == document.id, Segment.sequence == prepared.sequence)
    )
    if not segment:
        return _insert_prepared_segment(db, document, prepared)
    segment.segment_type = prepared.segment_type
    segment.source_text = prepared.source_text
    segment.normalized_source = prepared.normalized_source
    segment.location_json = prepared.location_json
    segment.protected_entities_json = prepared.protected_entities
    segment.glossary_hits_json = prepared.glossary_hits
    segment.status = prepared.segment_status
    _add_or_update_translation(db, segment, prepared)
    db.flush()
    return segment


def _add_or_update_translation(db: Session, segment: Segment, prepared: PreparedSegment) -> None:
    translation = segment.translation
    if translation is None:
        db.add(
            Translation(
                segment_id=segment.id,
                candidate_text=prepared.candidate_text,
                raw_candidate_text=prepared.raw_candidate_text,
                approved_text=prepared.approved_text,
                source_type=prepared.translation_source_type,
                provider_name=prepared.provider_name,
                memory_entry_id=prepared.memory_entry_id,
                risk_score=prepared.risk_score,
                risk_reasons_json=prepared.risk_reasons,
                status=prepared.translation_status, is_repaired=prepared.is_repaired,
            )
        )
        return
    translation.candidate_text = prepared.candidate_text
    translation.raw_candidate_text = prepared.raw_candidate_text
    translation.approved_text = prepared.approved_text
    translation.source_type = prepared.translation_source_type
    translation.provider_name = prepared.provider_name
    translation.memory_entry_id = prepared.memory_entry_id
    translation.risk_score = prepared.risk_score
    translation.risk_reasons_json = prepared.risk_reasons
    translation.status = prepared.translation_status
    translation.is_repaired = prepared.is_repaired


def _stabilize_structured_segment(
    source_text: str, 
    translated_text: str,
    protected_entities: list[dict] | None = None,
    glossary_hits: list[dict] | None = None,
    target_lang: str = "ne"
) -> tuple[str, bool]:
    # 1. If the provider returned something that already passes risk checks perfectly, keep it.
    if protected_entities is not None:
        provider_risk, _ = score_translation(
            source_text=source_text,
            translated_text=translated_text,
            protected_entities=protected_entities,
            glossary_hits=glossary_hits or [],
            target_lang="en" # Default for stabilization
        )
        if provider_risk == 0:
            return translated_text, False

    # 2. If the provider's translation has risk (e.g. malformed date), 
    # check if our localization fallback is safer.
    localized_source = to_devanagari_digits(source_text)
    if localized_source != source_text:
        # If the provider just returned the English source exactly, 
        # or returned something with risk, let's see if our fallback is better.
        if protected_entities is not None:
            fallback_risk, _ = score_translation(
                source_text=source_text,
                translated_text=localized_source,
                protected_entities=protected_entities,
                glossary_hits=glossary_hits or [],
                target_lang="en" # Default for stabilization
            )
            # If our fallback is safer (zero risk vs provider risk), use it!
            if fallback_risk < provider_risk:
                return localized_source, True
        else:
            # Simple fallback if we don't have risk metrics
            if translated_text.strip() == source_text.strip():
                return localized_source, True

    # 3. Otherwise, check for traditional stabilization (protecting labels like #1, 1.1, etc.)
    stable_candidate = _stable_structured_candidate(source_text)
    
    # 4. Final Script Normalization Pass
    final_text = stable_candidate if stable_candidate is not None else translated_text
    
    # Surgical Preservation: Ensure IDs, Phones, URLs, and Emails maintain structural integrity
    if protected_entities:
        for entity in protected_entities:
            kind = entity.get("kind")
            source_val = entity.get("text", "")
            
            # If the source value is already in the final text (maybe localized), we might leave it.
            # But if it's a PHONE or ID, we want the EXACT source digits/formatting if the AI mangled it.
            if kind in {"phone", "id", "url", "email"}:
                # If the AI return has a "broken" version of the source value
                # (e.g. source '+977-123' -> target '977/123+')
                # we surgically restore it.
                t_ascii = digits_to_ascii(final_text)
                s_ascii = digits_to_ascii(source_val)
                
                if s_ascii not in t_ascii:
                    # Check if the AI at least got the digits right
                    s_digits = "".join(filter(str.isdigit, s_ascii))
                    t_digits = "".join(filter(str.isdigit, t_ascii))
                    
                    # AGGRESSIVE FIX: For Phone/ID, the source is the ONLY truth.
                    # Even if digits don't match perfectly (AI made a typo like 977 -> 997),
                    # we force-restore the source value if the segment is short.
                    if kind in {"phone", "id"} and len(final_text) < len(source_val) * 2:
                        print(f"[SURGICAL-AGGRESSIVE] Overriding {kind} hallucination: {final_text} -> {source_val}")
                        final_text = source_val
                    elif s_digits and s_digits in t_digits:
                        # Standard case: digits are there, just formatting is mangled
                        if len(final_text) < len(source_val) * 1.5:
                            print(f"[SURGICAL-FIX] Restoring {kind} formatting: {source_val}")
                            final_text = source_val
                else:
                    # Even if it matches in ASCII, we might want to enforce Latin for URLs/Emails
                    if kind in {"url", "email"}:
                        final_text = final_text.replace(to_devanagari_digits(source_val), source_val)

    # 5. Global Localization (Target-Script Digits)
    if target_lang.lower() == "en":
        # Target is English: Enforce ASCII digits
        localized_final = digits_to_ascii(final_text)
    else:
        # Target is Nepali/Tamang: Enforce Devanagari digits
        localized_final = to_devanagari_digits(final_text)
    
    # Restore original Latin text for URLs/Emails specifically
    if protected_entities:
        for entity in protected_entities:
            if entity.get("kind") in {"url", "email"}:
                val = entity.get("text", "")
                # If target is English, they are already Latin. 
                # If target is Nepali, we ensure they aren't Devanagari-fied.
                if target_lang.lower() != "en":
                    localized_final = localized_final.replace(to_devanagari_digits(val), val)
                    
    was_stabilized = stable_candidate is not None or localized_final != translated_text
    return localized_final, was_stabilized


def _stable_structured_candidate(source_text: str) -> str | None:
    text = source_text.strip()
    if not text:
        return None
    if _DATE_ENTITY_RE.search(text):
        return None
    if _HASH_LABEL_RE.fullmatch(text):
        return to_devanagari_digits(text)
    if _NUMERIC_LABEL_RE.fullmatch(text):
        return to_devanagari_digits(text)
    if _SECTION_LABEL_RE.fullmatch(text):
        return to_devanagari_digits(text)
    if _ROMAN_LABEL_RE.fullmatch(text):
        return text
    if _BULLET_ONLY_RE.fullmatch(text):
        return text
    if _DOT_LEADER_RE.fullmatch(text) and any(mark in text for mark in ".·•"):
        return text
    return None


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
async def _attempt_auto_repair(
    provider,
    document,
    source_text: str,
    failed_translation: str,
    risk_reasons: list[dict],
    protected_entities: list[dict],
    glossary_hits: list[dict]
) -> tuple[str, bool]:
    """Genius auto-repair logic with post-repair validation and structural guards."""
    from sanad_api.services.risk import score_translation # Circular import avoidance
    
    codes = {r["code"] for r in risk_reasons}
    repair_instruction = "CRITICAL: Fix the following issues in your translation. Return ONLY the fixed translation."
    
    # 1. Build targeted instructions
    if "length_deviation" in codes:
        repair_instruction += "\n- The translation was incomplete. Provide the full translation for the entire text."
    
    missing_numbers = [r["detail"] for r in risk_reasons if r["code"] == "changed_number"]
    if missing_numbers:
        repair_instruction += f"\n- MANDATORY: Fix numbers. Ensure these values are present exactly: {', '.join(missing_numbers)}"
    
    if "currency_suboptimal" in codes:
        repair_instruction += "\n- MANDATORY: Use 'रु' (the official symbol) for currency, not 'एनपीआर'."
    
    if "polarity_flip" in codes:
        repair_instruction += "\n- MANDATORY: The meaning was REVERSED (Positive/Negative). Fix the negation."
        
    if "hallucination_repetition" in codes:
        repair_instruction += "\n- MANDATORY: STOP REPEATING WORDS. A word was repeated twice consecutively (e.g. 'मूल्य मूल्य'). Provide only the single, correct term."
    
    if "ghost_entity" in codes:
        repair_instruction += "\n- MANDATORY: Remove names or Latin words that are not in the source text."

    if "untranslated_segment" in codes:
        repair_instruction += "\n- MANDATORY: This segment was left in English. Translate it fully into the target language."
    
    # 2. Call Provider for Repair
    try:
        repair_request = TranslationBatchRequest(
            source_lang=document.source_lang,
            target_lang=document.target_lang,
            domain=document.domain,
            subdomain=document.subdomain,
            segments=[
                TranslationSegmentRequest(
                    segment_id="repair",
                    source_text=f"### INSTRUCTION: {repair_instruction}\n\nSOURCE: {source_text}\nFAILED ATTEMPT: {failed_translation}",
                    protected_entities=protected_entities,
                    glossary_hits=glossary_hits,
                )
            ],
        )
        results = await provider.translate_batch(repair_request)
        if not results or not results[0].translated_text:
            return failed_translation, False
            
        repaired_text = _strip_ai_chatter(results[0].translated_text.strip())
        
        # 3. GENIUS STEP: Post-Repair Audit (Validation Loop)
        # Apply deterministic stabilization first
        repaired_text, _ = _stabilize_structured_segment(source_text, repaired_text, protected_entities, glossary_hits, target_lang=document.target_lang)
        
        # Calculate new risk score
        new_score, new_reasons = score_translation(
            source_text=source_text,
            translated_text=repaired_text,
            protected_entities=protected_entities,
            glossary_hits=glossary_hits,
            target_lang=document.target_lang,
        )
        
        # Get baseline score
        old_score, _ = score_translation(
            source_text=source_text,
            translated_text=failed_translation,
            protected_entities=protected_entities,
            glossary_hits=glossary_hits,
            target_lang=document.target_lang,
        )
        
        # 4. Acceptance Criteria
        # - Score must be lower (better) than before
        # - Critical values (numbers/dates) MUST be correct now
        crit_error = any(r["code"] in {"changed_number", "date_mismatch", "total_omission"} for r in new_reasons)
        
        if not crit_error and new_score < old_score:
            # Acceptance: The repair is objectively better and structurally sound
            return repaired_text, True
            
        # If repair failed validation, try one last surgical sanitization pass on the ORIGINAL
        surgical_text, changed = _apply_master_sanitization(source_text, failed_translation, document.target_lang)
        if changed:
            # If we could at least fix the currency/spacing deterministically, do that.
            return surgical_text, True
            
    except Exception as e:
        print(f"[REPAIR-FAILURE] Internal error during genius repair: {e}")
        pass
    
    return failed_translation, False
        


def _apply_master_sanitization(source_text: str, target_text: str, target_lang: str) -> tuple[str, bool]:
    """Deterministic surgical fixes for institutional standards (Source-Aware)."""
    original = target_text
    target_lang = target_lang.lower()
    
    text = target_text
    
    if target_lang == "ne":
        # Target is Nepali: Enforce रु and professional Devanagari typography
        text = text.replace("एनपीआर", "रु")
        text = text.replace("एन.पी.आर.", "रु")
        text = text.replace("रुपैया", "रु")
        
        # Swaps 'NPR 500' -> 'रु 500' if preceded by Nepali or start of string
        text = re.sub(r"(^|[\u0900-\u097F\s])NPR\s*([०-९0-9])", r"\1रु \2", text)
        
        # Enforce spacing standard (रु५०० -> रु ५००)
        text = re.sub(r"([रु\$])([०-९0-9])", r"\1 \2", text)
        
        # Abbreviation standard (न ५ -> नं. ५)
        text = re.sub(r"\bन\s+([०-९0-9])", r"नं. \1", text)
        
    elif target_lang == "en":
        # Target is English: Enforce NPR/Rs and Latin script consistency
        text = text.replace("रु", "NPR")
        text = text.replace("एनपीआर", "NPR")
        
        # Fix Devanagari digits if they leaked into English target
        text = digits_to_ascii(text)
        
        # Ensure 'NPR 500' spacing
        text = re.sub(r"(NPR|Rs\.?)([0-9])", r"\1 \2", text)
        
    # Global: Surgical Repetition Flattening (e.g. "मूल्य मूल्य" -> "मूल्य")
    # Only if it's a short segment (table cell/label) AND not in source
    if len(text.split()) <= 4:
        # Check if source text also has a repetition loop
        source_words = [w.lower() for w in source_text.split() if len(w) > 1]
        source_has_rep = any(source_words[i] == source_words[i+1] for i in range(len(source_words)-1))
        
        if not source_has_rep:
            # Matches any word repeated twice with a space
            text = re.sub(r"(^|\s)([\u0900-\u097F]+)\s+\2($|\s)", r"\1\2\3", text)
            text = re.sub(r"(^|\s)([a-zA-Z]+)\s+\2($|\s)", r"\1\2\3", text)
            # Strip potential double spaces introduced by the sub
            text = re.sub(r"\s+", " ", text).strip()
        
    return text, text != original


def _strip_ai_chatter(text: str) -> str:
    """Removes common AI conversational filler."""
    prefixes = [
        "Sure, here is the translation:",
        "Sure, here's the translation:",
        "Translation:",
        "Translated text:",
        "Here is the translation in Nepali:",
        "Sure!",
        "Okay,"
    ]
    cleaned = text.strip()
    for p in prefixes:
        if cleaned.lower().startswith(p.lower()):
            cleaned = cleaned[len(p):].strip()
            # If it starts with a quote, strip it too
            if cleaned.startswith('"') and cleaned.endswith('"'):
                cleaned = cleaned[1:-1].strip()
    return cleaned
