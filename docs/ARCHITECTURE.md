# SANAD V1 Architecture

This document summarizes the current backend and UI architecture based on the active codebase.

## System layout

- API: FastAPI + SQLAlchemy
- UI: React + Vite
- Storage: SQLite + file storage root
- PDF conversion: Gotenberg for non-PDF to PDF export

## Request flow

1) Upload -> file saved to storage with checksum
2) Parse -> segments + location metadata
3) Protect -> glossary hits + protected entities
4) Memory -> scoped memory lookup and reuse
5) Provider -> official, legacy, or fixture fallback
6) Review -> approve/patch segments with risk flags
7) Export -> file export and feedback pack

## Parsing

SANAD supports text-based PDF, DOCX, CSV/TSV, and text formats (TXT/MD/HTML; DOC/ODT/RTF via `textutil` on macOS).

- **DOCX**: walks paragraphs and tables via `python-docx`.
- **PDF**: reads line blocks with `PyMuPDF`, preserves page+line bounding boxes.
- **CSV/TSV**: walks cells in row-major order.
- **Text**: splits on blank-line boundaries for review segments.

If parsing finds no translatable text, the API returns a clear error and the document is marked failed.

## Memory and review

Memory is scoped by:

- `source_lang`
- `target_lang`
- `domain`
- `subdomain`
- `normalized_source`

Memory hits are applied before provider translation. Approved translations write back to memory with provenance (document, segment, review event, actor, approval time).

Risk scoring is rule-based. Risk flags include:

- changed number
- changed protected entity
- glossary miss
- untranslated source token remains
- suspicious length deviation

## Providers

All providers implement:

```python
await provider.translate_batch(TranslationBatchRequest(...)) -> list[TranslationResult]
```

Current providers:

- `FixtureTranslationProvider`: deterministic demo path.
- `MockTranslationProvider`: contract tests only.
- `OfficialTmtApiProvider`: official `/lang-translate` with Bearer token auth.
- `LegacyTmtApiProvider`: public `/translate` fallback.
- `SmartTmtProvider` (`SANAD_ACTIVE_PROVIDER=tmt_api`): official -> legacy -> fixture.

Each translation result carries `provider_tier` (`tmt_official`, `tmt_legacy`, `fixture`, `fixture_fallback`) so the UI can show which tier produced each segment.

## Export and feedback pack

- DOCX/PDF/CSV/TSV/TXT exports require all segments approved.
- PDF to PDF export uses PyMuPDF; non-PDF to PDF uses Gotenberg.
- Feedback pack exports privacy-reduced rows and a manifest with counts and redaction mode.