import re
from dataclasses import dataclass
from pathlib import Path

from sanad_api.services.demo_content import DEMO_TEXT_BANK, PARAGRAPH_KEYS
from sanad_api.services.docx_io import parse_docx
from sanad_api.services.normalization import normalize_text
from sanad_api.services.pdf_document_io import PDF_DOCUMENT_TYPES, parse_pdf_document
from sanad_api.services.tabular_document_io import TABULAR_DOCUMENT_TYPES, parse_tabular_document
from sanad_api.services.text_document_io import TEXT_DOCUMENT_TYPES, parse_text_document


TOKEN_RE = re.compile(r"[A-Za-z]+|[\u0900-\u097F]+")
SHARED_DEVANAGARI_TOKENS = {
    # Loanwords and particles common across Nepali & Tamang
    "वडा",
    "फोन",
    "शुल्क",
    "सन्दर्भ",
    "नं",
    "का",
    "को",
    "ले",
    "से",
    "npr",
    "id",
    # Shared admin/borrowed words that appear in both languages
    "समीक्षा",
    "प्रमाणित",
    "ठेगाना",
    "फारम",
    "फाराम",
    "नगरपालिका",
}
TOKEN_WEIGHTS: dict[str, dict[str, float]] = {
    "en": {
        # Public-service domain vocabulary
        "certificate": 3.0,
        "residence": 3.0,
        "request": 2.5,
        "please": 2.0,
        "submit": 2.5,
        "form": 1.0,
        "office": 1.5,
        "municipality": 3.0,
        "application": 2.5,
        "review": 2.0,
        "updates": 2.0,
        "applicant": 2.0,
        "reference": 2.0,
        "service": 2.5,
        "hours": 2.5,
        "residents": 2.5,
        "citizenship": 3.0,
        "original": 1.5,
        "photo": 2.0,
        # General high-frequency English words
        "the": 1.0,
        "will": 1.0,
        "within": 1.5,
        "verify": 2.0,
        "visit": 1.0,
        "name": 1.0,
        "date": 1.0,
        "address": 2.0,
        "document": 2.5,
        "ward": 1.5,
        "fee": 1.5,
        "government": 3.0,
        "department": 2.5,
        "registration": 2.5,
        "approval": 2.5,
        "notice": 2.0,
        "authority": 2.5,
    },
    "ne": {
        # Nepali-specific grammar markers (Indo-Aryan)
        "छ": 2.0,         # existential "is" — uniquely Nepali, not used in Tamang
        "हो": 1.5,         # copula "is" (equative)
        "हुन्छ": 2.5,       # "it happens / okay"
        "थियो": 2.5,       # past tense "was"
        "छैन": 2.5,        # "is not"
        "गर्नुहोस्": 3.0,   # formal imperative "please do"
        "गर्नेछ": 2.0,      # future "will do"
        "भएको": 2.0,       # "having been"
        "लाई": 1.5,        # dative marker "to/for" — Nepali-specific
        "मा": 1.0,         # locative "in/at" — Nepali postposition
        "बाट": 2.0,        # ablative "from" — uniquely Nepali
        "सँग": 2.0,        # comitative "with" — uniquely Nepali
        "पनि": 1.5,        # "also"
        "र": 0.5,          # conjunction "and"
        # Nepali-specific vocabulary (not shared with Tamang)
        "कृपया": 3.0,       # "please" — Sanskrit-derived, Nepali-specific
        "बुझाउनुहोस्": 3.5,  # "please submit"
        "नगरपालिकाले": 3.5,  # "municipality" with ergative
        "आवेदन": 2.5,       # "application"
        "दिनभित्र": 2.5,    # "within days"
        "हेर्नुहोस्": 3.0,   # "please see"
        "निवेदकको": 3.0,    # "applicant's"
        "मिति": 2.0,        # "date"
        "बसोबास": 3.5,      # "residence" — uniquely Nepali
        "प्रमाणपत्र": 3.0,  # "certificate"
        "अनुरोध": 2.5,      # "request"
        "कार्यालयमा": 2.0,  # "in the office"
        "यो": 1.0,          # "this"
        "त्यो": 1.0,        # "that"
        "अपडेटका": 2.0,    # "for updates"
        "सेवा": 2.0,        # "service"
        "प्रदेश": 2.5,      # "province"
        "सरकार": 2.5,       # "government"
        "विवरण": 2.0,      # "details"
        "अनुमति": 2.5,      # "permission"
        "निर्णय": 2.5,      # "decision"
    },
    "tmg": {
        # Tamang-specific grammar markers (Tibeto-Burman)
        "मुला": 3.0,        # copula "is/are" — THE key Tamang marker
        "ङा": 2.5,          # first-person pronoun "I" — Tibeto-Burman root
        "ङोसेबास्यो": 3.5,  # Tamang term
        "ह्राङ": 2.5,       # "you" (formal)
        "थुजेछे": 3.5,      # "thank you" — uniquely Tamang (not a greeting)
        "हिम्बा": 3.0,      # "yes"
        "अहिम्बा": 3.0,     # "no"
        # Tamang suffix patterns visible as tokens
        "लासेला": 3.0,      # Tamang verb ending
        "लास्ह्युगो": 3.5,  # Tamang imperative form
        "गेदिमरि": 3.5,    # "office" with locative -ri
        "न्हाङरि": 2.5,    # "within" with -ri
        "स्ह्युसेनला": 3.5, # "application" with -la
        "अद्यावधिकला": 3.0, # "update" with -la
        "लागिरि": 2.5,     # "for" with -ri
        # Tamang-specific vocabulary
        "चु": 2.5,          # "this" — Tamang demonstrative
        "पेस": 2.5,         # "submit"
        "निगो": 3.0,        # "see/look" — Tamang verb
        "स्ह्युसेन": 2.5,   # "application" — Tamang form
        "पिन्बा": 2.5,     # Tamang name marker
        "कुनु": 2.5,        # "that day/when" — Tamang temporal marker
        "लाबा": 2.5,        # Tamang form
        "ह्रिबाला": 3.5,    # "residence" — Tamang
        "प्रमाणस्यो": 3.5,  # "certificate" — Tamang form
        "नगरपालिकासे": 3.5, # "municipality" with Tamang ergative -se
        "चिबा": 3.0,        # "living/staying" — Tamang
        "दिम": 2.0,         # "house/home" — Tamang (Tibetan root)
        "ज्याबा": 2.5,      # "good" — Tamang
        "खरांबा": 2.0,      # "how" — Tamang (dialectal variant)
        "ल्होस्सो": 3.5,    # "hello/greeting" — uniquely Tamang
        "फ्याफुल्ला": 3.5,  # "hello/greeting" — uniquely Tamang
    },
}
PHRASE_WEIGHTS: dict[str, dict[str, float]] = {"en": {}, "ne": {}, "tmg": {}}
for key in ("title", *PARAGRAPH_KEYS):
    for language, text in DEMO_TEXT_BANK[key].items():
        PHRASE_WEIGHTS[language][normalize_text(text)] = 6.0


