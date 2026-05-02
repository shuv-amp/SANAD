import re

from sanad_api.services.normalization import (
    digits_to_ascii, 
    display_normalize, 
    normalize_text, 
    to_devanagari_digits,
    contains_devanagari
)


NUMBER_RE = re.compile(r"[+0-9०-९]+(?:[,.\-:/][+0-9०-९]+)*")
LATIN_TOKEN_RE = re.compile(r"\b[A-Za-z][A-Za-z-]{1,}\b")
LIKELY_NAME_TOKEN_RE = re.compile(r"^[A-Z][a-z]+$")
REPEATED_WORD_RE = re.compile(r"(\b\w+\b)(?:\s+\1){3,}", re.IGNORECASE | re.UNICODE)
PUNCTUATION_PAIRS = [("(", ")"), ("[", "]"), ("{", "}"), ('"', '"')]
SYMBOL_RE = re.compile(r"[@#$%^&*_=+|\\<>]")
MARKUP_RE = re.compile(r"[•\-\*|:]")
DATE_PATTERN_RE = re.compile(r"(\d{1,4}[-./]\d{1,2}[-./]\d{1,4})")
ENGLISH_NEGATION = {"not", "no", "never", "none", "neither", "nor", "cannot", "don't", "can't", "won't"}
NEPALI_NEGATION = {"छैन", "हुँदैन", "नगर्नु", "नगर", "नाईं", "होइन", "छैनन्", "हुन्न", "थिएन"}
HONORIFIC_HIGH = {"तपाईं", "हुनुहुन्छ", "होला", "गर्नुहोस्", "पाल्नुहोस्"}
HONORIFIC_LOW = {"तँ", "तिमी", "छौ", "गछौ", "गरे", "गर"}
INSTRUCTION_KEYWORDS = {"translate", "nepali", "language", "following", "below", "text", "sure", "okay"}
PLACEHOLDER_RE = re.compile(r"(\{\{[^}]+\}\}|\{[^}]+\}|\[[A-Z_]+\])")
DIRECTIONAL_PAIRS = [
    ({"increase", "rise", "gain", "profit", "up"}, {"घट्नु", "घाटा", "कम", "तल"}), # Positive in S -> Negative in T
    ({"decrease", "fall", "loss", "down"}, {"बढ्नु", "नाफा", "बढी", "माथि"}), # Negative in S -> Positive in T
]
CURRENCY_PAIRS = [
    ({"$", "usd", "dollar"}, {"डलर", "अमेरिकी डलर"}),
    ({"rs", "npr", "rupee"}, {"रु", "रुपैयाँ", "नेपाली रुपैयाँ", "एनपीआर", "रुपैया"}),
]
PREFERRED_CURRENCY_SYMBOLS = {
    "rs": "रु",
    "npr": "रु",
    "usd": "$",
}
FORBIDDEN_TERMS = [
    # (Forbidden pattern, Label, Severity)
    (re.compile(r"\bकागज\b", re.IGNORECASE), "Informal terminology used for document", "low"),
    (re.compile(r"\bCitizenship paper\b", re.IGNORECASE), "Informal terminology for Citizenship Certificate", "medium"),
]
LOGICAL_CONNECTIVE_PAIRS = [
    ({"however", "but", "yet", "nevertheless"}, {"तर", "यद्यपि", "तापनि"}),
    ({"therefore", "so", "consequently", "thus"}, {"तसर्थ", "त्यसैले", "अतः"}),
    ({"because", "since", "as"}, {"किनभने", "कारण", "ले गर्दा"}),
]
LEGAL_MODAL_PAIRS = [
    ({"must", "shall", "should", "mandatory"}, {"पर्नेछ", "अनिवार्य", "हुनुपर्छ"}),
    ({"may", "can", "permissible"}, {"सक्नेछ", "मन्जुरी", "पाउनेछ"}),
]
LEGAL_ANCHOR_PAIRS = [
    ({"provided that", "subject to"}, {"बशर्ते", "अधिनमा"}),
    ({"notwithstanding", "regardless"}, {"तापनि", "वावजुद"}),
]
DOCUMENT_LANDMARKS = [
    ({"signature", "signed"}, {"हस्ताक्षर", "दस्तखत"}),
    ({"stamp", "seal"}, {"छाप", "मोहर", "लाहा"}),
    ({"verified", "certified"}, {"रुजु प्रमाणित", "प्रमाणित"}),
    ({"official", "authorized"}, {"आधिकारिक", "अधिकृत"}),
    ({"ward"}, {"वडा"}),
    ({"house"}, {"घर"}),
    ({"no", "number"}, {"नं", "नम्बर"}),
]
ANACHRONISM_MAP = [
    ({"vdc", "village development committee"}, {"गाउँपालिका", "नगरपालिका"}),
    ({"zonal", "zone"}, {"प्रदेश", "जिल्ला"}),
]
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
    "Call",
    "Card",
    "Fees",
    "Fee",
    "NPR",
    "Total",
    "Amount",
    "Price",
}
INSTITUTIONAL_WHITELIST = NON_NAME_TOKENS


