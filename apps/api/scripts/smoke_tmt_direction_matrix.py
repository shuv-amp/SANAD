import argparse
import asyncio
import json
import os
from datetime import datetime
from pathlib import Path

from sanad_api.services.providers import (
    LegacyTmtApiProvider,
    TranslationBatchRequest,
    TranslationSegmentRequest,
    validate_provider_results,
)


CASES = [
    {
        "direction": "English -> Nepali",
        "source_lang": "English",
        "target_lang": "Nepali",
        "text": "Please submit this form to the Ward Office.",
    },
    {
        "direction": "Nepali -> English",
        "source_lang": "Nepali",
        "target_lang": "English",
        "text": "कृपया यो फारम वडा कार्यालयमा बुझाउनुहोस्।",
    },
    {
        "direction": "English -> Tamang",
        "source_lang": "English",
        "target_lang": "Tamang",
        "text": "Please submit this form.",
    },
    {
        "direction": "Tamang -> English",
        "source_lang": "Tamang",
        "target_lang": "English",
        "text": "चु फाराम पेस लास्ह्युगो।",
    },
    {
        "direction": "Nepali -> Tamang",
        "source_lang": "Nepali",
        "target_lang": "Tamang",
        "text": "कृपया यो फारम बुझाउनुहोस्।",
    },
    {
        "direction": "Tamang -> Nepali",
        "source_lang": "Tamang",
        "target_lang": "Nepali",
        "text": "चु फाराम पेस लास्ह्युगो।",
    },
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke-test all six public TMT directions through SANAD's adapter.")
    parser.add_argument("--endpoint", default=os.getenv("SANAD_TMT_API_ENDPOINT") or "https://tmt.ilprl.ku.edu.np")
    parser.add_argument("--output", default=str(Path(__file__).resolve().parents[3] / "docs" / "tmt-direction-observations.json"))
    args = parser.parse_args()

    results = asyncio.run(_collect(args.endpoint))
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(results, ensure_ascii=False, indent=2))
    print(f"Wrote direction observations to {output_path}")


async def _collect(endpoint: str) -> dict:
    provider = LegacyTmtApiProvider(
        endpoint=endpoint,
        api_key=os.getenv("SANAD_TMT_API_KEY"),
        auth_method=os.getenv("SANAD_TMT_AUTH_METHOD") or "none",
        timeout_seconds=float(os.getenv("SANAD_TMT_TIMEOUT_SECONDS", "20")),
        batch_size=1,
    )
    observations = []
    for index, case in enumerate(CASES, start=1):
        request = TranslationBatchRequest(
            source_lang=case["source_lang"],
            target_lang=case["target_lang"],
            domain="public_service",
            subdomain="residence",
            segments=[
                TranslationSegmentRequest(
                    segment_id=f"case-{index}",
                    source_text=case["text"],
                    protected_entities=[],
                    glossary_hits=[],
                )
            ],
        )
        try:
            results = await provider.translate_batch(request)
            validate_provider_results(request, results)
            translated_text = results[0].translated_text.strip()
            verdict = _verdict(case["text"], translated_text)
            observations.append(
                {
                    "direction": case["direction"],
                    "source_lang": case["source_lang"],
                    "target_lang": case["target_lang"],
                    "sample_input": case["text"],
                    "sample_output": translated_text,
                    "verdict": verdict,
                }
            )
        except Exception as exc:  # noqa: BLE001 - evidence harness should record failures verbatim
            observations.append(
                {
                    "direction": case["direction"],
                    "source_lang": case["source_lang"],
                    "target_lang": case["target_lang"],
                    "sample_input": case["text"],
                    "sample_output": "",
                    "verdict": "failed",
                    "error": str(exc),
                }
            )
    return {
        "tested_at": datetime.now().astimezone().isoformat(),
        "endpoint": endpoint,
        "cases": observations,
    }


def _verdict(source_text: str, translated_text: str) -> str:
    if not translated_text:
        return "failed"
    if translated_text.strip() == source_text.strip():
        return "ambiguous"
    return "responded"


if __name__ == "__main__":
    main()