@dataclass(frozen=True)
class _ScoredSample:
    scores: dict[str, float]
    latin_letters: int
    devanagari_letters: int


@dataclass(frozen=True)
class SourceLanguageDetection:
    source_lang: str | None
    confidence: str
    explanation: str
    segment_count: int


def detect_source_language(path: Path, file_type: str) -> SourceLanguageDetection:
    if file_type == "docx":
        parsed_segments = parse_docx(path)
    elif file_type in PDF_DOCUMENT_TYPES:
        parsed_segments = parse_pdf_document(path)
    elif file_type in TABULAR_DOCUMENT_TYPES:
        parsed_segments = parse_tabular_document(path, file_type)
    elif file_type in TEXT_DOCUMENT_TYPES:
        parsed_segments = parse_text_document(path, file_type)
    else:
        raise ValueError(f"Unsupported detection file type: {file_type}")

    sampled_segments = parsed_segments[:12]
    sample_text = " ".join(segment.source_text for segment in sampled_segments)
    document_score = _score_text_sample(sample_text)
    segment_votes = {"en": 0, "ne": 0, "tmg": 0}
    for segment in sampled_segments:
        scored = _score_text_sample(segment.source_text)
        ranked = sorted(scored.scores.items(), key=lambda item: item[1], reverse=True)
        if ranked[0][1] >= 3 and ranked[0][1] - ranked[1][1] >= 1.5:
            segment_votes[ranked[0][0]] += 1
    return _build_detection(document_score, segment_votes=segment_votes, segment_count=len(parsed_segments))