def score_translation(
    *,
    source_text: str,
    translated_text: str,
    protected_entities: list[dict],
    glossary_hits: list[dict],
    target_lang: str = "en",
) -> tuple[float, list[dict]]:
    reasons: list[dict] = []

    source_numbers = _extract_numbers(source_text)
    target_numbers = _extract_numbers(translated_text)
    
    # Absolute Omission Check
    if not translated_text.strip() and source_text.strip():
        reasons.append({
            "code": "total_omission",
            "label": "CRITICAL: Empty translation",
            "severity": "high",
            "detail": "The AI failed to produce any translation text for this segment.",
        })
        return 10.0, reasons


    if not source_numbers.issubset(target_numbers):
        reasons.append(
            {
                "code": "changed_number",
                "label": "Changed number",
                "severity": "high",
                "repairable": True,
                "detail": f"Expected numbers {sorted(source_numbers)} in translation.",
            }
        )

    # Integrity Auditor: Number-Context Alignment Check (Deep Swap Detection)
    source_context = _extract_numbers_with_context(source_text)
    target_context = _extract_numbers_with_context(translated_text)
    
    # If we have multiple numbers, check for swaps
    if len(source_context) >= 2:
        for num_s, words_s in source_context.items():
            if num_s in target_context:
                words_t = target_context[num_s]
                # Simplified but Robust Bi-directional Swap Check:
                # 1. Identify which landmarks are near this number in the source
                source_landmarks = set()
                for s_word in words_s:
                    s_word_lower = s_word.lower()
                    for s_set, t_set in DOCUMENT_LANDMARKS:
                        if s_word_lower in s_set:
                            source_landmarks.add(tuple(t_set)) # Track the expected Nepali landmarks
                
                # 2. Check if those same landmarks are now near a DIFFERENT number in target
                if source_landmarks:
                    for num_other, words_other_t in target_context.items():
                        if num_other == num_s: continue
                        for t_set in source_landmarks:
                            if any(t_word in words_other_t for t_word in t_set):
                                reasons.append({
                                    "code": "number_swap",
                                    "label": "Critical: Possible number swap",
                                    "severity": "high",
                                    "detail": f"The label for number {num_s} appears to have been reassigned to {num_other}.",
                                })
                                break
                        else: continue
                        break

    for entity in protected_entities:
        kind = entity["kind"]
        # We now process all kinds including numbers for script/position checks
        if not is_protected_entity_preserved(entity, translated_text):
            reasons.append(
                {
                    "code": "changed_protected_entity",
                    "label": "Changed protected entity",
                    "severity": "high",
                    "repairable": True,
                    "detail": f"Expected a preserved {kind} value in translation.",
                }
            )
        
        # New: Position check
        shift_detected, script_mismatch = _check_entity_metadata(entity, translated_text)
        if shift_detected:
             reasons.append({
                "code": "position_shift",
                "label": "Suspicious position shift",
                "severity": "medium",
                "detail": f"The {kind} moved significantly within the segment.",
            })
        if script_mismatch:
             reasons.append({
                "code": "script_mismatch",
                "label": "Script mismatch",
                "severity": "medium",
                "detail": f"The {kind} value should be localized to the target script.",
            })

    for hit in glossary_hits:
        if hit["target_term"] not in translated_text:
            reasons.append(
                {
                    "code": "glossary_miss",
                    "label": "Glossary miss",
                    "severity": "medium",
                    "detail": f"Expected glossary term {hit['target_term']!r}.",
                }
            )

    untranslated = _remaining_source_tokens(source_text, translated_text, protected_entities, glossary_hits)
    
    # Hallucination: Immediate Repetition Check (e.g. "मूल्य मूल्य")
    # Only flag if the source doesn't have the same repetition pattern
    target_words = [w for w in translated_text.split() if len(w) > 1]
    source_words = [w for w in source_text.split() if len(w) > 1]
    
    has_target_rep = any(target_words[i] == target_words[i+1] for i in range(len(target_words)-1))
    has_source_rep = any(source_words[i] == source_words[i+1] for i in range(len(source_words)-1))
    
    if has_target_rep and not has_source_rep:
        reasons.append({
            "code": "hallucination_repetition",
            "label": "Repetition loop detected",
            "severity": "high",
            "repairable": True,
            "detail": "The AI repeated words in a way that wasn't in the source text.",
        })
    if untranslated:
        reasons.append(
            {
                "code": "untranslated_token",
                "label": "Untranslated token remains",
                "severity": "medium",
                "repairable": True,
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
                "severity": "low",
                "repairable": ratio < 0.5, # Likely truncated if too short
                "detail": f"Target/source length ratio is {ratio:.2f}.",
            }
        )

    # Untranslated segment check
    # Exempt pure technical segments or probable name segments
    is_technical = False
    if len(protected_entities) == 1 and len(translated_text.strip()) < len(protected_entities[0]["text"]) + 5:
         if protected_entities[0]["kind"] in {"url", "email", "id", "phone"}:
             is_technical = True

    if source_text.strip() == translated_text.strip() and len(source_text.strip()) > 3 and not is_technical:
        if not _is_probable_name_segment(source_text, translated_text) and LATIN_TOKEN_RE.search(translated_text):
            reasons.append({
                "code": "untranslated_segment",
                "label": "Untranslated segment",
                "severity": "medium",
                "detail": "The translation is identical to the source and appears untranslated.",
            })

    # Core Integrity Checks
    _check_punctuation_balance(source_text, translated_text, reasons)
    _check_symbol_leak(source_text, translated_text, reasons)
    _check_script_balance(translated_text, protected_entities, reasons, glossary_hits)
    _check_repetition(translated_text, reasons)
    _check_markup_integrity(source_text, translated_text, reasons)
    _check_date_locale(source_text, translated_text, reasons)
    _check_omission_addition(source_text, translated_text, reasons)
    _check_negation_flip(source_text, translated_text, reasons)
    _check_honorific_consistency(translated_text, reasons)
    _check_instruction_leak(translated_text, reasons)
    _check_placeholder_integrity(source_text, translated_text, reasons)
    _check_directional_flip(source_text, translated_text, reasons)
    _check_currency_integrity(source_text, translated_text, reasons, target_lang=target_lang)
    _check_list_sequence(source_text, translated_text, reasons)
    _check_forbidden_terms(translated_text, reasons)
    _check_logical_flow(source_text, translated_text, reasons)
    _check_identity_swap(source_text, translated_text, reasons)
    _check_entity_anchors(source_text, translated_text, reasons)
    _check_professional_landmarks(source_text, translated_text, reasons)
    _check_certification_markers(source_text, translated_text, reasons)
    _check_date_hallucination(source_text, translated_text, reasons)
    _check_anachronisms(source_text, translated_text, reasons)
    _check_transliteration_drift(source_text, translated_text, reasons)
    _check_legal_modals(source_text, translated_text, reasons)
    _check_legalisms(translated_text, reasons)
    _check_legal_anchors(source_text, translated_text, reasons)
    _check_ghost_entities(source_text, translated_text, reasons, target_lang=target_lang)
    _check_polarity(source_text, translated_text, reasons)
    _check_professional_spacing(translated_text, reasons)
    _check_official_abbreviations(translated_text, reasons)
    
    # Final Unicode Sanitation check
    sanitized = _sanitize_unicode(translated_text)
    if sanitized != translated_text:
        reasons.append({
            "code": "unicode_sanitized",
            "label": "Hidden characters removed",
            "severity": "low",
            "detail": "SANAD automatically stripped invisible Unicode characters to prevent document corruption.",
        })

    # Suspicious filler check
    FILLER_PHRASES = ["here is the", "sure,", "translation:", "translated text:"]
    if any(phrase in translated_text.lower()[:50] for phrase in FILLER_PHRASES):
        reasons.append({
            "code": "ai_filler",
            "label": "AI chatter detected",
            "severity": "low",
            "detail": "The translation contains conversational filler text from the AI.",
        })

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


