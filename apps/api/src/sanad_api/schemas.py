from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DocumentCreateResponse(BaseModel):
    id: str
    status: str
    original_filename: str
    is_duplicate: bool = False


class SourceLanguageDetectionRead(BaseModel):
    source_lang: str | None
    confidence: str
    explanation: str
    segment_count: int


class TrustSummaryRead(BaseModel):
    total_segments: int
    approved_segments: int
    memory_reused_segments: int
    protected_values_total: int
    protected_values_preserved: int
    unresolved_review_flags: int


class DocumentSummary(BaseModel):
    id: str
    original_filename: str
    file_type: str
    source_lang: str
    target_lang: str
    domain: str
    subdomain: str | None
    status: str
    export_file_uri: str | None
    counts: dict[str, int]
    trust_summary: TrustSummaryRead
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TranslationRead(BaseModel):
    id: str
    candidate_text: str
    raw_candidate_text: str | None = None
    approved_text: str | None
    source_type: str
    provider_name: str
    memory_entry_id: str | None
    risk_score: float
    risk_reasons: list[dict] = Field(default_factory=list)
    status: str
    is_repaired: bool = False
    memory_provenance: dict | None = None

    model_config = ConfigDict(from_attributes=True)


class SegmentRead(BaseModel):
    id: str
    sequence: int
    segment_type: str
    source_text: str
    normalized_source: str
    protected_entities: list[dict]
    glossary_hits: list[dict]
    status: str
    translation: TranslationRead | None

    model_config = ConfigDict(from_attributes=True)


class TranslationPatch(BaseModel):
    candidate_text: str

    @field_validator("candidate_text")
    @classmethod
    def candidate_text_must_not_be_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("candidate_text must not be empty.")
        return cleaned


class ApproveRequest(BaseModel):
    text: str | None = None
    actor: str = "demo-reviewer"

    @field_validator("text")
    @classmethod
    def text_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is None:
            return value
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("text must not be empty.")
        return cleaned

    @field_validator("actor")
    @classmethod
    def actor_must_not_be_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("actor must not be empty.")
        return cleaned


class ExportRequest(BaseModel):
    format: str = "docx"


class GlobalApproveResponse(BaseModel):
    segment: SegmentRead
    propagated_count: int


class ProviderDebug(BaseModel):
    active_provider: str
    implemented: bool
    notes: str
