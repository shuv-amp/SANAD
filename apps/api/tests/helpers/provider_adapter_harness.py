from collections.abc import Awaitable, Callable

from sanad_api.services.providers import (
    TranslationBatchRequest,
    TranslationResult,
    TranslationSegmentRequest,
    validate_provider_results,
)


ProviderCallable = Callable[[TranslationBatchRequest], Awaitable[list[TranslationResult]]]


def sample_provider_request() -> TranslationBatchRequest:
    return TranslationBatchRequest(
        source_lang="en",
        target_lang="ne",
        domain="public_service",
        subdomain="residence",
        segments=[
            TranslationSegmentRequest(
                segment_id="seg-001",
                source_text="Please submit this form to the Ward Office.",
                protected_entities=[{"kind": "office", "text": "Ward Office", "target_term": "वडा कार्यालय"}],
                glossary_hits=[{"source_term": "Ward Office", "target_term": "वडा कार्यालय", "term_type": "office"}],
            ),
            TranslationSegmentRequest(
                segment_id="seg-002",
                source_text="Phone: +977-9841234567",
                protected_entities=[{"kind": "phone", "text": "+977-9841234567"}],
                glossary_hits=[],
            ),
        ],
    )


async def assert_provider_adapter_contract(provider_call: ProviderCallable) -> list[TranslationResult]:
    request = sample_provider_request()
    results = await provider_call(request)
    validate_provider_results(request, results)
    return results


def results_from_recorded_fixture(payload: dict) -> list[TranslationResult]:
    items = payload.get("translations")
    if not isinstance(items, list):
        raise AssertionError("Recorded fixture must contain a top-level 'translations' list.")
    return [
        TranslationResult(segment_id=str(item["segment_id"]), translated_text=str(item["translated_text"]))
        for item in items
    ]

