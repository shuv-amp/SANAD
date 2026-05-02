import asyncio
import json
import os

import httpx
import pytest

from sanad_api.services.providers import (
    FixtureTranslationProvider,
    MockTranslationProvider,
    ProviderConfigurationError,
    ProviderContractError,
    LegacyTmtApiProvider,
    TranslationBatchRequest,
    TranslationResult,
    TranslationSegmentRequest,
    validate_provider_results,
)


def _request() -> TranslationBatchRequest:
    return TranslationBatchRequest(
        source_lang="en",
        target_lang="ne",
        domain="public_service",
        subdomain="residence",
        segments=[
            TranslationSegmentRequest(
                segment_id="s1",
                source_text="Please submit this form to the Ward Office.",
                protected_entities=[],
                glossary_hits=[],
            ),
            TranslationSegmentRequest(
                segment_id="s2",
                source_text="Phone",
                protected_entities=[],
                glossary_hits=[],
            ),
        ],
    )


def test_fixture_provider_satisfies_translation_contract() -> None:
    request = _request()
    results = asyncio.run(FixtureTranslationProvider().translate_batch(request))

    validate_provider_results(request, results)
    assert [result.segment_id for result in results] == ["s1", "s2"]
    assert all(result.translated_text for result in results)


def test_fixture_provider_uses_polished_nepali_for_demo_phrases() -> None:
    provider = FixtureTranslationProvider()
    request = TranslationBatchRequest(
        source_lang="en",
        target_lang="ne",
        domain="public_service",
        subdomain="residence",
        segments=[
            TranslationSegmentRequest(
                segment_id="days",
                source_text="The Municipality will review the application within 7 days.",
                protected_entities=[],
                glossary_hits=[],
            ),
            TranslationSegmentRequest(
                segment_id="ward",
                source_text="Ward No. 4 will verify the address.",
                protected_entities=[],
                glossary_hits=[],
            ),
            TranslationSegmentRequest(
                segment_id="fee",
                source_text="Fee: NPR 500",
                protected_entities=[],
                glossary_hits=[],
            ),
            TranslationSegmentRequest(
                segment_id="date",
                source_text="2026-04-22",
                protected_entities=[],
                glossary_hits=[],
            ),
        ],
    )

    results = asyncio.run(provider.translate_batch(request))
    by_id = {result.segment_id: result.translated_text for result in results}

    assert by_id["days"] == "नगरपालिकाले आवेदन ७ दिनभित्र समीक्षा गर्नेछ।"
    assert by_id["ward"] == "वडा नं. ४ ले ठेगाना प्रमाणित गर्नेछ।"
    assert by_id["fee"] == "शुल्क: NPR ५००"
    assert by_id["date"] == "२०२६-०४-२२"


def test_fixture_provider_supports_all_three_languages_for_demo_phrases() -> None:
    provider = FixtureTranslationProvider()
    request = TranslationBatchRequest(
        source_lang="ne",
        target_lang="en",
        domain="public_service",
        subdomain="residence",
        segments=[
            TranslationSegmentRequest(
                segment_id="title",
                source_text="बसोबास प्रमाणपत्र अनुरोध",
                protected_entities=[],
                glossary_hits=[],
            ),
            TranslationSegmentRequest(
                segment_id="fee",
                source_text="शुल्क: NPR ५००",
                protected_entities=[],
                glossary_hits=[],
            ),
        ],
    )
    results = asyncio.run(provider.translate_batch(request))
    by_id = {result.segment_id: result.translated_text for result in results}
    assert by_id["title"] == "Certificate of Residence Request"
    assert by_id["fee"] == "Fee: NPR 500"

    tam_request = TranslationBatchRequest(
        source_lang="tmg",
        target_lang="ne",
        domain="public_service",
        subdomain="residence",
        segments=[
            TranslationSegmentRequest(
                segment_id="title",
                source_text="चिबा ह्रिबाला प्रमाणस्यो",
                protected_entities=[],
                glossary_hits=[],
            ),
            TranslationSegmentRequest(
                segment_id="submit",
                source_text="चु फाराम वडा गेदिमरि पेस लास्ह्युगो।",
                protected_entities=[],
                glossary_hits=[],
            ),
        ],
    )
    tam_results = asyncio.run(provider.translate_batch(tam_request))
    tam_by_id = {result.segment_id: result.translated_text for result in tam_results}
    assert tam_by_id["title"] == "बसोबास प्रमाणपत्र अनुरोध"
    assert tam_by_id["submit"] == "कृपया यो फारम वडा कार्यालयमा बुझाउनुहोस्।"


