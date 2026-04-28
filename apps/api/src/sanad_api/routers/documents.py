import shutil
import tempfile
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from sanad_api.database import get_db
from sanad_api.models import Document, MemoryEntry, ReviewEvent, Segment, Translation, uuid_str
from sanad_api.schemas import (
    ApproveRequest,
    DocumentCreateResponse,
    DocumentSummary,
    ExportRequest,
    SegmentRead,
    SourceLanguageDetectionRead,
    TranslationPatch,
    TranslationRead,
)
from sanad_api.services.export import export_document_file
from sanad_api.services.feedback_pack import export_feedback_pack
from sanad_api.services.demo_content import SUPPORTED_DEMO_LANGUAGES
from sanad_api.services.language_detection import detect_source_language
from sanad_api.services.processing import document_counts, document_trust_summary, process_document
from sanad_api.services.review import approve_segment, approve_unflagged, update_candidate_translation
from sanad_api.services.scope import display_scope, normalize_scope
from sanad_api.services.storage import save_upload
router = APIRouter(tags=["documents"])

SUPPORTED_UPLOAD_TYPES = {
    ".csv": "csv",
    ".pdf": "pdf",
    ".docx": "docx",
    ".doc": "doc",
    ".odt": "odt",
    ".rtf": "rtf",
    ".tsv": "tsv",
    ".txt": "txt",
    ".md": "md",
    ".html": "html",
    ".htm": "html",
}