def _check_entity_metadata(entity: dict, translated_text: str) -> tuple[bool, bool]:
    """Returns (shift_detected, script_mismatch)"""
    source_text = entity.get("text", "")
    if not source_text or not translated_text:
        return False, False
        
    start = entity.get("start", 0)
    source_len = entity.get("segment_source_len") or len(translated_text) or 100 # Fallback
    rel_start_source = start / source_len
    
    translated_display = display_normalize(translated_text)
    best_rel_start_target = None
    script_mismatch = False
    
    for variant in _entity_variants(entity):
        norm_v = display_normalize(variant)
        idx = translated_display.find(norm_v)
        if idx != -1:
            best_rel_start_target = idx / len(translated_display)
            # If we matched a variant that is NOT Devanagari, but it COULD be localized,
            # it might be a script mismatch (unless it's a technical ID/Phone/URL).
            if not contains_devanagari(norm_v) and to_devanagari_digits(norm_v) != norm_v:
                if entity.get("kind") not in {"url", "email", "id", "phone"}:
                    script_mismatch = True
            break
            
    if best_rel_start_target is None:
        # Check ASCII fallback
        translated_ascii = digits_to_ascii(translated_display)
        idx_ascii = translated_ascii.find(digits_to_ascii(source_text))
        if idx_ascii != -1:
            best_rel_start_target = idx_ascii / len(translated_display)
            if to_devanagari_digits(source_text) != source_text:
                script_mismatch = True

    if best_rel_start_target is not None:
        # SOV-Aware Positioning: English (SVO) -> Nepali (SOV) causes natural object shifts.
        # We use a more relaxed threshold for short segments where shifts are mathematically larger.
        threshold = 0.75 if len(translated_display) < 60 else 0.6
        if abs(rel_start_source - best_rel_start_target) > threshold:
            return True, script_mismatch
            
    return False, script_mismatch


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
                f"एनपीआर {localized_amount}",
                f"रुपैया {localized_amount}",
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
def _check_punctuation_balance(source: str, target: str, reasons: list[dict]):
    for open_p, close_p in PUNCTUATION_PAIRS:
        if open_p == close_p:
            if source.count(open_p) % 2 != target.count(open_p) % 2:
                 reasons.append({
                    "code": "punctuation_mismatch",
                    "label": "Mismatched quotes",
                    "severity": "medium",
                    "detail": f"Quote marks are unbalanced compared to the source.",
                })
        else:
            if source.count(open_p) != target.count(open_p) or source.count(close_p) != target.count(close_p):
                 reasons.append({
                    "code": "punctuation_mismatch",
                    "label": "Mismatched brackets",
                    "severity": "medium",
                    "detail": f"Brackets '{open_p}{close_p}' are unbalanced or missing.",
                })

