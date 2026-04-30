import asyncio
import json
import time
import httpx


# Configuration
OFFICIAL_ENDPOINT = "https://tmt.ilprl.ku.edu.np/lang-translate"
LEGACY_ENDPOINT = "https://tmt.ilprl.ku.edu.np/translate"
API_KEY = "team_ce8a839bb29c7c7a"

# Language codes to test
LANG_CODES = {
    "official": {
        # The official API returned success for lowercase 'en'/'ne' via curl.
        # We test every combo: en, ne, tam, EN, NE, TAM, Tamang, etc.
        "test_cases": [
            # (src, tgt, label)
            ("en", "ne", "EN→NE lowercase"),
            ("en", "tam", "EN→TAM lowercase"),
            ("ne", "en", "NE→EN lowercase"),
            ("ne", "tam", "NE→TAM lowercase"),
            ("tam", "en", "TAM→EN lowercase"),
            ("tam", "ne", "TAM→NE lowercase"),
            ("EN", "NE", "EN→NE UPPERCASE"),
            ("EN", "TAM", "EN→TAM UPPERCASE"),
            ("NE", "EN", "NE→EN UPPERCASE"),
            ("NE", "TAM", "NE→TAM UPPERCASE"),
            ("TAM", "EN", "TAM→EN UPPERCASE"),
            ("TAM", "NE", "TAM→NE UPPERCASE"),
            ("English", "Nepali", "English→Nepali canonical"),
            ("English", "Tamang", "English→Tamang canonical"),
            ("Nepali", "English", "Nepali→English canonical"),
            ("Nepali", "Tamang", "Nepali→Tamang canonical"),
            ("Tamang", "English", "Tamang→English canonical"),
            ("Tamang", "Nepali", "Tamang→Nepali canonical"),
            # Internal SANAD codes
            ("en", "tmg", "EN→TMG (SANAD internal)"),
            ("tmg", "en", "TMG→EN (SANAD internal)"),
        ],
    },
    "legacy": {
        "test_cases": [
            ("English", "Nepali", "English→Nepali"),
            ("English", "Tamang", "English→Tamang"),
            ("Nepali", "English", "Nepali→English"),
            ("Nepali", "Tamang", "Nepali→Tamang"),
            ("Tamang", "English", "Tamang→English"),
            ("Tamang", "Nepali", "Tamang→Nepali"),
            ("en", "ne", "en→ne shortcode"),
            ("en", "tam", "en→tam shortcode"),
        ],
    },
}

TEST_SENTENCE = "Hello world"


async def test_official_api():
    print("=" * 70)
    print("TIER 1: OFFICIAL TMT API  —  POST /lang-translate")
    print("=" * 70)
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }
    results = []
    async with httpx.AsyncClient(timeout=20) as client:
        for src, tgt, label in LANG_CODES["official"]["test_cases"]:
            payload = {"text": TEST_SENTENCE, "src_lang": src, "tgt_lang": tgt}
            start = time.monotonic()
            try:
                resp = await client.post(OFFICIAL_ENDPOINT, json=payload, headers=headers)
                elapsed = (time.monotonic() - start) * 1000
                body = resp.text
                status = resp.status_code
                # Parse output if success
                output = ""
                if status == 200:
                    try:
                        data = resp.json()
                        output = data.get("output", "")[:40]
                    except Exception:
                        pass
                results.append((label, status, elapsed, output, body[:100] if status != 200 else ""))
            except Exception as e:
                elapsed = (time.monotonic() - start) * 1000
                results.append((label, "ERR", elapsed, "", str(e)[:80]))

    print(f"\n{'Label':<35} {'Status':<8} {'Time(ms)':<10} {'Output':<45} {'Error'}")
    print("-" * 150)
    for label, status, elapsed, output, error in results:
        status_str = f"{status}"
        ok = "✅" if status == 200 else "❌"
        print(f"{ok} {label:<33} {status_str:<8} {elapsed:<10.0f} {output:<45} {error}")
    return results