@router.post("/documents/detect-source", response_model=SourceLanguageDetectionRead)
def detect_document_source_language(file: Annotated[UploadFile, File()]) -> SourceLanguageDetectionRead:
    extension = Path(file.filename or "").suffix.lower()
    file_type = SUPPORTED_UPLOAD_TYPES.get(extension)
    if not file_type:
        raise HTTPException(
            status_code=400,
            detail=(
                "Unsupported file type. SANAD accepts DOCX, DOC, ODT, RTF, TXT, MD, and HTML text documents. "
                "PDF, CSV, and TSV are also supported. "
                "Scanned/image-only PDFs are not supported."
            ),
        )

    temp_path = _save_temp_upload(file, extension)
    try:
        detection = detect_source_language(temp_path, file_type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        temp_path.unlink(missing_ok=True)

    return SourceLanguageDetectionRead(
        source_lang=detection.source_lang,
        confidence=detection.confidence,
        explanation=detection.explanation,
        segment_count=detection.segment_count,
    )


@router.post("/documents", response_model=DocumentCreateResponse)
def upload_document(
    file: Annotated[UploadFile, File()],
    source_lang: Annotated[str, Form()],
    target_lang: Annotated[str, Form()],
    domain: Annotated[str, Form()],
    subdomain: Annotated[str | None, Form()] = None,
    db: Session = Depends(get_db),
) -> DocumentCreateResponse:
    source_lang = _required_text(source_lang, "source_lang")
    target_lang = _required_text(target_lang, "target_lang")
    domain = _required_text(domain, "domain")
    source_lang, target_lang = _validated_language_pair(source_lang, target_lang)
    normalized_subdomain = normalize_scope(subdomain)
    extension = Path(file.filename or "").suffix.lower()
    file_type = SUPPORTED_UPLOAD_TYPES.get(extension)
    if not file_type:
        raise HTTPException(
            status_code=400,
            detail=(
                "Unsupported file type. SANAD accepts DOCX, DOC, ODT, RTF, TXT, MD, and HTML text documents. "
                "PDF, CSV, and TSV are also supported. "
                "Scanned/image-only PDFs are not supported."
            ),
        )

    document_id = uuid_str()
    saved_path, checksum = save_upload(document_id, file, extension)
    
    # Duplicate detection (Moat Feature F12)
    existing_duplicate = db.scalar(
        select(Document).where(
            Document.checksum == checksum,
            Document.source_lang == source_lang,
            Document.target_lang == target_lang,
            Document.domain == domain,
            Document.subdomain == normalized_subdomain,
            Document.status != "failed",
        )
    )
    if existing_duplicate:
        # We don't save the new upload, just return the existing one
        saved_path.unlink(missing_ok=True)
        return DocumentCreateResponse(
            id=existing_duplicate.id, 
            status=existing_duplicate.status, 
            original_filename=existing_duplicate.original_filename,
            is_duplicate=True
        )

    document = Document(
        id=document_id,
        original_filename=file.filename or f"upload{extension or '.docx'}",
        file_type=file_type,
        source_lang=source_lang,
        target_lang=target_lang,
        domain=domain,
        subdomain=normalized_subdomain,
        status="uploaded",
        original_file_uri=str(saved_path),
        checksum=checksum,
        doc_metadata={},
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    return DocumentCreateResponse(id=document.id, status=document.status, original_filename=document.original_filename, is_duplicate=False)


@router.post("/documents/{document_id}/process", response_model=DocumentSummary)
async def process(document_id: str, db: Session = Depends(get_db)) -> DocumentSummary:
    document = _get_document(db, document_id)
    try:
        await process_document(db, document)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _document_summary(db, document)


@router.get("/documents/{document_id}", response_model=DocumentSummary)
def get_document(document_id: str, db: Session = Depends(get_db)) -> DocumentSummary:
    return _document_summary(db, _get_document(db, document_id))


@router.delete("/documents/{document_id}", status_code=204)
def delete_document(document_id: str, db: Session = Depends(get_db)):
    from sqlalchemy import delete, update
    document = db.scalar(select(Document).where(Document.id == document_id))
    if not document:
        raise HTTPException(status_code=404, detail="Document not found.")

    # Collect IDs that will be cascade-deleted so we can clear FK references in memory_entries first.
    segment_ids = [row[0] for row in db.execute(select(Segment.id).where(Segment.document_id == document_id)).all()]
    review_event_ids = [row[0] for row in db.execute(select(ReviewEvent.id).where(ReviewEvent.document_id == document_id)).all()]

    # Nullify memory_entries references that would block cascade deletion (existing DB lacks ON DELETE SET NULL).
    if segment_ids:
        db.execute(
            update(MemoryEntry)
            .where(MemoryEntry.created_from_segment_id.in_(segment_ids))
            .values(created_from_segment_id=None)
        )
    if review_event_ids:
        db.execute(
            update(MemoryEntry)
            .where(MemoryEntry.created_from_review_event_id.in_(review_event_ids))
            .values(created_from_review_event_id=None)
        )
    db.execute(
        update(MemoryEntry)
        .where(MemoryEntry.created_from_document_id == document_id)
        .values(created_from_document_id=None)
    )
    db.flush()

    # Now the cascade can proceed without FK constraint violations.
    db.execute(delete(Document).where(Document.id == document_id))
    db.commit()


@router.get("/documents/{document_id}/segments", response_model=list[SegmentRead])
def get_segments(document_id: str, db: Session = Depends(get_db)) -> list[SegmentRead]:
    _get_document(db, document_id)
    segments = db.scalars(
        select(Segment)
        .where(Segment.document_id == document_id)
        .options(
            selectinload(Segment.translation)
            .selectinload(Translation.memory_entry)
            .selectinload(MemoryEntry.source_document)
        )
        .order_by(Segment.sequence)
    ).all()
    return [_segment_read(segment) for segment in segments]


@router.patch("/segments/{segment_id}/translation", response_model=SegmentRead)
def patch_translation(segment_id: str, payload: TranslationPatch, db: Session = Depends(get_db)) -> SegmentRead:
    try:
        segment = update_candidate_translation(db, segment_id, candidate_text=payload.candidate_text)
    except ValueError as exc:
        status_code = 404 if "not found" in str(exc).lower() else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    return _segment_read(segment)


@router.post("/segments/{segment_id}/approve", response_model=SegmentRead)
def approve(segment_id: str, payload: ApproveRequest, db: Session = Depends(get_db)) -> SegmentRead:
    try:
        segment = approve_segment(db, segment_id, text=payload.text, actor=payload.actor)
    except ValueError as exc:
        status_code = 404 if "not found" in str(exc).lower() else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    return _segment_read(segment)


@router.post("/documents/{document_id}/approve-unflagged")
def approve_unflagged_segments(document_id: str, db: Session = Depends(get_db)) -> dict:
    _get_document(db, document_id)
    return {"approved": approve_unflagged(db, document_id)}


@router.post("/documents/{document_id}/export")
def export_document(document_id: str, payload: ExportRequest, db: Session = Depends(get_db)) -> dict:
    document = _get_document(db, document_id)
    supported_formats = _supported_export_formats(document.file_type)
    if payload.format not in supported_formats:
        raise HTTPException(status_code=400, detail=f"SANAD cannot export {document.file_type.upper()} documents to {payload.format.upper()}. Supported formats: {', '.join(supported_formats).upper()}.")
    try:
        output_path = export_document_file(db, document, payload.format)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"document_id": document.id, "format": payload.format, "export_file_uri": str(output_path)}


@router.get("/documents/{document_id}/feedback-pack")
def feedback_pack(document_id: str, db: Session = Depends(get_db)) -> FileResponse:
    document = _get_document(db, document_id)
    try:
        output_path = export_feedback_pack(db, document)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return FileResponse(
        output_path,
        media_type="application/zip",
        filename=f"sanad-{Path(document.original_filename).stem}-feedback-pack.zip",
    )


@router.get("/documents/{document_id}/exports/latest")
def latest_export(document_id: str, db: Session = Depends(get_db)) -> FileResponse:
    document = _get_document(db, document_id)
    if not document.export_file_uri or not Path(document.export_file_uri).exists():
        raise HTTPException(status_code=404, detail="No export is available for this document.")
    export_format = Path(document.export_file_uri).suffix.lstrip(".")
    media_type = _media_type_for_export(export_format)
    return FileResponse(
        document.export_file_uri,
        media_type=media_type,
        filename=f"sanad-{Path(document.original_filename).stem}-translated.{export_format}",
    )


def _get_document(db: Session, document_id: str) -> Document:
    document = db.get(Document, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found.")
    return document


def _document_summary(db: Session, document: Document) -> DocumentSummary:
    db.refresh(document)
    return DocumentSummary(
        id=document.id,
        original_filename=document.original_filename,
        file_type=document.file_type,
        source_lang=document.source_lang,
        target_lang=document.target_lang,
        domain=document.domain,
        subdomain=display_scope(document.subdomain),
        status=document.status,
        export_file_uri=document.export_file_uri,
        counts=document_counts(db, document.id),
        trust_summary=document_trust_summary(db, document.id),
        created_at=document.created_at,
        updated_at=document.updated_at,
    )


def _segment_read(segment: Segment) -> SegmentRead:
    translation = segment.translation
    return SegmentRead(
        id=segment.id,
        sequence=segment.sequence,
        segment_type=segment.segment_type,
        source_text=segment.source_text,
        normalized_source=segment.normalized_source,
        protected_entities=segment.protected_entities_json,
        glossary_hits=segment.glossary_hits_json,
        status=segment.status,
        translation=_translation_read(translation) if translation else None,
    )


def _translation_read(translation: Translation) -> TranslationRead:
    return TranslationRead(
        id=translation.id,
        candidate_text=translation.candidate_text,
        approved_text=translation.approved_text,
        source_type=translation.source_type,
        provider_name=translation.provider_name,
        memory_entry_id=translation.memory_entry_id,
        risk_score=translation.risk_score,
        risk_reasons=translation.risk_reasons_json,
        status=translation.status,
        memory_provenance=_memory_provenance_read(translation.memory_entry) if translation.memory_entry else None,
    )


def _memory_provenance_read(memory_entry: MemoryEntry) -> dict:
    return {
        "source_document_filename": memory_entry.source_document.original_filename if memory_entry.source_document else None,
        "scope_label": _scope_label(memory_entry.domain, memory_entry.subdomain),
        "approved_at": memory_entry.approved_at.isoformat(),
        "times_used": memory_entry.times_used,
    }


def _scope_label(domain: str, subdomain: str | None) -> str:
    values = [_humanize_scope(domain)]
    subdomain_display = display_scope(subdomain)
    if subdomain_display:
        values.append(_humanize_scope(subdomain_display))
    return " / ".join(values)


def _humanize_scope(value: str) -> str:
    return value.replace("_", " ").strip().title()


def _required_text(value: str, field_name: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise HTTPException(status_code=422, detail=f"{field_name} must not be empty.")
    return cleaned


def _validated_language_pair(source_lang: str, target_lang: str) -> tuple[str, str]:
    source = source_lang.lower()
    target = target_lang.lower()
    supported = ", ".join(language.upper() for language in SUPPORTED_DEMO_LANGUAGES)
    if source not in SUPPORTED_DEMO_LANGUAGES:
        raise HTTPException(status_code=422, detail=f"Unsupported source_lang {source_lang!r}. Use one of: {supported}.")
    if target not in SUPPORTED_DEMO_LANGUAGES:
        raise HTTPException(status_code=422, detail=f"Unsupported target_lang {target_lang!r}. Use one of: {supported}.")
    if source == target:
        raise HTTPException(status_code=422, detail="source_lang and target_lang must be different.")
    return source, target


def _save_temp_upload(upload: UploadFile, extension: str) -> Path:
    with tempfile.NamedTemporaryFile(delete=False, suffix=extension or ".tmp") as handle:
        upload.file.seek(0)
        shutil.copyfileobj(upload.file, handle)
        temp_path = Path(handle.name)
    upload.file.seek(0)
    return temp_path


def _supported_export_formats(file_type: str) -> list[str]:
    if file_type in {"csv", "tsv"}:
        return [file_type, "docx", "pdf", "txt"]
    if file_type == "pdf":
        return ["pdf", "docx", "txt"]
    return ["docx", "pdf", "txt"]


def _media_type_for_export(export_format: str) -> str:
    if export_format == "csv":
        return "text/csv"
    if export_format == "tsv":
        return "text/tab-separated-values"
    if export_format == "pdf":
        return "application/pdf"
    if export_format == "txt":
        return "text/plain"
    return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

from fastapi.responses import StreamingResponse
import asyncio
import json

@router.get("/documents/{document_id}/progress")
async def document_progress(document_id: str, db: Session = Depends(get_db)):
    document = _get_document(db, document_id)
    
    async def event_generator():
        # This is a real-time SSE stream. In a full implementation we'd hook this into the
        # process_document flow using an async queue or Redis pub/sub. 
        # For the hackathon moat, we will stream real DB status updates until it's processed.
        
        while True:
            # Refresh document from DB
            db.refresh(document)
            
            if document.status == "failed":
                yield f"data: {json.dumps({'status': 'failed'})}\n\n"
                break
                
            if document.status == "processed":
                yield f"data: {json.dumps({'status': 'processed', 'step': 'ready'})}\n\n"
                break
                
            if document.status == "uploaded":
                yield f"data: {json.dumps({'status': 'processing', 'step': 'parsing'})}\n\n"
            else:
                # Get segment counts to calculate real translation progress
                counts = document_counts(db, document.id)
                total = counts["segments"]
                done = counts["approved"] + counts["needs_review"] + counts["memory_applied"]
                
                if total == 0:
                    yield f"data: {json.dumps({'status': 'processing', 'step': 'parsing'})}\n\n"
                elif done < total:
                    yield f"data: {json.dumps({'status': 'processing', 'step': 'translating', 'progress': done, 'total': total})}\n\n"
                else:
                    yield f"data: {json.dumps({'status': 'processing', 'step': 'scoring'})}\n\n"
            
            await asyncio.sleep(0.5)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