def _check_symbol_leak(source: str, target: str, reasons: list[dict]):
    source_symbols = set(SYMBOL_RE.findall(source))
    target_symbols = set(SYMBOL_RE.findall(target))
    leak = target_symbols - source_symbols
    if leak:
        reasons.append({
            "code": "symbol_leak",
            "label": "Suspicious characters",
            "severity": "medium",
            "detail": f"Translation contains unexpected symbols: {', '.join(leak)}",
        })

def _extract_numbers_with_context(text: str, window: int = 15) -> dict[str, list[str]]:
    """Extracts numbers along with their surrounding context words for integrity checking."""
    results = {}
    normalized = display_normalize(text)
    # We use digits_to_ascii for mapping but keep original for script check
    for match in NUMBER_RE.finditer(normalized):
        num_val = digits_to_ascii(match.group(0))
        # Get context
        start = max(0, match.start() - window)
        end = min(len(normalized), match.end() + window)
        context = normalized[start:match.start()] + " " + normalized[match.end():end]
        # Clean context for words (2+ chars, ignore digits)
        words = re.findall(r"[^\s\d]{2,}", context)
        if num_val not in results:
            results[num_val] = []
        results[num_val].extend(words)
    return results

def _check_script_balance(target: str, entities: list[dict], reasons: list[dict], glossary_hits: list[dict] = None):
    if not target or not contains_devanagari(target):
        return
        
    latin_chars = sum(1 for c in target if 'a' <= c.lower() <= 'z')
    total_chars = len(target)
    
    # Integrity Auditor: Exclude Glossary terms from Latin penalty (Prevents False Flags)
    excluded_latin_len = 0
    if glossary_hits:
        for hit in glossary_hits:
            target_term = hit.get("target_term", "")
            if any('a' <= c.lower() <= 'z' for c in target_term):
                excluded_latin_len += len(target_term)
                
    for e in entities:
        if e.get("kind") in {"url", "email"}:
            excluded_latin_len += len(e.get("text", ""))
            
    latin_chars = max(0, latin_chars - excluded_latin_len)
            
    if total_chars > 20 and (latin_chars / total_chars) > 0.35:
        reasons.append({
            "code": "script_imbalance",
            "label": "Suspicious script mixing",
            "severity": "medium",
            "detail": "Translation contains an unusually high amount of English text.",
        })

def _check_repetition(target: str, reasons: list[dict]):
    if REPEATED_WORD_RE.search(target):
        reasons.append({
            "code": "word_repetition",
            "label": "Repetitive content",
            "severity": "medium",
            "detail": "The translation contains highly repetitive words (possible AI loop).",
        })
def _check_markup_integrity(source: str, target: str, reasons: list[dict]):
    s_marks = MARKUP_RE.findall(source)
    t_marks = MARKUP_RE.findall(target)
    if len(s_marks) != len(t_marks):
        reasons.append({
            "code": "markup_mismatch",
            "label": "Layout mismatch",
            "severity": "low",
            "detail": f"Structural symbols (bullets, bars) don't match source count.",
        })

def _check_date_locale(source: str, target: str, reasons: list[dict]):
    s_dates = DATE_PATTERN_RE.findall(source)
    t_dates = DATE_PATTERN_RE.findall(digits_to_ascii(target))
    if len(s_dates) != len(t_dates):
        reasons.append({
            "code": "date_mismatch",
            "label": "Date missing or added",
            "severity": "high",
            "repairable": True,
            "detail": "A date value appears to have been omitted or hallucinated.",
        })

