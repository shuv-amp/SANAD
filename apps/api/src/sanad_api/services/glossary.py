import re

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from sanad_api.models import GlossaryTerm
from sanad_api.services.normalization import normalize_text
from sanad_api.services.scope import normalize_scope


DEFAULT_GLOSSARY = [
    ("en", "ne", "public_service", None, "Ward Office", "वडा कार्यालय", "office"),
    ("en", "ne", "public_service", None, "Municipality", "नगरपालिका", "office"),
    ("en", "ne", "public_service", None, "Rural Municipality", "गाउँपालिका", "office"),
    ("en", "ne", "public_service", None, "District Administration Office", "जिल्ला प्रशासन कार्यालय", "office"),
    ("en", "ne", "public_service", None, "Public Service Commission", "लोक सेवा आयोग", "office"),
    ("en", "ne", "public_service", "residence", "Certificate of Residence", "बसोबास प्रमाणपत्र", "term"),
]
URL_RE = re.compile(r"https?://[^\s,;]+", re.IGNORECASE)


def seed_default_glossary(db: Session) -> None:
    """Seed default glossary terms only into a fresh (empty) glossary table.
    
    If the user has already interacted with the glossary (adding or removing
    terms), we respect their changes and skip re-seeding entirely.
    """
    existing_count = db.scalar(select(func.count()).select_from(GlossaryTerm))
    if existing_count and existing_count > 0:
        return

    for source_lang, target_lang, domain, subdomain, source_term, target_term, term_type in DEFAULT_GLOSSARY:
        db.add(
            GlossaryTerm(
                source_lang=source_lang,
                target_lang=target_lang,
                domain=domain,
                subdomain=normalize_scope(subdomain),
                source_term=source_term,
                normalized_source_term=normalize_text(source_term),
                target_term=target_term,
                term_type=term_type,
            )
        )
    db.commit()


def find_glossary_hits(
    db: Session,
    *,
    source_text: str,
    source_lang: str,
    target_lang: str,
    domain: str,
    subdomain: str,
) -> list[dict]:
    terms = db.scalars(
        select(GlossaryTerm).where(
            GlossaryTerm.source_lang == source_lang,
            GlossaryTerm.target_lang == target_lang,
            GlossaryTerm.domain == domain,
            GlossaryTerm.subdomain.in_([subdomain, normalize_scope(None)]),
        )
    ).all()

    source_for_matching = URL_RE.sub(" ", source_text)
    source_norm = normalize_text(source_for_matching)
    hits: list[dict] = []
    for term in terms:
        needle = term.source_term if term.case_sensitive else term.normalized_source_term
        haystack = source_for_matching if term.case_sensitive else source_norm
        if needle in haystack:
            hits.append(
                {
                    "source_term": term.source_term,
                    "target_term": term.target_term,
                    "term_type": term.term_type,
                }
            )
    return hits