async def test_legacy_api():
    print("\n" + "=" * 70)
    print("TIER 2: LEGACY TMT API  —  POST /translate")
    print("=" * 70)
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    results = []
    async with httpx.AsyncClient(timeout=20) as client:
        for src, tgt, label in LANG_CODES["legacy"]["test_cases"]:
            payload = {"src_lang": src, "tgt_lang": tgt, "text": TEST_SENTENCE}
            start = time.monotonic()
            try:
                resp = await client.post(LEGACY_ENDPOINT, json=payload, headers=headers)
                elapsed = (time.monotonic() - start) * 1000
                body = resp.text
                status = resp.status_code
                output = ""
                if status == 200:
                    try:
                        data = resp.json()
                        # Legacy returns NLLB200 key
                        output = (data.get("NLLB200") or next(iter(data.values()), ""))[:40]
                    except Exception:
                        pass
                results.append((label, status, elapsed, output, body[:100] if status != 200 else ""))
            except Exception as e:
                elapsed = (time.monotonic() - start) * 1000
                results.append((label, "ERR", elapsed, "", str(e)[:80]))

    print(f"\n{'Label':<35} {'Status':<8} {'Time(ms)':<10} {'Output':<45} {'Error'}")
    print("-" * 150)
    for label, status, elapsed, output, error in results:
        status_str = f"{status}"
        ok = "✅" if status == 200 else "❌"
        print(f"{ok} {label:<33} {status_str:<8} {elapsed:<10.0f} {output:<45} {error}")
    return results


async def test_sanad_normalization():
    """Test what our normalize functions actually produce."""
    import sys
    sys.path.insert(0, "src")
    from sanad_api.services.providers import _normalize_lang_for_api

    print("\n" + "=" * 70)
    print("SANAD NORMALIZATION AUDIT")
    print("=" * 70)

    inputs = ["en", "ne", "tam", "tmg", "english", "nepali", "tamang", "EN", "NE", "TAM", "TMG", "Tamang"]
    
    print(f"\n{'Input':<15} {'_normalize_lang_for_api':<25}")
    print("-" * 40)
    for inp in inputs:
        try:
            result = _normalize_lang_for_api(inp)
        except ValueError as e:
            result = f"ERROR: {e}"
        print(f"  {inp:<13} {result:<25}")


async def test_fixture_provider():
    """Test the fixture fallback for all language combos."""
    import sys
    sys.path.insert(0, "src")
    from sanad_api.services.providers import FixtureTranslationProvider, TranslationBatchRequest, TranslationSegmentRequest

    print("\n" + "=" * 70)
    print("TIER 3: FIXTURE PROVIDER AUDIT")
    print("=" * 70)

    provider = FixtureTranslationProvider()
    test_texts = [
        "Certificate of Residence Request",
        "Please submit this form to the Ward Office.",
        "Fee: NPR 500",
        "This text has no fixture match.",
    ]
    combos = [("en", "tmg"), ("en", "ne"), ("ne", "en"), ("ne", "tmg"), ("tmg", "en"), ("tmg", "ne")]

    for src, tgt in combos:
        print(f"\n  {src} → {tgt}:")
        req = TranslationBatchRequest(
            source_lang=src, target_lang=tgt, domain="public_service", subdomain="residence",
            segments=[
                TranslationSegmentRequest(segment_id=str(i), source_text=t, protected_entities=[], glossary_hits=[])
                for i, t in enumerate(test_texts)
            ]
        )
        results = await provider.translate_batch(req)
        for r in results:
            src_text = test_texts[int(r.segment_id)][:40]
            translated = r.translated_text[:50] if r.translated_text else "(empty)"
            matched = "✅ MATCHED" if translated != src_text else "⚠️  PASSTHROUGH (no fixture)"
            print(f"    {matched}: \"{src_text}\" → \"{translated}\"")


async def main():
    official_results = await test_official_api()
    legacy_results = await test_legacy_api()
    await test_sanad_normalization()
    await test_fixture_provider()

    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    
    official_ok = sum(1 for _, s, *_ in official_results if s == 200)
    official_total = len(official_results)
    legacy_ok = sum(1 for _, s, *_ in legacy_results if s == 200)
    legacy_total = len(legacy_results)

    print(f"\n  Official API: {official_ok}/{official_total} passed")
    print(f"  Legacy API:   {legacy_ok}/{legacy_total} passed")
    
    # Identify which language codes actually work
    print("\n  Working Official codes:")
    for label, status, *_ in official_results:
        if status == 200:
            print(f"    ✅ {label}")
    
    print("\n  Working Legacy codes:")
    for label, status, *_ in legacy_results:
        if status == 200:
            print(f"    ✅ {label}")


if __name__ == "__main__":
    asyncio.run(main())
