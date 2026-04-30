from sanad_api.services.risk import count_preserved_protected_entities, is_protected_entity_preserved, score_translation


def test_risk_flags_changed_protected_entities_and_glossary_miss() -> None:
    score, reasons = score_translation(
        source_text="Please submit to the Ward Office by 2026-04-21.",
        translated_text="कृपया कार्यालयमा बुझाउनुहोस्।",
        protected_entities=[
            {"kind": "date", "text": "2026-04-21"},
            {"kind": "office", "text": "Ward Office", "target_term": "वडा कार्यालय"},
        ],
        glossary_hits=[{"source_term": "Ward Office", "target_term": "वडा कार्यालय", "term_type": "office"}],
    )

    codes = {reason["code"] for reason in reasons}
    assert score > 0
    assert "changed_protected_entity" in codes
    assert "glossary_miss" in codes


def test_risk_accepts_localized_digits_and_public_service_entity_forms() -> None:
    score, reasons = score_translation(
        source_text="Ward No. 4 fee NPR 500 on 2026-04-22.",
        translated_text="वडा नं. ४ को शुल्क रु ५०० मिति २०२६-०४-२२।",
        protected_entities=[
            {"kind": "ward", "text": "Ward No. 4"},
            {"kind": "money", "text": "NPR 500"},
            {"kind": "date", "text": "2026-04-22"},
        ],
        glossary_hits=[],
    )

    codes = {reason["code"] for reason in reasons}
    assert score == 0
    assert "changed_number" not in codes
    assert "changed_protected_entity" not in codes


def test_risk_does_not_flag_preserved_urls_ids_or_names_as_untranslated() -> None:
    examples = [
        (
            "Visit https://municipality.example.gov for updates.",
            "अपडेटका लागि https://municipality.example.gov हेर्नुहोस्।",
            [{"kind": "url", "text": "https://municipality.example.gov", "start": 6, "end": 38}],
        ),
        (
            "RES-2026-004",
            "RES-2026-004",
            [{"kind": "id", "text": "RES-2026-004", "start": 0, "end": 12}],
        ),
        (
            "Maya Lama",
            "Maya Lama",
            [],
        ),
    ]

    for source_text, translated_text, protected_entities in examples:
        score, reasons = score_translation(
            source_text=source_text,
            translated_text=translated_text,
            protected_entities=protected_entities,
            glossary_hits=[],
        )

        codes = {reason["code"] for reason in reasons}
        assert "untranslated_token" not in codes
        assert score == 0


def test_protected_entity_preservation_helpers_match_localized_values() -> None:
    translated_text = "वडा नं. ४ को शुल्क रु ५०० मिति २०२६-०४-२२।"
    protected_entities = [
        {"kind": "ward", "text": "Ward No. 4"},
        {"kind": "money", "text": "NPR 500"},
        {"kind": "date", "text": "2026-04-22"},
        {"kind": "number", "text": "500"},
    ]

    preserved, total = count_preserved_protected_entities(protected_entities, translated_text)

    assert total == 4
    assert preserved == 4
    assert is_protected_entity_preserved({"kind": "number", "text": "500"}, translated_text) is True
