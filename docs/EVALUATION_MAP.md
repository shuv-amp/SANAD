# SANAD Evaluation Map

This file maps the submission to the judging criteria with concrete repo references.

## 1. Functionality and accuracy

Evidence:

- Upload -> process -> review -> approve -> export flow in `apps/api/src/sanad_api/routers/documents.py`
- Parsing, risk, and review services in `apps/api/src/sanad_api/services/`
- End-to-end tests in `apps/api/tests/`

Supported formats:

- DOCX, PDF, CSV, TSV, TXT
- DOC/ODT/RTF/HTML/MD when `textutil` is available (macOS)

Languages exercised in the demo path:

- English, Nepali, Tamang

## 2. Alignment with theme

- Public-service document workflows (residence certificates, ward notices)
- Protected-entity checks for identifiers and sensitive values
- Human review and scoped memory reuse
- Feedback pack for privacy-reduced contribution data

## 3. Code quality and architecture

Evidence:

- Modular services: parsing, providers, protection, risk, review, export, memory
- Provider contract with official/legacy/fallback tiers
- CI workflow in `.github/workflows/ci.yml`

Reference:

- `docs/ARCHITECTURE.md`

## 4. Documentation and demo

- Setup and demo workflow in `README.md`
- Architecture notes in `docs/ARCHITECTURE.md`
- This file for evaluation alignment and evidence pointers

## 5. System design and deployment

- `docker-compose.yml` runs API, web UI, and Gotenberg
- SQLite data stored on a Docker volume
- Health checks defined for API, web, and Gotenberg

## 6. User experience

- Document history and analytics dashboard
- Inline review with risk flags and trust summary
- Glossary and memory panels with provenance details
- Feedback pack available after full approval