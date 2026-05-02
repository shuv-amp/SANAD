import asyncio
import json
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from sanad_api.database import get_db
from sanad_api.models import (
    Document,
    GlossaryTerm,
    MemoryEntry,
    ReviewEvent,
    Segment,
    Translation,
)
from sanad_api.services.normalization import normalize_text
from sanad_api.services.scope import display_scope, normalize_scope
from sanad_api.services.processing import document_counts

router = APIRouter(tags=["platform"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class DocumentListItem(BaseModel):
    id: str
    original_filename: str
    file_type: str
    source_lang: str
    target_lang: str
    domain: str
    subdomain: str | None
    status: str
    created_at: datetime
    segment_count: int
    approved_count: int
    memory_count: int


class AnalyticsSummary(BaseModel):
    total_documents: int
    total_segments: int
    total_approved: int
    total_memory_entries: int
    memory_reuse_count: int
    total_review_corrections: int
    total_glossary_terms: int
    provider_breakdown: dict[str, int]
    avg_risk_score: float
    total_exports: int


class GlossaryTermRead(BaseModel):
    id: str
    source_lang: str
    target_lang: str
    domain: str
    subdomain: str | None
    source_term: str
    target_term: str
    term_type: str


class GlossaryTermCreate(BaseModel):
    source_lang: str = "en"
    target_lang: str = "ne"
    domain: str = "public_service"
    subdomain: str | None = None
    source_term: str
    target_term: str
    term_type: str = "term"

    @field_validator("source_term", "target_term")
    @classmethod
    def must_not_be_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Term must not be blank.")
        return v.strip()


class MemoryEntryRead(BaseModel):
    id: str
    source_lang: str
    target_lang: str
    domain: str
    subdomain: str | None
    source_text: str
    target_text: str
    approved_by: str
    approved_at: datetime
    times_used: int
    last_used_at: datetime | None
    source_document_filename: str | None


class QuickDetectRequest(BaseModel):
    text: str


class QuickDetectResponse(BaseModel):
    source_lang: str | None
    confidence: str
    explanation: str


class QuickTranslateRequest(BaseModel):
    text: str
    source_lang: str
    target_lang: str


class QuickTranslateResponse(BaseModel):
    translated_text: str
    risk_score: float


# ---------------------------------------------------------------------------
# F1: Document History
# ---------------------------------------------------------------------------


@router.get("/documents", response_model=list[DocumentListItem])
def list_documents(db: Session = Depends(get_db)) -> list[DocumentListItem]:
    documents = db.scalars(
        select(Document).order_by(Document.created_at.desc())
    ).all()

    items = []
    for doc in documents:
        seg_count = db.scalar(
            select(func.count()).select_from(Segment).where(Segment.document_id == doc.id)
        ) or 0
        approved = db.scalar(
            select(func.count()).select_from(Segment).where(
                Segment.document_id == doc.id, Segment.status == "approved"
            )
        ) or 0
        memory = db.scalar(
            select(func.count())
            .select_from(Segment)
            .join(Translation, Translation.segment_id == Segment.id)
            .where(Segment.document_id == doc.id, Translation.source_type == "memory")
        ) or 0
        items.append(
            DocumentListItem(
                id=doc.id,
                original_filename=doc.original_filename,
                file_type=doc.file_type,
                source_lang=doc.source_lang,
                target_lang=doc.target_lang,
                domain=doc.domain,
                subdomain=display_scope(doc.subdomain),
                status=doc.status,
                created_at=doc.created_at,
                segment_count=seg_count,
                approved_count=approved,
                memory_count=memory,
            )
        )
    return items


# ---------------------------------------------------------------------------
# F2: Analytics Dashboard
# ---------------------------------------------------------------------------


@router.get("/analytics/summary", response_model=AnalyticsSummary)
def analytics_summary(db: Session = Depends(get_db)) -> AnalyticsSummary:
    total_documents = db.scalar(select(func.count()).select_from(Document)) or 0
    total_segments = db.scalar(select(func.count()).select_from(Segment)) or 0
    total_approved = db.scalar(
        select(func.count()).select_from(Segment).where(Segment.status == "approved")
    ) or 0
    total_memory_entries = db.scalar(
        select(func.count()).select_from(MemoryEntry).where(MemoryEntry.is_active.is_(True))
    ) or 0
    memory_reuse_count = db.scalar(
        select(func.count()).select_from(Translation).where(Translation.source_type == "memory")
    ) or 0
    total_review_corrections = db.scalar(
        select(func.count())
        .select_from(ReviewEvent)
        .where(ReviewEvent.event_type.in_(["edit", "edit_and_approve"]))
    ) or 0
    total_glossary_terms = db.scalar(select(func.count()).select_from(GlossaryTerm)) or 0
    total_exports = db.scalar(
        select(func.count()).select_from(Document).where(Document.status == "exported")
    ) or 0

    # Provider breakdown
    provider_rows = db.execute(
        select(Translation.provider_name, func.count()).group_by(Translation.provider_name)
    ).all()
    provider_breakdown = {name: count for name, count in provider_rows}

    avg_risk = db.scalar(select(func.avg(Translation.risk_score))) or 0.0

    return AnalyticsSummary(
        total_documents=total_documents,
        total_segments=total_segments,
        total_approved=total_approved,
        total_memory_entries=total_memory_entries,
        memory_reuse_count=memory_reuse_count,
        total_review_corrections=total_review_corrections,
        total_glossary_terms=total_glossary_terms,
        provider_breakdown=provider_breakdown,
        avg_risk_score=round(float(avg_risk), 2),
        total_exports=total_exports,
    )


# ---------------------------------------------------------------------------
# F3: Glossary CRUD
# ---------------------------------------------------------------------------


@router.get("/glossary", response_model=list[GlossaryTermRead])
def list_glossary(db: Session = Depends(get_db)) -> list[GlossaryTermRead]:
    terms = db.scalars(select(GlossaryTerm).order_by(GlossaryTerm.created_at.desc())).all()
    return [
        GlossaryTermRead(
            id=t.id,
            source_lang=t.source_lang,
            target_lang=t.target_lang,
            domain=t.domain,
            subdomain=display_scope(t.subdomain),
            source_term=t.source_term,
            target_term=t.target_term,
            term_type=t.term_type,
        )
        for t in terms
    ]


@router.post("/glossary", response_model=GlossaryTermRead, status_code=201)
def create_glossary_term(payload: GlossaryTermCreate, db: Session = Depends(get_db)) -> GlossaryTermRead:
    normalized = normalize_text(payload.source_term)
    subdomain = normalize_scope(payload.subdomain)
    existing = db.scalar(
        select(GlossaryTerm).where(
            GlossaryTerm.source_lang == payload.source_lang,
            GlossaryTerm.target_lang == payload.target_lang,
            GlossaryTerm.domain == payload.domain,
            GlossaryTerm.subdomain == subdomain,
            GlossaryTerm.normalized_source_term == normalized,
        )
    )
    if existing:
        raise HTTPException(status_code=409, detail="A glossary term with that source already exists in this scope.")

    term = GlossaryTerm(
        source_lang=payload.source_lang,
        target_lang=payload.target_lang,
        domain=payload.domain,
        subdomain=subdomain,
        source_term=payload.source_term,
        normalized_source_term=normalized,
        target_term=payload.target_term,
        term_type=payload.term_type,
    )
    db.add(term)
    db.commit()
    db.refresh(term)
    return GlossaryTermRead(
        id=term.id,
        source_lang=term.source_lang,
        target_lang=term.target_lang,
        domain=term.domain,
        subdomain=display_scope(term.subdomain),
        source_term=term.source_term,
        target_term=term.target_term,
        term_type=term.term_type,
    )


@router.delete("/glossary/{term_id}", status_code=204)
def delete_glossary_term(term_id: str, db: Session = Depends(get_db)):
    term = db.scalar(select(GlossaryTerm).where(GlossaryTerm.id == term_id))
    if not term:
        raise HTTPException(status_code=404, detail="Glossary term not found.")
    db.delete(term)
    db.commit()


# ---------------------------------------------------------------------------
# F4: Translation Memory Browser
# ---------------------------------------------------------------------------


@router.get("/memory", response_model=list[MemoryEntryRead])
def list_memory(db: Session = Depends(get_db)) -> list[MemoryEntryRead]:
    entries = db.scalars(
        select(MemoryEntry)
        .where(MemoryEntry.is_active.is_(True))
        .order_by(MemoryEntry.approved_at.desc())
    ).all()

    items = []
    for entry in entries:
        source_doc_name = None
        if entry.created_from_document_id:
            doc = db.scalar(select(Document).where(Document.id == entry.created_from_document_id))
            if doc:
                source_doc_name = doc.original_filename

        items.append(
            MemoryEntryRead(
                id=entry.id,
                source_lang=entry.source_lang,
                target_lang=entry.target_lang,
                domain=entry.domain,
                subdomain=display_scope(entry.subdomain),
                source_text=entry.source_text,
                target_text=entry.target_text,
                approved_by=entry.approved_by,
                approved_at=entry.approved_at,
                times_used=entry.times_used,
                last_used_at=entry.last_used_at,
                source_document_filename=source_doc_name,
            )
        )
    return items


@router.delete("/memory/{entry_id}", status_code=204)
def delete_memory_entry(entry_id: str, db: Session = Depends(get_db)):
    entry = db.scalar(select(MemoryEntry).where(MemoryEntry.id == entry_id))
    if not entry:
        raise HTTPException(status_code=404, detail="Memory entry not found.")
    
    entry.is_active = False
    db.commit()


# ---------------------------------------------------------------------------
# Real-time SSE processing updates
# ---------------------------------------------------------------------------

@router.get("/documents/{document_id}/progress")
async def document_progress(document_id: str, db: Session = Depends(get_db)):
    doc = db.scalar(select(Document).where(Document.id == document_id))
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
        
    async def event_generator():
        # SSE stream showing processing pipeline status
        while True:
            # Refresh doc
            db.refresh(doc)
            
            if doc.status == "failed":
                yield f"data: {json.dumps({'status': 'failed'})}\n\n"
                break
                
            if doc.status == "processed":
                yield f"data: {json.dumps({'status': 'processed', 'step': 'ready'})}\n\n"
                break
                
            if doc.status == "uploaded":
                yield f"data: {json.dumps({'status': 'processing', 'step': 'parsing'})}\n\n"
            else:
                processing_meta = (doc.doc_metadata or {}).get("processing") or {}
                counts = document_counts(db, doc.id)
                total = counts["segments"]
                done = counts["approved"] + counts["needs_review"] + counts["memory_applied"]
                
                if processing_meta:
                    meta_total = int(processing_meta.get("total_segments") or 0)
                    meta_done = int(processing_meta.get("local_segments") or 0)
                    yield f"data: {json.dumps({'status': 'processing', 'step': 'translating', 'progress': meta_done, 'total': meta_total})}\n\n"
                elif total == 0:
                    yield f"data: {json.dumps({'status': 'processing', 'step': 'parsing'})}\n\n"
                elif done < total:
                    yield f"data: {json.dumps({'status': 'processing', 'step': 'translating', 'progress': done, 'total': total})}\n\n"
                else:
                    yield f"data: {json.dumps({'status': 'processing', 'step': 'scoring'})}\n\n"
            
            await asyncio.sleep(0.5)

    return StreamingResponse(event_generator(), media_type="text/event-stream")

# ---------------------------------------------------------------------------
# F5: Quick Actions (CLI / Simple Integration)
# ---------------------------------------------------------------------------

@router.post("/quick-detect", response_model=QuickDetectResponse)
def quick_detect(payload: QuickDetectRequest):
    from sanad_api.services.language_detection import detect_source_language_from_text
    
    if not payload.text.strip():
        raise HTTPException(status_code=400, detail="Text cannot be empty.")
        
    detection = detect_source_language_from_text(payload.text)
    return QuickDetectResponse(
        source_lang=detection.source_lang,
        confidence=detection.confidence,
        explanation=detection.explanation
    )

@router.post("/quick-translate", response_model=QuickTranslateResponse)
async def quick_translate(payload: QuickTranslateRequest):
    from sanad_api.services.risk import score_translation
    from sanad_api.services.providers import get_provider, TranslationBatchRequest, TranslationSegmentRequest
    from sanad_api.config import get_settings
    
    if not payload.text.strip():
        raise HTTPException(status_code=400, detail="Text cannot be empty.")
        
    settings = get_settings()
    provider = get_provider(settings.active_provider)
    
    # 1. Raw Fast Translate
    req = TranslationBatchRequest(
        source_lang=payload.source_lang,
        target_lang=payload.target_lang,
        domain="public_service",
        subdomain="",
        segments=[
            TranslationSegmentRequest(
                segment_id="quick",
                source_text=payload.text,
                protected_entities=[],
                glossary_hits=[]
            )
        ]
    )
    
    results = await provider.translate_batch(req)
    if not results:
        raise HTTPException(status_code=500, detail="Translation failed.")
        
    translated_text = results[0].translated_text
    
    # 2. Basic Audit Scoring
    score, _ = score_translation(
        source_text=payload.text,
        translated_text=translated_text,
        protected_entities=[],
        glossary_hits=[]
    )

    return QuickTranslateResponse(
        translated_text=translated_text,
        risk_score=score
    )