def _check_omission_addition(source: str, target: str, reasons: list[dict]):
    s_words = len(re.findall(r"\w+", source))
    t_words = len(re.findall(r"\w+", target))
    if s_words > 10:
        ratio = t_words / s_words
        if ratio < 0.4:
            reasons.append({
                "code": "major_omission",
                "label": "Possible major omission",
                "severity": "high",
                "detail": f"Translation is significantly shorter ({ratio:.2f}) than source. Clause may be missing.",
            })
        elif ratio > 2.5:
            reasons.append({
                "code": "major_addition",
                "label": "Possible major addition",
                "severity": "medium",
                "detail": f"Translation is significantly longer ({ratio:.2f}) than source. AI may have hallucinated text.",
            })

def _check_negation_flip(source: str, target: str, reasons: list[dict]):
    # Advanced Refinement: Ignore "No." as an abbreviation for "Number"
    # We strip "no." followed by a digit before checking for real negatives
    source_clean = re.sub(r"\bno\.?\s*\d+", " ", source, flags=re.IGNORECASE)
    s_words = set(re.findall(r"\w+", source_clean.lower()))
    t_text = digits_to_ascii(target)
    
    has_s_neg = any(w in ENGLISH_NEGATION for w in s_words)
    has_t_neg = any(w in t_text for w in NEPALI_NEGATION)
    
    if has_s_neg and not has_t_neg:
        reasons.append({
            "code": "negation_flip",
            "label": "Critical: Negation missing",
            "severity": "high",
            "detail": "The English source contains a negative ('not/no') but the Nepali translation appears affirmative.",
        })

def _check_honorific_consistency(target: str, reasons: list[dict]):
    has_high = any(w in target for w in HONORIFIC_HIGH)
    has_low = any(w in target for w in HONORIFIC_LOW)
    
    if has_high and has_low:
        reasons.append({
            "code": "honorific_inconsistency",
            "label": "Inconsistent honorifics",
            "severity": "medium",
            "detail": "Mixed politeness levels detected (High/Low respect) in the same segment.",
        })

def _check_instruction_leak(target: str, reasons: list[dict]):
    # Check first 5 words for instruction leakage
    words = re.findall(r"[a-z]{4,}", target.lower())[:5]
    leaks = [w for w in words if w in INSTRUCTION_KEYWORDS]
    if leaks:
        reasons.append({
            "code": "instruction_leak",
            "label": "Possible instruction leak",
            "severity": "medium",
            "detail": f"The translation may contain prompt instructions like: {', '.join(leaks)}",
        })

def _check_placeholder_integrity(source: str, target: str, reasons: list[dict]):
    s_placeholders = set(PLACEHOLDER_RE.findall(source))
    t_placeholders = set(PLACEHOLDER_RE.findall(target))
    
    missing = s_placeholders - t_placeholders
    if missing:
        reasons.append({
            "code": "placeholder_broken",
            "label": "Template placeholder broken",
            "severity": "high",
            "detail": f"Critical placeholders missing or translated: {', '.join(missing)}",
        })

def _check_directional_flip(source: str, target: str, reasons: list[dict]):
    source_lower = source.lower()
    for s_set, t_opposites in DIRECTIONAL_PAIRS:
        if any(w in source_lower for w in s_set):
            if any(w in target for w in t_opposites):
                reasons.append({
                    "code": "directional_flip",
                    "label": "Possible logical flip",
                    "severity": "high",
                    "detail": "A directional word (e.g. increase/profit) appears to have been reversed in the translation.",
                })

def _check_currency_integrity(source: str, target: str, reasons: list[dict], target_lang: str = "ne"):
    source_lower = source.lower()
    target_lower = target.lower()
    for s_set, t_set in CURRENCY_PAIRS:
        has_s = any(s in source_lower for s in s_set)
        has_t_localized = any(t in target_lower for t in t_set)
        has_t_latin = any(s in target_lower for s in s_set)
        
        if has_s:
            if not has_t_localized and not has_t_latin:
                s_label = sorted(list(s_set))[0]
                reasons.append({
                    "code": "currency_missing",
                    "label": "CRITICAL: Currency missing",
                    "severity": "high",
                    "detail": f"The currency ({s_label}) present in the source is missing in the translation.",
                })
            elif has_t_latin and not has_t_localized and target_lang.lower() != "en":
                s_label = sorted(list(s_set))[-1] # Usually the code like 'USD' or 'NPR'
                t_label = sorted(list(t_set))[0]
                reasons.append({
                    "code": "currency_unlocalized",
                    "label": "Unlocalized currency marker",
                    "severity": "medium",
                    "detail": f"The currency code '{s_label}' was kept in Latin script. Consider localizing to '{t_label}'.",
                })
            # New Smart Check: Sub-optimal phonetic transliteration (e.g. एनपीआर)
            # Only for non-English targets
            elif target_lang.lower() != "en" and any(sub in target_lower for sub in ["एनपीआर", "रुपैया"]):
                 reasons.append({
                    "code": "currency_suboptimal",
                    "label": "Sub-optimal currency style",
                    "severity": "low",
                    "repairable": True,
                    "detail": f"Phonetic transliteration detected. Using the official symbol '{PREFERRED_CURRENCY_SYMBOLS.get('npr')}' is more professional.",
                })

