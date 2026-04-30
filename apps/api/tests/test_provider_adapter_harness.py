import asyncio
import json
from pathlib import Path

from helpers.provider_adapter_harness import (
    assert_provider_adapter_contract,
    results_from_recorded_fixture,
    sample_provider_request,
)
from sanad_api.services.providers import FixtureTranslationProvider, validate_provider_results


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "tmt_recorded_response.example.json"


def test_adapter_harness_accepts_current_fixture_provider() -> None:
    provider = FixtureTranslationProvider()

    results = asyncio.run(assert_provider_adapter_contract(provider.translate_batch))

    assert [result.segment_id for result in results] == ["seg-001", "seg-002"]


def test_adapter_harness_validates_recorded_response_shape() -> None:
    payload = json.loads(FIXTURE_PATH.read_text())
    results = results_from_recorded_fixture(payload)

    validate_provider_results(sample_provider_request(), results)
