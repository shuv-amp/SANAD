from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from sanad_api.database import Base
from sanad_api.services.glossary import find_glossary_hits, seed_default_glossary
from sanad_api.services.protection import detect_protected_entities
from sanad_api.services.scope import normalize_scope


def test_glossary_does_not_match_office_terms_inside_urls() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        seed_default_glossary(db)

        url_hits = find_glossary_hits(
            db,
            source_text="Visit https://municipality.example.gov for updates.",
            source_lang="en",
            target_lang="ne",
            domain="public_service",
            subdomain=normalize_scope("residence"),
        )
        office_hits = find_glossary_hits(
            db,
            source_text="The Municipality will review the application.",
            source_lang="en",
            target_lang="ne",
            domain="public_service",
            subdomain=normalize_scope("residence"),
        )

    assert url_hits == []
    assert [hit["source_term"] for hit in office_hits] == ["Municipality"]


def test_date_is_not_classified_as_phone_number() -> None:
    entities = detect_protected_entities("Date: 2026-04-21. Phone: +977-9841234567.", [])

    entity_by_text = {entity["text"]: entity["kind"] for entity in entities}

    assert entity_by_text["2026-04-21"] == "date"
    assert entity_by_text["+977-9841234567"] == "phone"