def _check_list_sequence(source: str, target: str, reasons: list[dict]):
    # Find numbers that look like list markers (e.g. 1., 2.)
    s_markers = [int(n) for n in re.findall(r"\b(\d+)\.\s", source) if int(n) < 100]
    t_markers = [int(digits_to_ascii(n)) for n in re.findall(r"\b([0-9०-९]+)\.\s", target) if int(digits_to_ascii(n)) < 100]
    
    if s_markers and t_markers:
        if s_markers != t_markers:
            reasons.append({
                "code": "list_sequence_broken",
                "label": "List sequence broken",
                "severity": "high",
                "detail": f"List numbering mismatch. Expected sequence: {s_markers}.",
            })

def _check_forbidden_terms(target: str, reasons: list[dict]):
    for pattern, label, severity in FORBIDDEN_TERMS:
        if pattern.search(target):
            reasons.append({
                "code": "forbidden_term",
                "label": label,
                "severity": severity,
                "detail": "This term is considered informal or incorrect for official documents.",
            })

def _check_logical_flow(source: str, target: str, reasons: list[dict]):
    source_lower = source.lower()
    target_text = display_normalize(target)
    for s_set, t_set in LOGICAL_CONNECTIVE_PAIRS:
        has_s = any(re.search(rf"\b{w}\b", source_lower) for w in s_set)
        has_t = any(w in target_text for w in t_set)
        if has_s and not has_t:
            reasons.append({
                "code": "logical_flow_broken",
                "label": "Possible logical flow break",
                "severity": "medium",
                "detail": "A transition word (e.g. However, Therefore) is missing or mismatched, potentially changing the document's logic.",
            })

def _check_identity_swap(source: str, target: str, reasons: list[dict]):
    # Find potential names (Latin tokens not in non-name set)
    names = [w for w in LATIN_TOKEN_RE.findall(source) if w not in NON_NAME_TOKENS]
    if len(set(names)) >= 2:
        # Check if names appear in target
        target_norm = display_normalize(target)
        present_names = [n for n in names if n in target_norm or normalize_text(n) in target_norm]
        if len(present_names) >= 2:
            # Check relative order (simplified but catches most swaps)
            s_order = [n for n in names if n in present_names]
            t_order = []
            for n in present_names:
                t_order.append((target_norm.find(n), n))
            t_order.sort()
            t_sorted_names = [n for _, n in t_order if _ != -1]
            
            if s_order != t_sorted_names and len(s_order) == len(t_sorted_names):
                 reasons.append({
                    "code": "identity_swap",
                    "label": "Critical: Possible identity swap",
                    "severity": "high",
                    "detail": f"The names {s_order} appear in a different order in the translation. Possible role reversal.",
                })

def _check_entity_anchors(source: str, target: str, reasons: list[dict]):
    # Bi-lingual Data Anchors: Ensuring data points stay with their labels across languages
    anchors = [
        ({"ward"}, {"वडा"}),
        ({"house"}, {"घर"}),
        ({"no", "number"}, {"नं", "नम्बर", "संख्या"}),
    ]
    source_lower = source.lower()
    target_text = display_normalize(target)
    
    for s_set, t_set in anchors:
        s_vals = set()
        for s_anchor in s_set:
            s_vals.update(digits_to_ascii(m) for m in re.findall(rf"\b{s_anchor}\.?\s*([0-9०-९]+)", source_lower))
        
        t_vals = set()
        for t_anchor in t_set:
            t_vals.update(digits_to_ascii(m) for m in re.findall(rf"\b{t_anchor}\.?\s*([0-9०-९]+)", target_text))
            
        if s_vals and t_vals:
            if s_vals != t_vals:
                s_label = sorted(list(s_set))[0]
                t_label = sorted(list(t_set))[0]
                reasons.append({
                    "code": "anchor_mismatch",
                    "label": "Data anchor mismatch",
                    "severity": "high",
                    "detail": f"The value for {s_label}/{t_label} does not match between source and target.",
                })

def _check_professional_landmarks(source: str, target: str, reasons: list[dict]):
    # Locking formal document markers like [STAMP], [SIGNATURE]
    source_lower = source.lower()
    target_text = display_normalize(target)
    for s_set, t_set in DOCUMENT_LANDMARKS:
        # Check if source has a bracketed or formal landmark
        has_s_landmark = any(f"[{s}]" in source_lower or f"({s})" in source_lower for s in s_set)
        has_t_landmark = any(f"[{t}]" in target_text or f"({t})" in target_text or t in target_text for t in t_set)
        
        if has_s_landmark and not has_t_landmark:
            s_label = sorted(list(s_set))[0]
            reasons.append({
                "code": "missing_landmark",
                "label": "Missing professional landmark",
                "severity": "high",
                "detail": f"An official marker (e.g. [{s_label}]) is missing in the translation.",
            })

