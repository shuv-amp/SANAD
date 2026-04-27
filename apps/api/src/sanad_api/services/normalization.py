import re
import unicodedata


WHITESPACE_RE = re.compile(r"\s+")
ASCII_TO_DEVANAGARI_DIGITS = str.maketrans("0123456789", "०१२३४५६७८९")
DEVANAGARI_TO_ASCII_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")


def normalize_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text or "")
    normalized = WHITESPACE_RE.sub(" ", normalized).strip()
    return normalized.casefold()


def display_normalize(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text or "")
    return WHITESPACE_RE.sub(" ", normalized).strip()


def contains_devanagari(text: str) -> bool:
    return any("\u0900" <= ch <= "\u097F" for ch in text)


def to_devanagari_digits(text: str) -> str:
    return (text or "").translate(ASCII_TO_DEVANAGARI_DIGITS)


def digits_to_ascii(text: str) -> str:
    return (text or "").translate(DEVANAGARI_TO_ASCII_DIGITS)
