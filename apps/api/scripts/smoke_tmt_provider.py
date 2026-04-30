import argparse
import asyncio
import os

from sanad_api.services.providers import (
    LegacyTmtApiProvider,
    TranslationBatchRequest,
    TranslationSegmentRequest,
    validate_provider_results,
)


DEFAULT_TEXT = "तिमीले मासु खायौ?"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one live smoke request through SANAD's TMT adapter.")
    parser.add_argument("--endpoint", default=os.getenv("SANAD_TMT_API_ENDPOINT"))
    parser.add_argument("--source", default="Nepali")
    parser.add_argument("--target", default="English")
    parser.add_argument("--text", default=DEFAULT_TEXT)
    args = parser.parse_args()

    if not args.endpoint:
        raise SystemExit("Set SANAD_TMT_API_ENDPOINT or pass --endpoint, for example https://tmt.ilprl.ku.edu.np")

    asyncio.run(_smoke(args.endpoint, args.source, args.target, args.text))


async def _smoke(endpoint: str, source_lang: str, target_lang: str, text: str) -> None:
    provider = LegacyTmtApiProvider(
        endpoint=endpoint,
        api_key=os.getenv("SANAD_TMT_API_KEY"),
        auth_method=os.getenv("SANAD_TMT_AUTH_METHOD") or "none",
        timeout_seconds=float(os.getenv("SANAD_TMT_TIMEOUT_SECONDS", "20")),
        batch_size=int(os.getenv("SANAD_TMT_PROVIDER_BATCH_SIZE", "25")),
        rate_limit_delay=float(os.getenv("SANAD_TMT_RATE_LIMIT_DELAY", "0.25")),
    )
    request = TranslationBatchRequest(
        source_lang=source_lang,
        target_lang=target_lang,
        domain="public_service",
        subdomain="residence",
        segments=[
            TranslationSegmentRequest(
                segment_id="smoke-1",
                source_text=text,
                protected_entities=[],
                glossary_hits=[],
            )
        ],
    )
    results = await provider.translate_batch(request)
    validate_provider_results(request, results)

    print("Provider: tmt_api")
    print(f"Endpoint: {endpoint}")
    print(f"Payload shape: src_lang={source_lang!r}, tgt_lang={target_lang!r}, text={text!r}")
    print(f"Result: {results[0].translated_text}")


if __name__ == "__main__":
    main()
