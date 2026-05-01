import re

from sanad_api.services.normalization import digits_to_ascii, normalize_text, to_devanagari_digits


DEMO_TEXT_BANK: dict[str, dict[str, str]] = {
    "title": {
        "en": "Certificate of Residence Request",
        "ne": "बसोबास प्रमाणपत्र अनुरोध",
        "tmg": "चिबा ह्रिबाला प्रमाणस्यो",
    },
    "submit_form": {
        "en": "Please submit this form to the Ward Office.",
        "ne": "कृपया यो फारम वडा कार्यालयमा बुझाउनुहोस्।",
        "tmg": "चु फाराम वडा गेदिमरि पेस लास्ह्युगो।",
    },
    "review_within_days": {
        "en": "The Municipality will review the application within 7 days.",
        "ne": "नगरपालिकाले आवेदन ७ दिनभित्र समीक्षा गर्नेछ।",
        "tmg": "नगरपालिकासे ७ रे न्हाङरि स्ह्युसेनला समीक्षा लासेला मुला।",
    },
    "ward_verify": {
        "en": "Ward No. 4 will verify the address.",
        "ne": "वडा नं. ४ ले ठेगाना प्रमाणित गर्नेछ।",
        "tmg": "वडा नं. ४ से ठेगाना प्रमाणित लासेला मुला।",
    },
    "visit_updates": {
        "en": "Visit https://municipality.example.gov for updates.",
        "ne": "अपडेटका लागि https://municipality.example.gov हेर्नुहोस्।",
        "tmg": "अद्यावधिकला लागिरि https://municipality.example.gov निगो।",
    },
    "applicant_name": {
        "en": "Applicant Name",
        "ne": "निवेदकको नाम",
        "tmg": "स्ह्युसेन पिन्बा मिन",
    },
    "phone": {
        "en": "Phone",
        "ne": "फोन",
        "tmg": "फोन लाबा",
    },
    "date": {
        "en": "Date",
        "ne": "मिति",
        "tmg": "कुनु",
    },
    "reference_id": {
        "en": "Reference ID",
        "ne": "सन्दर्भ आईडी",
        "tmg": "सन्दर्भ ङोसेबास्यो",
    },
    "fee_500": {
        "en": "Fee: NPR 500",
        "ne": "शुल्क: NPR ५००",
        "tmg": "शुल्क: NPR ५००",
    },
}

SUPPORTED_DEMO_LANGUAGES = ("en", "ne", "tmg")
TABLE_ROW_KEYS = ("applicant_name", "phone", "date", "reference_id")
PARAGRAPH_KEYS = ("submit_form", "review_within_days", "ward_verify", "visit_updates")
_TEXT_TO_KEY = {
    (language, normalize_text(text)): key
    for key, translations in DEMO_TEXT_BANK.items()
    for language, text in translations.items()
}
_DATE_RE = re.compile(r"^[0-9०-९]{4}[-/][0-9०-९]{2}[-/][0-9०-९]{2}$")
_MONEY_RE = re.compile(r"^(?:NPR|Rs\.?|रु\.?|\$)\s?[0-9०-९][0-9०-९,]*(?:\.[0-9]+)?$", re.IGNORECASE)
_PHONE_RE = re.compile(r"^\+?[0-9०-९][0-9०-९\-\s]{7,}$")
_REFERENCE_RE = re.compile(r"^[A-Z]{2,}(?:-[A-Z0-9]{2,})+$")


def demo_text(key: str, language: str) -> str:
    return DEMO_TEXT_BANK[key][language]


def translate_demo_text(source_lang: str, target_lang: str, text: str) -> str | None:
    key = _TEXT_TO_KEY.get((source_lang, normalize_text(text)))
    if key:
        return demo_text(key, target_lang)

    normalized = text.strip()
    if _DATE_RE.fullmatch(normalized):
        return format_date_value(normalized, target_lang)
    if _MONEY_RE.fullmatch(normalized):
        return format_money_value(normalized, target_lang)
    if _PHONE_RE.fullmatch(normalized):
        return format_phone_value(normalized, target_lang)
    if _REFERENCE_RE.fullmatch(digits_to_ascii(normalized)):
        return digits_to_ascii(normalized)
    return None


def format_date_value(value: str, language: str) -> str:
    ascii_value = digits_to_ascii(value)
    return ascii_value if language == "en" else to_devanagari_digits(ascii_value)


def format_phone_value(value: str, language: str) -> str:
    ascii_value = digits_to_ascii(value)
    return ascii_value if language == "en" else to_devanagari_digits(ascii_value)


def format_money_value(value: str, language: str) -> str:
    ascii_value = digits_to_ascii(value)
    if language == "en":
        return ascii_value
    return to_devanagari_digits(ascii_value)