def test_mock_provider_satisfies_translation_contract() -> None:
    request = _request()
    results = asyncio.run(MockTranslationProvider().translate_batch(request))

    validate_provider_results(request, results)
    assert [result.segment_id for result in results] == ["s1", "s2"]


def test_provider_contract_rejects_missing_segment_results() -> None:
    request = _request()

    with pytest.raises(ProviderContractError):
        validate_provider_results(request, [TranslationResult(segment_id="s1", translated_text="ठीक")])


def test_tmt_provider_requires_endpoint_config() -> None:
    request = _request()
    provider = LegacyTmtApiProvider(endpoint=None, api_key=None)

    with pytest.raises(ProviderConfigurationError, match="SANAD_TMT_API_ENDPOINT"):
        asyncio.run(provider.translate_batch(request))


def test_tmt_provider_maps_language_aliases_and_parses_translation() -> None:
    seen_payloads: list[dict] = []
    request = _request()

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        seen_payloads.append(payload)
        assert request.url.path.endswith("/translate")
        return httpx.Response(200, json={"NLLB200": f"translated:{payload['text']}"})

    provider = LegacyTmtApiProvider(
        endpoint="https://tmt.ilprl.ku.edu.np",
        auth_method="none",
        transport=httpx.MockTransport(handler),
    )

    results = asyncio.run(provider.translate_batch(request))

    assert len(results) == 2
    assert [result.segment_id for result in results] == ["s1", "s2"]
    assert all(result.translated_text.startswith("translated:") for result in results)
    assert seen_payloads[0]["src_lang"] == "English"
    assert seen_payloads[0]["tgt_lang"] == "Nepali"


def test_tmt_provider_accepts_ui_tamang_alias_and_clamps_batch_size() -> None:
    seen_payloads: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        seen_payloads.append(payload)
        return httpx.Response(200, json={"NLLB200": "translated"})

    provider = LegacyTmtApiProvider(
        endpoint="https://tmt.ilprl.ku.edu.np",
        batch_size=0,
        transport=httpx.MockTransport(handler),
    )

    request = TranslationBatchRequest(
        source_lang="tmg",
        target_lang="en",
        domain="public_service",
        subdomain="residence",
        segments=[
            TranslationSegmentRequest(
                segment_id="only-segment",
                source_text="नमस्ते",
                protected_entities=[],
                glossary_hits=[],
            )
        ],
    )
    results = asyncio.run(provider.translate_batch(request))

    assert results[0].translated_text == "translated"
    assert seen_payloads == [{"src_lang": "Tamang", "tgt_lang": "English", "text": "नमस्ते"}]


def test_tmt_provider_recovers_failed_tail_segment_on_second_pass() -> None:
    attempts_by_text: dict[str, int] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        text = payload["text"]
        attempts_by_text[text] = attempts_by_text.get(text, 0) + 1
        if text == "Tail line" and attempts_by_text[text] == 1:
            return httpx.Response(503, json={"error": "temporary overload"})
        return httpx.Response(200, json={"NLLB200": f"translated:{text}"})

    provider = LegacyTmtApiProvider(
        endpoint="https://tmt.ilprl.ku.edu.np",
        transport=httpx.MockTransport(handler),
        retry_attempts=1,
        batch_size=2,
        rate_limit_delay=0,
    )

    request = TranslationBatchRequest(
        source_lang="en",
        target_lang="ne",
        domain="public_service",
        subdomain="residence",
        segments=[
            TranslationSegmentRequest(
                segment_id="head",
                source_text="Head line",
                protected_entities=[],
                glossary_hits=[],
            ),
            TranslationSegmentRequest(
                segment_id="tail",
                source_text="Tail line",
                protected_entities=[],
                glossary_hits=[],
            ),
        ],
    )

    results = asyncio.run(provider.translate_batch(request))

    assert [result.translated_text for result in results] == [
        "translated:Head line",
        "translated:Tail line",
    ]
    assert attempts_by_text["Tail line"] == 2