def _check_certification_markers(source: str, target: str, reasons: list[dict]):
    # Specifically for 'Verified' / 'Ruju Pramanit'
    if "verified" in source.lower() or "certified" in source.lower():
        if "प्रमाणित" not in target:
             reasons.append({
                "code": "certification_missing",
                "label": "Certification status missing",
                "severity": "high",
                "detail": "The 'Verified/Certified' status of the document has been omitted.",
            })

def _check_date_hallucination(source: str, target: str, reasons: list[dict]):
    # AI often tries to convert AD years (2024) to BS years (2081) and fails by 1-2 days
    s_years = re.findall(r"\b(20[0-2][0-9])\b", source)
    t_text = digits_to_ascii(target)
    t_years = re.findall(r"\b(20[7-9][0-9])\b", t_text)
    
    if s_years and t_years:
        # If the target has a '208x' year but source has '202x', it's a conversion attempt
        reasons.append({
            "code": "date_conversion_risk",
            "label": "Date conversion hallucination",
            "severity": "high",
            "detail": "AI converted an AD date to BS. This math is often incorrect by 1-2 days. Please verify with an official calendar.",
        })

def _check_anachronisms(source: str, target: str, reasons: list[dict]):
    # Checking for obsolete administrative terms (VDC, Zonal)
    s_lower = source.lower()
    for s_set, suggestion_set in ANACHRONISM_MAP:
        if any(w in s_lower for w in s_set):
            s_label = sorted(list(s_set))[0]
            suggestion_label = sorted(list(suggestion_set))[0]
            reasons.append({
                "code": "anachronism_risk",
                "label": "Obsolete administrative term",
                "severity": "medium",
                "detail": f"This document uses an outdated term (e.g. {s_label}). Consider using modern Federal terms like {suggestion_label}.",
            })

def _check_transliteration_drift(source: str, target: str, reasons: list[dict]):
    # Intra-segment consistency: Same Latin name should ideally have same Devanagari form
    latin_tokens = [w for w in LATIN_TOKEN_RE.findall(source) if w not in NON_NAME_TOKENS]
    if not latin_tokens:
        return
        
    for token in set(latin_tokens):
        if source.count(token) >= 2:
            # Find all Devanagari segments that correspond to this Latin token
            # We look for words that match the normalized Latin token or appear near it
            target_matches = [w for w in re.findall(r"[\u0900-\u097F]+", target) if len(w) > 2]
            # If we find 2+ different variations and no single dominant one
            if len(set(target_matches)) >= 2:
                reasons.append({
                    "code": "transliteration_drift",
                    "label": "Inconsistent transliteration",
                    "severity": "low",
                    "detail": f"The entity '{token}' is translated with multiple variations in the same segment.",
                })
                break

def _check_legal_modals(source: str, target: str, reasons: list[dict]):
    # Legal Obligations: 'Must' (Mandatory) vs 'May' (Permissive)
    s_lower = source.lower()
    t_text = display_normalize(target)
    for i, (s_set, t_set) in enumerate(LEGAL_MODAL_PAIRS):
        has_s = any(re.search(rf"\b{w}\b", s_lower) for w in s_set)
        has_t = any(w in t_text for w in t_set)
        
        # Check for Modal Flip: Source has Mandatory, Target has Permissive (or vice versa)
        other_index = 1 - i
        other_t_set = LEGAL_MODAL_PAIRS[other_index][1]
        has_other_t = any(w in t_text for w in other_t_set)
        
        if has_s and has_other_t and not has_t:
            reasons.append({
                "code": "legal_modal_flip",
                "label": "CRITICAL: Legal obligation flip",
                "severity": "high",
                "detail": "A mandatory requirement (Must/Shall) appears to have been changed to a permissive one (May), or vice versa.",
            })

def _check_legalisms(target: str, reasons: list[dict]):
    # Common Latin/English legalisms that should be translated
    legalisms = ["subpoena", "indemnity", "habeas corpus", "tort", "affidavit"]
    target_lower = target.lower()
    for term in legalisms:
        if re.search(rf"\b{term}\b", target_lower):
             reasons.append({
                "code": "untranslated_legalism",
                "label": "Untranslated legal term",
                "severity": "medium",
                "detail": f"The legal term '{term}' was left in English script. Please provide a Nepali equivalent.",
            })

