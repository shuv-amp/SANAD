import csv
import io
import json
import re
import zipfile
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from sanad_api.models import Document, ReviewEvent, Segment
from sanad_api.services.processing import document_trust_summary
from sanad_api.services.protection import detect_protected_entities
from sanad_api.services.risk import is_probable_name_segment, protected_entity_variants, score_translation
from sanad_api.services.normalization import normalize_text
from sanad_api.services.scope import display_scope
from sanad_api.services.storage import feedback_pack_path

PLACEHOLDERS = {
    "url": "<URL>",
    "email": "<EMAIL>",
    "phone": "<PHONE>",
    "id": "<ID>",
    "date": "<DATE>",
    "money": "<MONEY>",
    "number": "<NUMBER>",
    "ward": "<WARD>",
    "office": "<OFFICE>",
}
PLACEHOLDER_RE = re.compile(r"<[A-Z_]+>")
ALPHA_RE = re.compile(r"[^\W\d_]", re.UNICODE)
NAME_LABELS = {
    normalize_text("Applicant Name"),
    normalize_text("Name"),
    normalize_text("निवेदकको नाम"),
    normalize_text("नाम"),
    normalize_text("स्ह्युसेन पिन्बा मिन"),
}


def export_feedback_pack(db: Session, document: Document) -> Path:
    segments = _approved_segments(db, document.id)
    unapproved = [
        segment.sequence
        for segment in segments
        if not segment.translation or segment.status != "approved" or not (segment.translation.approved_text or "").strip()
    ]
    if unapproved:
        raise ValueError(f"Cannot export feedback pack until all segments are approved. Pending sequence(s): {unapproved}")

    events_by_segment = _review_events_by_segment(db, document.id)
    approved_rows: list[dict[str, str]] = []
    correction_rows: list[dict[str, str]] = []
    excluded_rows = 0
    corrected_segments_total = 0

    for index, segment in enumerate(segments):
        translation = segment.translation
        if not translation:
            continue

        approved_text = (translation.approved_text or translation.candidate_text or "").strip()
        baseline_text = _baseline_candidate_text(segment, events_by_segment[segment.id])
        _, baseline_risks = score_translation(
            source_text=segment.source_text,
            translated_text=baseline_text,
            protected_entities=segment.protected_entities_json or [],
            glossary_hits=segment.glossary_hits_json or [],
        )
        protected_kinds = sorted({entity["kind"] for entity in segment.protected_entities_json or []})
        glossary_terms = sorted(
            {
                f"{hit['source_term']} -> {hit['target_term']}"
                for hit in segment.glossary_hits_json or []
                if hit.get("source_term") and hit.get("target_term")
            }
        )
        redacted_source = redact_feedback_text(segment.source_text, segment.protected_entities_json or [])
        redacted_approved = redact_feedback_text(approved_text, segment.protected_entities_json or [])
        previous_segment = segments[index - 1] if index > 0 else None
        shareable = _is_shareable_row(segment, redacted_source, redacted_approved, previous_segment)
        if shareable:
            approved_rows.append(
                {
                    "sequence": str(segment.sequence),
                    "segment_type": segment.segment_type,
                    "source_text_redacted": redacted_source,
                    "approved_text_redacted": redacted_approved,
                    "source_lang": document.source_lang,
                    "target_lang": document.target_lang,
                    "domain": document.domain,
                    "subdomain": _subdomain_value(document.subdomain),
                    "source_type": translation.source_type,
                    "provider_name": translation.provider_name,
                    "had_risk_before_approval": _bool_text(bool(baseline_risks)),
                    "protected_entity_kinds": ", ".join(protected_kinds),
                    "glossary_terms_applied": "; ".join(glossary_terms),
                }
            )
        else:
            excluded_rows += 1

        has_reviewer_correction = _has_reviewer_correction(events_by_segment[segment.id], baseline_text, approved_text)
        if has_reviewer_correction:
            corrected_segments_total += 1

        if has_reviewer_correction and shareable:
            redacted_candidate = redact_feedback_text(baseline_text, segment.protected_entities_json or [])
            correction_rows.append(
                {
                    "sequence": str(segment.sequence),
                    "source_text_redacted": redacted_source,
                    "candidate_text_redacted": redacted_candidate,
                    "approved_text_redacted": redacted_approved,
                    "review_action": _review_action(events_by_segment[segment.id]),
                    "risk_codes_before_approval": ", ".join(reason["code"] for reason in baseline_risks),
                    "protected_entity_kinds": ", ".join(protected_kinds),
                }
            )

    trust_summary = document_trust_summary(db, document.id)
    manifest = {
        "document_id": document.id,
        "original_filename": document.original_filename,
        "file_type": document.file_type,
        "source_lang": document.source_lang,
        "target_lang": document.target_lang,
        "domain": document.domain,
        "subdomain": _subdomain_value(document.subdomain),
        "scope_label": _scope_label(document.domain, document.subdomain),
        "exported_at": datetime.now(UTC).isoformat(),
        "total_segments": trust_summary["total_segments"],
        "approved_segments": trust_summary["approved_segments"],
        "memory_reused_segments": trust_summary["memory_reused_segments"],
        "corrected_segments": corrected_segments_total,
        "included_rows": len(approved_rows),
        "excluded_rows": excluded_rows,
        "redaction_mode": "protected_entity_placeholders_v1",
        "notes": "Review-derived local export for feedback or corpus contribution. Privacy-reduced by default.",
    }

    output_path = feedback_pack_path(document.id)
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"))
        archive.writestr(
            "approved_segments.tsv",
            _tsv_bytes(
                approved_rows,
                [
                    "sequence",
                    "segment_type",
                    "source_text_redacted",
                    "approved_text_redacted",
                    "source_lang",
                    "target_lang",
                    "domain",
                    "subdomain",
                    "source_type",
                    "provider_name",
                    "had_risk_before_approval",
                    "protected_entity_kinds",
                    "glossary_terms_applied",
                ],
            ),
        )
        archive.writestr(
            "review_corrections.tsv",
            _tsv_bytes(
                correction_rows,
                [
                    "sequence",
                    "source_text_redacted",
                    "candidate_text_redacted",
                    "approved_text_redacted",
                    "review_action",
                    "risk_codes_before_approval",
                    "protected_entity_kinds",
                ],
            ),
        )
    return output_path


