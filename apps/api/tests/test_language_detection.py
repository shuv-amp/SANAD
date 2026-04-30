from sanad_api.services.language_detection import detect_source_language_from_text


def test_detects_english_from_latin_text() -> None:
    result = detect_source_language_from_text(
        "Certificate of Residence Request Please submit this form to the Ward Office."
    )

    assert result.source_lang == "en"
    assert result.confidence in {"high", "medium"}


def test_detects_nepali_from_devanagari_public_service_text() -> None:
    result = detect_source_language_from_text(
        "बसोबास प्रमाणपत्र अनुरोध कृपया यो फारम वडा कार्यालयमा बुझाउनुहोस्।"
    )

    assert result.source_lang == "ne"
    assert result.confidence in {"high", "medium"}


def test_detects_tamang_from_devanagari_tamang_text() -> None:
    result = detect_source_language_from_text(
        "चिबा ह्रिबाला प्रमाणस्यो चु फाराम वडा गेदिमरि पेस लास्ह्युगो।"
    )

    assert result.source_lang == "tmg"
    assert result.confidence in {"high", "medium"}


def test_shared_public_service_words_do_not_force_nepali_or_tamang_guess() -> None:
    result = detect_source_language_from_text("वडा फोन शुल्क सन्दर्भ NPR ५००")

    assert result.source_lang is None
    assert result.confidence == "low"
