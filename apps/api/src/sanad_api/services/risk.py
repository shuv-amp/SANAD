import re

from sanad_api.services.normalization import digits_to_ascii, display_normalize, normalize_text, to_devanagari_digits


NUMBER_RE = re.compile(r"[0-9०-९]+(?:[,.][0-9०-९]+)*")
LATIN_TOKEN_RE = re.compile(r"\b[A-Za-z][A-Za-z-]{3,}\b")
LIKELY_NAME_TOKEN_RE = re.compile(r"^[A-Z][a-z]+(?:[-'][A-Z][a-z]+)?$")
NON_NAME_TOKENS = {
    "Applicant",
    "Application",
    "Certificate",
    "Citizenship",
    "Date",
    "District",
    "Fee",
    "Form",
    "ID",
    "Municipality",
    "Name",
    "Office",
    "Phone",
    "Reference",
    "Request",
    "Residence",
    "Service",
    "Ward",
}


def score_translation(
    *,
    source_text: str,
    translated_text: str,
    protected_entities: list[dict],
    glossary_hits: list[dict],
) -> tuple[float, list[dict]]:
    reasons: list[dict] = []

    source_numbers = _extract_numbers(source_text)
    target_numbers = _extract_numbers(translated_text)
    if not source_numbers.issubset(target_numbers):
        reasons.append(
            {
                "code": "changed_number",
                "label": "Changed number",
                "detail": f"Expected numbers {sorted(source_numbers)} in translation.",
            }
        )

    for entity in protected_entities:
        kind = entity["kind"]
        if kind in {"number"}:
            continue
        if not is_protected_entity_preserved(entity, translated_text):
            reasons.append(
                {
                    "code": "changed_protected_entity",
                    "label": "Changed protected entity",
                    "detail": f"Expected a preserved {kind} value in translation.",
                }
            )

    for hit in glossary_hits:
        if hit["target_term"] not in translated_text:
            reasons.append(
                {
                    "code": "glossary_miss",
                    "label": "Glossary miss",
                    "detail": f"Expected glossary term {hit['target_term']!r}.",
                }
            )

    untranslated = _remaining_source_tokens(source_text, translated_text, protected_entities, glossary_hits)
    if untranslated:
        reasons.append(
            {
                "code": "untranslated_token",
                "label": "Untranslated token remains",
                "detail": f"Possible untranslated token(s): {', '.join(untranslated[:5])}.",
            }
        )

    source_len = max(len(source_text.strip()), 1)
    target_len = len(translated_text.strip())
    ratio = target_len / source_len
    if ratio < 0.35 or ratio > 3.0:
        reasons.append(
            {
                "code": "length_deviation",
                "label": "Suspicious length deviation",
                "detail": f"Target/source length ratio is {ratio:.2f}.",
            }
        )

    return float(len(reasons)), reasons


def count_preserved_protected_entities(protected_entities: list[dict], translated_text: str) -> tuple[int, int]:
    total = len(protected_entities)
    preserved = sum(1 for entity in protected_entities if is_protected_entity_preserved(entity, translated_text))
    return preserved, total


def is_protected_entity_preserved(entity: dict, translated_text: str) -> bool:
    if entity.get("kind") == "number":
        entity_numbers = _extract_numbers(str(entity.get("text", "")))
        if not entity_numbers:
            return False
        return entity_numbers.issubset(_extract_numbers(translated_text))
    return _protected_entity_present(entity, translated_text)


def protected_entity_variants(entity: dict) -> set[str]:
    return _entity_variants(entity)


def is_probable_name_segment(source_text: str, translated_text: str) -> bool:
    return _is_probable_name_segment(source_text, translated_text)


def _remaining_source_tokens(
    source_text: str,
    translated_text: str,
    protected_entities: list[dict],
    glossary_hits: list[dict],
) -> list[str]:
    if _is_probable_name_segment(source_text, translated_text):
        return []

    translated_norm = normalize_text(translated_text)
    glossary_source_tokens = {
        token.casefold()
        for hit in glossary_hits
        for token in LATIN_TOKEN_RE.findall(hit.get("source_term", ""))
    }
    protected_ranges = [
        range(entity["start"], entity["end"])
        for entity in protected_entities
        if isinstance(entity.get("start"), int) and isinstance(entity.get("end"), int)
    ]
    protected_source_tokens = {
        token.casefold()
        for entity in protected_entities
        for token in LATIN_TOKEN_RE.findall(entity.get("text", ""))
    }
    tokens: list[str] = []
    for match in LATIN_TOKEN_RE.finditer(source_text):
        token = match.group(0)
        lowered = token.casefold()
        if lowered in glossary_source_tokens:
            continue
        if lowered in {"http", "https", "example", "www"}:
            continue
        if any(_overlaps(match.span(), protected_range) for protected_range in protected_ranges):
            continue
        if lowered in protected_source_tokens:
            continue
        if lowered in translated_norm:
            tokens.append(token)
    return sorted(set(tokens))


def _extract_numbers(text: str) -> set[str]:
    return {digits_to_ascii(match) for match in NUMBER_RE.findall(text)}


def _protected_entity_present(entity: dict, translated_text: str) -> bool:
    translated_display = display_normalize(translated_text)
    translated_ascii_digits = digits_to_ascii(translated_display)
    for variant in _entity_variants(entity):
        normalized_variant = display_normalize(variant)
        if normalized_variant in translated_display:
            return True
        if digits_to_ascii(normalized_variant) in translated_ascii_digits:
            return True
    return False


def _entity_variants(entity: dict) -> set[str]:
    kind = entity["kind"]
    text = entity["text"]
    if kind == "office":
        target_term = entity.get("target_term")
        return {target_term} if isinstance(target_term, str) and target_term else {text}
    if kind == "date":
        return {text, to_devanagari_digits(text)}
    if kind == "money":
        return _money_variants(text)
    if kind == "ward":
        return _ward_variants(text)
    if kind in {"url", "email", "phone", "id"}:
        return {text}
    return {text, to_devanagari_digits(text)}


def _money_variants(text: str) -> set[str]:
    variants = {text, to_devanagari_digits(text)}
    amount_match = NUMBER_RE.search(text)
    if amount_match:
        amount = digits_to_ascii(amount_match.group(0))
        localized_amount = to_devanagari_digits(amount)
        variants.update(
            {
                f"NPR {localized_amount}",
                f"रु {localized_amount}",
                f"रु. {localized_amount}",
            }
        )
    return variants


def _ward_variants(text: str) -> set[str]:
    variants = {text, to_devanagari_digits(text)}
    number_match = NUMBER_RE.search(text)
    if number_match:
        number = digits_to_ascii(number_match.group(0))
        localized_number = to_devanagari_digits(number)
        variants.update(
            {
                f"वडा नं. {localized_number}",
                f"वडा नं. {number}",
                f"वडा नम्बर {localized_number}",
                f"वडा नम्बर {number}",
            }
        )
    return variants


def _is_probable_name_segment(source_text: str, translated_text: str) -> bool:
    source = source_text.strip()
    target = translated_text.strip()
    if not source or source != target:
        return False
    if any(character.isdigit() for character in source):
        return False
    if any(character in ":/.@_" for character in source):
        return False
    tokens = source.split()
    if not 1 < len(tokens) <= 3:
        return False
    if any(token in NON_NAME_TOKENS for token in tokens):
        return False
    return all(LIKELY_NAME_TOKEN_RE.fullmatch(token) for token in tokens)


def _overlaps(span: tuple[int, int], protected_range: range) -> bool:
    return span[0] < protected_range.stop and protected_range.start < span[1]