def redact_feedback_text(text: str, protected_entities: list[dict]) -> str:
    redacted = text
    token_map: dict[str, str] = {}
    for index, entity in enumerate(protected_entities):
        placeholder = PLACEHOLDERS.get(entity.get("kind", ""), "<VALUE>")
        token = chr(0xE000 + index)
        variants = sorted(
            {variant for variant in protected_entity_variants(entity) if variant},
            key=len,
            reverse=True,
        )
        if not variants:
            continue
        pattern = re.compile("|".join(re.escape(variant) for variant in variants), re.IGNORECASE)
        updated, count = pattern.subn(token, redacted)
        if count:
            redacted = updated
            token_map[token] = placeholder
    for token, placeholder in token_map.items():
        redacted = redacted.replace(token, placeholder)
    residual_entities = detect_protected_entities(redacted, [])
    return _replace_entities_by_span(redacted, residual_entities)


def _approved_segments(db: Session, document_id: str) -> list[Segment]:
    return db.scalars(
        select(Segment)
        .where(Segment.document_id == document_id)
        .options(selectinload(Segment.translation))
        .order_by(Segment.sequence)
    ).all()


def _review_events_by_segment(db: Session, document_id: str) -> dict[str, list[ReviewEvent]]:
    events = db.scalars(select(ReviewEvent).where(ReviewEvent.document_id == document_id).order_by(ReviewEvent.created_at)).all()
    grouped: dict[str, list[ReviewEvent]] = defaultdict(list)
    for event in events:
        grouped[event.segment_id].append(event)
    return grouped


def _baseline_candidate_text(segment: Segment, events: list[ReviewEvent]) -> str:
    for event in events:
        if event.event_type in {"edit", "edit_and_approve"} and event.before_text:
            return event.before_text
    translation = segment.translation
    return (translation.approved_text or translation.candidate_text or "").strip() if translation else ""


def _has_reviewer_correction(events: list[ReviewEvent], baseline_text: str, approved_text: str) -> bool:
    if not any(event.event_type in {"edit", "edit_and_approve"} for event in events):
        return False
    return baseline_text.strip() != approved_text.strip()


def _review_action(events: list[ReviewEvent]) -> str:
    if any(event.event_type == "edit_and_approve" for event in events):
        return "edit_and_approve"
    return "revised_then_approve"


def _is_shareable_row(
    segment: Segment,
    redacted_source: str,
    redacted_target: str,
    previous_segment: Segment | None,
) -> bool:
    if not _has_signal_text(redacted_source) and not _has_signal_text(redacted_target):
        return False
    if _is_likely_personal_value_row(segment, previous_segment):
        return False
    return True


def _has_signal_text(text: str) -> bool:
    deplaceholdered = PLACEHOLDER_RE.sub(" ", text)
    return bool(ALPHA_RE.search(deplaceholdered))


def _is_likely_personal_value_row(segment: Segment, previous_segment: Segment | None) -> bool:
    source_text = segment.source_text.strip()
    approved_text = (segment.translation.approved_text if segment.translation else "") or ""
    if not source_text:
        return False
    if segment.protected_entities_json or segment.glossary_hits_json:
        return False
    if is_probable_name_segment(source_text, source_text):
        return True
    if approved_text and is_probable_name_segment(approved_text, approved_text):
        return True
    if previous_segment and normalize_text(previous_segment.source_text) in NAME_LABELS:
        return _looks_like_short_alpha_value(source_text) or _looks_like_short_alpha_value(approved_text)
    return False


def _looks_like_short_alpha_value(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    if any(character.isdigit() for character in stripped):
        return False
    if any(character in ":/.@_" for character in stripped):
        return False
    tokens = stripped.split()
    if not 1 <= len(tokens) <= 4:
        return False
    return all(ALPHA_RE.search(token) for token in tokens)


def _bool_text(value: bool) -> str:
    return "true" if value else "false"


def _subdomain_value(subdomain: str | None) -> str:
    return display_scope(subdomain) or ""


def _scope_label(domain: str, subdomain: str | None) -> str:
    values = [_humanize_scope(domain)]
    subdomain_display = display_scope(subdomain)
    if subdomain_display:
        values.append(_humanize_scope(subdomain_display))
    return " / ".join(values)


def _humanize_scope(value: str) -> str:
    return value.replace("_", " ").strip().title()


def _tsv_bytes(rows: list[dict[str, str]], fieldnames: list[str]) -> bytes:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, delimiter="\t", lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return buffer.getvalue().encode("utf-8")


def _replace_entities_by_span(text: str, entities: list[dict]) -> str:
    redacted = text
    for entity in sorted(
        (
            item
            for item in entities
            if isinstance(item.get("start"), int) and isinstance(item.get("end"), int) and item.get("kind") in PLACEHOLDERS
        ),
        key=lambda item: (item["start"], item["end"]),
        reverse=True,
    ):
        redacted = f"{redacted[:entity['start']]}{PLACEHOLDERS[entity['kind']]}{redacted[entity['end']:]}"
    return redacted