def detect_source_language_from_text(text: str, *, segment_count: int = 0) -> SourceLanguageDetection:
    scored = _score_text_sample(text)
    return _build_detection(scored, segment_votes={"en": 0, "ne": 0, "tmg": 0}, segment_count=segment_count)


def _score_text_sample(text: str) -> _ScoredSample:
    normalized = normalize_text(text)
    tokens = TOKEN_RE.findall(normalized)
    latin_letters = sum(ch.isascii() and ch.isalpha() for ch in text)
    devanagari_letters = sum("\u0900" <= ch <= "\u097F" for ch in text)

    scores = {"en": 0.0, "ne": 0.0, "tmg": 0.0}
    for language, phrase_map in PHRASE_WEIGHTS.items():
        for phrase, weight in phrase_map.items():
            if phrase and phrase in normalized:
                scores[language] += weight

    for token in tokens:
        if token in SHARED_DEVANAGARI_TOKENS:
            continue
        for language, token_map in TOKEN_WEIGHTS.items():
            scores[language] += token_map.get(token, 0.0)

    if latin_letters >= 18 and latin_letters > devanagari_letters * 1.5:
        scores["en"] += 4.0
    elif latin_letters > 0 and devanagari_letters == 0:
        scores["en"] += 2.5

    return _ScoredSample(scores=scores, latin_letters=latin_letters, devanagari_letters=devanagari_letters)


def _build_detection(
    scored: _ScoredSample,
    *,
    segment_votes: dict[str, int],
    segment_count: int,
) -> SourceLanguageDetection:
    scores = scored.scores
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    best_lang, best_score = ranked[0]
    second_score = ranked[1][1]

    if scored.latin_letters > 0 and scored.devanagari_letters == 0:
        confidence = "high" if scored.latin_letters >= 18 else "medium"
        return SourceLanguageDetection(
            source_lang="en",
            confidence=confidence,
            explanation="Detected mostly Latin-script text, so SANAD suggested English as the source language.",
            segment_count=segment_count,
        )

    if scored.devanagari_letters > 0 and best_score >= 8 and best_score - second_score >= 4:
        language_name = {"en": "English", "ne": "Nepali", "tmg": "Tamang"}[best_lang]
        return SourceLanguageDetection(
            source_lang=best_lang,
            confidence="high",
            explanation=(
                f"Detected strong {language_name} phrase patterns"
                f"{_vote_suffix(segment_votes, best_lang)}."
            ),
            segment_count=segment_count,
        )

    if scored.devanagari_letters > 0 and best_score >= 4 and best_score - second_score >= 1.5:
        language_name = {"en": "English", "ne": "Nepali", "tmg": "Tamang"}[best_lang]
        return SourceLanguageDetection(
            source_lang=best_lang,
            confidence="medium",
            explanation=f"Detected likely {language_name} wording, but SANAD is keeping the final choice manual.",
            segment_count=segment_count,
        )

    if scored.devanagari_letters > 0:
        return SourceLanguageDetection(
            source_lang=None,
            confidence="low",
            explanation="Detected Devanagari text, but the visible wording overlaps between Nepali and Tamang. Please confirm manually.",
            segment_count=segment_count,
        )

    return SourceLanguageDetection(
        source_lang=None,
        confidence="low",
        explanation="Could not confidently detect the source language from the current document sample.",
        segment_count=segment_count,
    )


def _vote_suffix(segment_votes: dict[str, int], language: str) -> str:
    votes = segment_votes.get(language, 0)
    if votes <= 0:
        return " in the document preview"
    return f" across {votes} segment{'s' if votes != 1 else ''}"