def test_tmt_provider_accepts_full_translate_url_without_double_append() -> None:
    seen_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_paths.append(request.url.path)
        return httpx.Response(200, json={"NLLB200": "ok"})

    provider = LegacyTmtApiProvider(
        endpoint="https://tmt.ilprl.ku.edu.np/translate?ignored=true",
        transport=httpx.MockTransport(handler),
    )

    results = asyncio.run(provider.translate_batch(_request()))

    assert len(results) == 2
    assert seen_paths == ["/translate", "/translate"]


def test_tmt_provider_sets_bearer_authorization_header() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer test-secret"
        return httpx.Response(200, json={"NLLB200": "ok"})

    provider = LegacyTmtApiProvider(
        endpoint="https://tmt.ilprl.ku.edu.np/translate",
        auth_method="bearer",
        api_key="test-secret",
        transport=httpx.MockTransport(handler),
    )

    results = asyncio.run(provider.translate_batch(_request()))
    assert len(results) == 2


def test_tmt_provider_retries_retryable_status_codes() -> None:
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        if attempts["count"] == 1:
            return httpx.Response(503, json={"error": "busy"})
        return httpx.Response(200, json={"NLLB200": "translated"})

    provider = LegacyTmtApiProvider(
        endpoint="https://tmt.ilprl.ku.edu.np",
        transport=httpx.MockTransport(handler),
        retry_attempts=2,
    )

    results = asyncio.run(
        provider.translate_batch(
            TranslationBatchRequest(
                source_lang="English",
                target_lang="Nepali",
                domain="public_service",
                subdomain="residence",
                segments=[
                    TranslationSegmentRequest(
                        segment_id="only-segment",
                        source_text="Please submit this form to the Ward Office.",
                        protected_entities=[],
                        glossary_hits=[],
                    )
                ],
            )
        )
    )

    assert attempts["count"] == 2
    assert results[0].translated_text == "translated"


def test_tmt_provider_rejects_response_without_translation_text() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"NLLB200": "   "})

    provider = LegacyTmtApiProvider(
        endpoint="https://tmt.ilprl.ku.edu.np",
        transport=httpx.MockTransport(handler),
    )

    results = asyncio.run(provider.translate_batch(_request()))
    assert "did not include translated text" in results[0].error


@pytest.mark.skipif(
    os.getenv("SANAD_RUN_LIVE_TMT_TESTS") != "1",
    reason="Set SANAD_RUN_LIVE_TMT_TESTS=1 to run the network-dependent public TMT smoke test.",
)
def test_live_tmt_public_site_contract_when_enabled() -> None:
    endpoint = os.getenv("SANAD_TMT_API_ENDPOINT") or "https://tmt.ilprl.ku.edu.np"
    request = TranslationBatchRequest(
        source_lang="Nepali",
        target_lang="English",
        domain="public_service",
        subdomain="residence",
        segments=[
            TranslationSegmentRequest(
                segment_id="live-smoke",
                source_text="तिमीले मासु खायौ?",
                protected_entities=[],
                glossary_hits=[],
            )
        ],
    )
    provider = LegacyTmtApiProvider(endpoint=endpoint, auth_method="none", retry_attempts=1)

    results = asyncio.run(provider.translate_batch(request))

    validate_provider_results(request, results)
    assert results[0].translated_text != request.segments[0].source_text


# ---------------------------------------------------------------------------
# Official TMT API Provider Tests
# ---------------------------------------------------------------------------


