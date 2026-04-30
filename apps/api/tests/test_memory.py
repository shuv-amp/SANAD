from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from sanad_api.database import Base
from sanad_api.models import MemoryEntry
from sanad_api.services.memory import lookup_memory
from sanad_api.services.normalization import normalize_text
from sanad_api.services.scope import normalize_scope


def test_memory_lookup_is_scoped_by_domain_and_subdomain() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add(
            MemoryEntry(
                source_lang="en",
                target_lang="ne",
                domain="public_service",
                subdomain="residence",
                source_text="Please submit this form to the Ward Office.",
                normalized_source=normalize_text("Please submit this form to the Ward Office."),
                target_text="कृपया यो फारम वडा कार्यालयमा बुझाउनुहोस्।",
            )
        )
        db.commit()

        assert (
            lookup_memory(
                db,
                source_lang="en",
                target_lang="ne",
                domain="public_service",
                subdomain="residence",
                normalized_source=normalize_text("Please submit this form to the Ward Office."),
            )
            is not None
        )
        assert (
            lookup_memory(
                db,
                source_lang="en",
                target_lang="ne",
                domain="public_service",
                subdomain=normalize_scope(None),
                normalized_source=normalize_text("Please submit this form to the Ward Office."),
            )
            is None
        )
        assert (
            lookup_memory(
                db,
                source_lang="en",
                target_lang="ne",
                domain="legal_notice",
                subdomain="residence",
                normalized_source=normalize_text("Please submit this form to the Ward Office."),
            )
            is None
        )