def _check_legal_anchors(source: str, target: str, reasons: list[dict]):
    # Complex clause markers: 'Provided that', 'Notwithstanding'
    s_lower = source.lower()
    t_text = display_normalize(target)
    for s_set, t_set in LEGAL_ANCHOR_PAIRS:
        has_s = any(w in s_lower for w in s_set)
        has_t = any(w in t_text for w in t_set)
        if has_s and not has_t:
             reasons.append({
                "code": "legal_anchor_missing",
                "label": "Legal condition anchor missing",
                "severity": "medium",
                "detail": "A critical legal condition (e.g. 'Provided that') is missing or mistranslated.",
            })

def _check_ghost_entities(source: str, target: str, reasons: list[dict], target_lang: str = "en"):
    # Hallucination Guard: Flags Latin tokens in target that aren't in source
    s_tokens = set(LATIN_TOKEN_RE.findall(source.lower()))
    t_tokens = set(LATIN_TOKEN_RE.findall(target.lower()))
    
    # Script-Aware Lenience:
    # If translating to English, many words like 'Phone', 'Reference', 'Office'
    # will appear in the target as Latin tokens but were Devanagari in the source.
    # We only flag if they are NOT in a common set of institutional words AND are long.
    ghosts = t_tokens - s_tokens - INSTRUCTION_KEYWORDS
    
    if target_lang.lower() == "en" and contains_devanagari(source):
        # Filter out common institutional terms that are definitely not hallucinations
        filtered_ghosts = set()
        for g in ghosts:
            if len(g) < 4: continue # Too short to be a meaningful hallucination
            if g.capitalize() in INSTITUTIONAL_WHITELIST: continue
            filtered_ghosts.add(g)
        ghosts = filtered_ghosts

    if ghosts:
        ghost_list = sorted(list(ghosts))
        reasons.append({
            "code": "ghost_entity",
            "label": "CRITICAL: Hallucinated entity",
            "severity": "high",
            "detail": f"The translation contains words ({', '.join(ghost_list[:2])}) not present in the source. Possible AI hallucination.",
        })

def _check_polarity(source: str, target: str, reasons: list[dict]):
    # Polarity Auditor: Detects if the sentence shifted from Positive to Negative
    # accounts for morphological negatives (un-, in-, im-, dis-)
    neg_prefixes = (
        "un", "in", "im", "dis", "non", "ir", "mis", "anti", "de"
    )
    # Whitelist of words that start with prefixes but aren't negative
    NEGATION_WHITELIST = {
        "instruction", "information", "important", "interest", "industry",
        "individual", "increase", "include", "indeed", "inside", "insight",
        "inspect", "install", "instead", "intend", "intensity", "interview",
        "instrument", "instance", "incident", "input", "income", "invite"
    }
    
    def count_negatives(text, negation_set, is_english=False):
        words = text.lower().split()
        count = sum(1 for w in words if w in negation_set)
        if is_english:
            # Heuristic: words like 'unhappy', 'impossible'
            for w in words:
                if w in NEGATION_WHITELIST:
                    continue
                if any(w.startswith(p) for p in neg_prefixes) and len(w) > 4 and w not in negation_set:
                    count += 1
        return count

    s_neg_count = count_negatives(source, ENGLISH_NEGATION, is_english=True)
    t_neg_count = count_negatives(target, NEPALI_NEGATION)
    
    # Parity check: (Negative + Negative = Positive)
    if (s_neg_count % 2) != (t_neg_count % 2):
        # Allow 0 source negatives to match 0 target negatives (Normal case)
        if s_neg_count > 0 or t_neg_count > 0:
            reasons.append({
                "code": "polarity_flip",
                "label": "CRITICAL: Meaning inversion",
                "severity": "high",
                "detail": "The sentence logic (Positive/Negative) has been flipped. Double-check for missing or extra negation.",
            })

def _check_professional_spacing(target: str, reasons: list[dict]):
    # Spacing standards: Symbol should have a space before the number (e.g. रु ५००)
    # This flags the lack of space (e.g. रु५००)
    if re.search(r"[रु\$][०-९0-9]", target):
        reasons.append({
            "code": "spacing_standard",
            "label": "Sub-optimal typography",
            "severity": "low",
            "detail": "Adding a space between the currency symbol and the number (e.g. 'रु ५००') is more professional.",
        })

def _check_official_abbreviations(target: str, reasons: list[dict]):
    # Official standard for Number is 'नं.' (with dot)
    if re.search(r"\bन\s*[०-९0-9]", target):
        reasons.append({
            "code": "abbreviation_standard",
            "label": "Non-standard abbreviation",
            "severity": "low",
            "detail": "Use the official abbreviation 'नं.' (with a dot) for professional documents.",
        })

def _sanitize_unicode(text: str) -> str:
    import unicodedata
    # Normalize and strip control characters (except newline/tab)
    normalized = unicodedata.normalize('NFKC', text)
    return "".join(c for c in normalized if unicodedata.category(c)[0] != 'C' or c in '\n\r\t')