def test_official_provider_sends_correct_payload_and_parses_success() -> None:
    from sanad_api.services.providers import OfficialTmtApiProvider

    seen_payloads: list[dict] = []
    seen_headers: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        seen_payloads.append(payload)
        seen_headers.append(dict(request.headers))
        assert request.url.path.endswith("/lang-translate")
        return httpx.Response(200, json={
            "message_type": "SUCCESS",
            "message": "Translation successful",
            "src_lang": "English",
            "input": payload["text"],
            "target_lang": "Nepali",
            "output": f"translated:{payload['text']}",
            "timestamp": "2026-04-25T10:32:00Z",
        })

    provider = OfficialTmtApiProvider(
        endpoint="https://tmt.ilprl.ku.edu.np/lang-translate",
        api_key="team_test_token_123",
        transport=httpx.MockTransport(handler),
        rate_limit_delay=0,
    )

    results = asyncio.run(provider.translate_batch(_request()))

    assert len(results) == 2
    assert results[0].translated_text.startswith("translated:")
    assert results[0].provider_tier == "tmt_official"
    # Verify canonical language names are sent (verified working on real API 2026-04-26)
    assert seen_payloads[0]["src_lang"] == "English"
    assert seen_payloads[0]["tgt_lang"] == "Nepali"
    # Verify Bearer auth header
    assert "Bearer team_test_token_123" in seen_headers[0]["authorization"]


def test_official_provider_handles_fail_response() -> None:
    from sanad_api.services.providers import OfficialTmtApiProvider

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "message_type": "FAIL",
            "message": "src_lang and tgt_lang must be different",
        })

    provider = OfficialTmtApiProvider(
        endpoint="https://tmt.ilprl.ku.edu.np/lang-translate",
        api_key="team_test",
        transport=httpx.MockTransport(handler),
        rate_limit_delay=0,
    )

    results = asyncio.run(provider.translate_batch(_request()))
    assert "translation failed" in results[0].error.lower()


def test_official_provider_requires_api_key() -> None:
    from sanad_api.services.providers import OfficialTmtApiProvider

    provider = OfficialTmtApiProvider(
        endpoint="https://tmt.ilprl.ku.edu.np/lang-translate",
        api_key=None,
    )

    with pytest.raises(ProviderConfigurationError, match="SANAD_TMT_API_KEY"):
        asyncio.run(provider.translate_batch(_request()))


def test_official_provider_resolves_base_url_to_lang_translate() -> None:
    from sanad_api.services.providers import OfficialTmtApiProvider

    seen_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_paths.append(request.url.path)
        return httpx.Response(200, json={
            "message_type": "SUCCESS", "output": "ok",
        })

    provider = OfficialTmtApiProvider(
        endpoint="https://tmt.ilprl.ku.edu.np",
        api_key="team_test",
        transport=httpx.MockTransport(handler),
        rate_limit_delay=0,
    )

    asyncio.run(provider.translate_batch(_request()))
    assert seen_paths[0] == "/lang-translate"


def test_official_provider_retries_on_server_error() -> None:
    from sanad_api.services.providers import OfficialTmtApiProvider

    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        if attempts["count"] == 1:
            return httpx.Response(503, json={"error": "overloaded"})
        return httpx.Response(200, json={
            "message_type": "SUCCESS", "output": "translated",
        })

    provider = OfficialTmtApiProvider(
        endpoint="https://tmt.ilprl.ku.edu.np/lang-translate",
        api_key="team_test",
        transport=httpx.MockTransport(handler),
        retry_attempts=2,
        rate_limit_delay=0,
    )

    request = TranslationBatchRequest(
        source_lang="en", target_lang="ne", domain="test", subdomain="test",
        segments=[TranslationSegmentRequest(
            segment_id="s1", source_text="Hello", protected_entities=[], glossary_hits=[],
        )],
    )

    results = asyncio.run(provider.translate_batch(request))
    assert attempts["count"] == 2
    assert results[0].translated_text == "translated"


# ---------------------------------------------------------------------------
# Smart Fallback Cascade Tests
# ---------------------------------------------------------------------------


