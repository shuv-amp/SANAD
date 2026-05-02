import re


ENTITY_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("email", re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")),
    ("url", re.compile(r"https?://[^\s,;]+", re.IGNORECASE)),
    ("money", re.compile(r"(?:NPR|Rs\.?|रु\.?|\$)\s?\d[\d,]*(?:\.\d+)?", re.IGNORECASE)),
    ("date", re.compile(r"\b(?:[0-9०-९]{4}[-/][0-9०-९]{1,2}[-/][0-9०-९]{1,2}|[0-9०-९]{1,2}[-/][0-9०-९]{1,2}[-/][0-9०-९]{2,4})\b")),
    ("ward", re.compile(r"\bWard\s*(?:No\.?|Number)?\s*[-:]?\s*\d+\b", re.IGNORECASE)),
    (
        "id",
        re.compile(
            r"\b(?:ID|Ref|Reference|Citizenship)\s*(?:ID|No\.?|Number)?\s*[-:]?\s*[A-Z0-9/-]*\d[A-Z0-9/-]{1,}\b",
            re.IGNORECASE,
        ),
    ),
    ("id", re.compile(r"\b[A-Z]{2,}(?:-[A-Z0-9]{2,})+\b")),
    ("phone", re.compile(r"(?:\+[9९][7७]{2}[-\s]?)?(?:[0-9०-९][-\s]?){7,12}[0-9०-९]")),
    ("number", re.compile(r"\b[0-9०-९]+(?:[,.][0-9०-९]+)*\b")),
]


def detect_protected_entities(source_text: str, glossary_hits: list[dict]) -> list[dict]:
    entities: list[dict] = []
    occupied: list[range] = []

    for kind, pattern in ENTITY_PATTERNS:
        for match in pattern.finditer(source_text):
            span = range(match.start(), match.end())
            if any(_overlaps(span, existing) for existing in occupied):
                continue
            occupied.append(span)
            entities.append({"kind": kind, "text": match.group(0), "start": match.start(), "end": match.end()})

    for hit in glossary_hits:
        if hit.get("term_type") != "office":
            continue
        source_term = hit["source_term"]
        start = source_text.lower().find(source_term.lower())
        if start >= 0:
            entities.append(
                {
                    "kind": "office",
                    "text": source_text[start : start + len(source_term)],
                    "start": start,
                    "end": start + len(source_term),
                    "target_term": hit["target_term"],
                }
            )

    return sorted(entities, key=lambda item: (item["start"], item["end"]))


def _overlaps(left: range, right: range) -> bool:
    return left.start < right.stop and right.start < left.stop