def test_smart_provider_uses_official_when_available() -> None:
    from sanad_api.services.providers import OfficialTmtApiProvider, SmartTmtProvider

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "message_type": "SUCCESS", "output": "official_result",
        })

    official = OfficialTmtApiProvider(
        endpoint="https://tmt.ilprl.ku.edu.np/lang-translate",
        api_key="team_test",
        transport=httpx.MockTransport(handler),
        rate_limit_delay=0,
    )

    smart = SmartTmtProvider(official=official, legacy=None, enable_fallback=True)
    results = asyncio.run(smart.translate_batch(_request()))

    assert results[0].translated_text == "official_result"
    assert results[0].provider_tier == "tmt_official"
    assert smart.last_provider_used == "tmt_official"
    assert smart.last_fallback_reason is None


def test_smart_provider_falls_back_to_legacy_on_official_failure() -> None:
    from sanad_api.services.providers import LegacyTmtApiProvider, OfficialTmtApiProvider, SmartTmtProvider

    call_count = {"official": 0, "legacy": 0}

    def official_handler(request: httpx.Request) -> httpx.Response:
        call_count["official"] += 1
        return httpx.Response(500, json={"error": "down"})

    def legacy_handler(request: httpx.Request) -> httpx.Response:
        call_count["legacy"] += 1
        return httpx.Response(200, json={"NLLB200": "legacy_result"})

    official = OfficialTmtApiProvider(
        endpoint="https://tmt.ilprl.ku.edu.np/lang-translate",
        api_key="team_test",
        transport=httpx.MockTransport(official_handler),
        retry_attempts=1,
        rate_limit_delay=0,
    )
    legacy = LegacyTmtApiProvider(
        endpoint="https://tmt.ilprl.ku.edu.np",
        transport=httpx.MockTransport(legacy_handler),
        retry_attempts=1,
    )

    smart = SmartTmtProvider(official=official, legacy=legacy, enable_fallback=True)
    results = asyncio.run(smart.translate_batch(_request()))

    assert results[0].translated_text == "legacy_result"
    assert results[0].provider_tier == "tmt_legacy"
    assert smart.last_provider_used == "tmt_legacy"
    assert "cascaded to legacy" in smart.last_fallback_reason.lower()


def test_smart_provider_falls_back_to_fixture_when_all_apis_fail() -> None:
    from sanad_api.services.providers import LegacyTmtApiProvider, OfficialTmtApiProvider, SmartTmtProvider

    def fail_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "down"})

    official = OfficialTmtApiProvider(
        endpoint="https://tmt.ilprl.ku.edu.np/lang-translate",
        api_key="team_test",
        transport=httpx.MockTransport(fail_handler),
        retry_attempts=1,
        rate_limit_delay=0,
    )
    legacy = LegacyTmtApiProvider(
        endpoint="https://tmt.ilprl.ku.edu.np",
        transport=httpx.MockTransport(fail_handler),
        retry_attempts=1,
    )

    smart = SmartTmtProvider(official=official, legacy=legacy, enable_fallback=True)
    results = asyncio.run(smart.translate_batch(_request()))

    # Fixture should produce known translations for test text
    assert len(results) == 2
    assert results[0].provider_tier == "fixture_fallback"
    assert smart.last_provider_used == "fixture_fallback"
    assert "failure on API tiers" in smart.last_fallback_reason


def test_smart_provider_falls_back_to_fixture_when_no_api_key() -> None:
    from sanad_api.services.providers import SmartTmtProvider

    # No official, no legacy — should go straight to fixture
    smart = SmartTmtProvider(official=None, legacy=None, enable_fallback=True)
    results = asyncio.run(smart.translate_batch(_request()))

    assert len(results) == 2
    assert results[0].provider_tier == "fixture_fallback"
    assert smart.last_provider_used == "fixture_fallback"


def test_smart_provider_reports_status() -> None:
    from sanad_api.services.providers import OfficialTmtApiProvider, SmartTmtProvider

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"message_type": "SUCCESS", "output": "ok"})

    official = OfficialTmtApiProvider(
        endpoint="https://tmt.ilprl.ku.edu.np/lang-translate",
        api_key="team_test",
        transport=httpx.MockTransport(handler),
        rate_limit_delay=0,
    )

    smart = SmartTmtProvider(official=official, legacy=None, enable_fallback=True)
    status = smart.get_status()

    assert status["official_configured"] is True
    assert status["legacy_configured"] is False
    assert status["fallback_enabled"] is True
