import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Protocol
from urllib.parse import urlsplit

import httpx

from sanad_api.config import get_settings
from sanad_api.services.demo_content import translate_demo_text

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data contracts
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TranslationSegmentRequest:
    segment_id: str
    source_text: str
    protected_entities: list[dict]
    glossary_hits: list[dict]


@dataclass(frozen=True)
class TranslationBatchRequest:
    source_lang: str
    target_lang: str
    domain: str
    subdomain: str
    segments: list[TranslationSegmentRequest]


@dataclass(frozen=True)
class TranslationResult:
    segment_id: str
    translated_text: str
    provider_tier: str = "unknown"
    error: str | None = None


class ProviderConfigurationError(ValueError):
    pass


class ProviderContractError(ValueError):
    pass


class TranslationProvider(Protocol):
    name: str
    is_implemented: bool
    notes: str

    async def translate_batch(self, request: TranslationBatchRequest) -> list[TranslationResult]:
        ...


# ---------------------------------------------------------------------------
# Fixture provider (deterministic — always works)
# ---------------------------------------------------------------------------

class FixtureTranslationProvider:
    name = "fixture"
    is_implemented = True
    notes = "Deterministic multilingual fixture provider for SANAD reliability."

    async def translate_batch(self, request: TranslationBatchRequest) -> list[TranslationResult]:
        return [
            TranslationResult(
                segment_id=item.segment_id,
                translated_text=self._translate(request.source_lang, request.target_lang, item.source_text),
                provider_tier="fixture",
            )
            for item in request.segments
        ]

    def _translate(self, source_lang: str, target_lang: str, text: str) -> str:
        translated = translate_demo_text(source_lang, target_lang, text)
        return translated if translated is not None else text


# ---------------------------------------------------------------------------
# Mock provider (contract tests)
# ---------------------------------------------------------------------------

class MockTranslationProvider:
    name = "mock"
    is_implemented = True
    notes = "Mechanical mock provider for provider contract tests."

    async def translate_batch(self, request: TranslationBatchRequest) -> list[TranslationResult]:
        return [
            TranslationResult(
                segment_id=item.segment_id,
                translated_text=f"[mock:{request.target_lang}] {item.source_text}",
                provider_tier="mock",
            )
            for item in request.segments
        ]


# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

_RETRYABLE_STATUS_CODES = {500, 502, 503, 504}
_DEFAULT_RETRY_ATTEMPTS = 3
_RETRY_BACKOFF_SECONDS = 0.4

_LANGUAGE_ALIASES_TO_CANONICAL = {
    "english": "English", "en": "English", "eng": "English",
    "nepali": "Nepali", "ne": "Nepali", "nep": "Nepali",
    "tamang": "Tamang", "tam": "Tamang", "tm": "Tamang", "tmg": "Tamang",
}


def _normalize_lang_for_api(language: str) -> str:
    """Normalize any language input to canonical names (English/Nepali/Tamang).

    Canonical names are the ONLY format verified to work on BOTH the Official
    TMT API (/lang-translate) and the Legacy TMT API (/translate).

    Verified 2026-04-26 via deep audit:
      - Official API rejects 'tam', 'TAM', but accepts 'Tamang', 'tmg', 'English', 'Nepali'
      - Legacy API rejects all short codes ('en', 'ne', 'tam'), only accepts canonical names
      - Canonical names work on BOTH endpoints for ALL 6 language pair combinations
    """
    normalized = _LANGUAGE_ALIASES_TO_CANONICAL.get((language or "").strip().lower())
    if normalized:
        return normalized
    raise ValueError(
        "Unsupported TMT language value. "
        "Supported: English/en, Nepali/ne, Tamang/tmg (and aliases eng, nep, tam, tm)."
    )


def _segment_chunks(segments: list[TranslationSegmentRequest], size: int) -> list[list[TranslationSegmentRequest]]:
    chunk_size = max(1, size)
    return [segments[index:index + chunk_size] for index in range(0, len(segments), chunk_size)]


class _RequestPacer:
    def __init__(self, min_interval_seconds: float) -> None:
        self.min_interval_seconds = max(0.0, min_interval_seconds)
        self._lock = asyncio.Lock()
        self._next_slot = 0.0

    async def wait(self) -> None:
        if self.min_interval_seconds <= 0:
            return
        async with self._lock:
            loop = asyncio.get_running_loop()
            now = loop.time()
            if now < self._next_slot:
                await asyncio.sleep(self._next_slot - now)
                now = loop.time()
            self._next_slot = now + self.min_interval_seconds


# ---------------------------------------------------------------------------
# Official TMT API Provider (Tier 1 — /lang-translate with Bearer auth)
# ---------------------------------------------------------------------------

class OfficialTmtApiProvider:
    name = "tmt_official"
    is_implemented = True
    notes = (
        "Official TMT API adapter. "
        "Uses POST /lang-translate with Bearer token authentication."
    )

    def __init__(
        self,
        *,
        endpoint: str | None = None,
        api_key: str | None = None,
        timeout_seconds: float = 20.0,
        batch_size: int = 25,
        rate_limit_delay: float = 0.1,
        concurrency: int = 8,
        transport: httpx.AsyncBaseTransport | None = None,
        retry_attempts: int = _DEFAULT_RETRY_ATTEMPTS,
    ) -> None:
        self.endpoint = endpoint
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.batch_size = max(1, batch_size)
        self.rate_limit_delay = max(0, rate_limit_delay)
        self.concurrency = max(1, concurrency)
        self.transport = transport
        self.retry_attempts = max(1, retry_attempts)

    async def translate_batch(self, request: TranslationBatchRequest) -> list[TranslationResult]:
        url = self._resolve_url()
        headers = self._build_headers()
        src_lang = _normalize_lang_for_api(request.source_lang)
        tgt_lang = _normalize_lang_for_api(request.target_lang)
        print(f"📦 translate_batch received {len(request.segments)} segments for {src_lang} -> {tgt_lang}")

        semaphore = asyncio.Semaphore(self.concurrency)
        pacer = _RequestPacer(self.rate_limit_delay)

        async def _translate_one(segment: TranslationSegmentRequest, *, use_semaphore: bool = True) -> TranslationResult:
            source_text = segment.source_text.strip()
            if not source_text:
                return TranslationResult(segment.segment_id, "", provider_tier="tmt_official", error="Empty source text")
            payload = {"text": source_text, "src_lang": src_lang, "tgt_lang": tgt_lang}

            async def _run_request() -> TranslationResult:
                try:
                    await pacer.wait()
                    print(f"📡 TMT REQ: {src_lang} -> {tgt_lang} | Text: {source_text[:30]}...")
                    response_data = await self._post_with_retries(client, url, headers, payload)
                    print(f"📥 TMT RESP: {str(response_data)[:200]}...")
                    translated = self._extract_output(response_data)
                    return TranslationResult(
                        segment_id=segment.segment_id,
                        translated_text=translated,
                        provider_tier="tmt_official",
                    )
                except Exception as exc:
                    print(f"❌ TMT API Error for segment {segment.segment_id}: {exc}")
                    return TranslationResult(
                        segment_id=segment.segment_id,
                        translated_text="",
                        provider_tier="tmt_official",
                        error=str(exc)
                    )

            if use_semaphore:
                async with semaphore:
                    return await _run_request()
            return await _run_request()

        async with httpx.AsyncClient(timeout=self.timeout_seconds, transport=self.transport) as client:
            results_by_id: dict[str, TranslationResult] = {}
            failed_segments: list[TranslationSegmentRequest] = []
            for chunk in _segment_chunks(request.segments, self.batch_size):
                print(f"📡 Sending chunk of {len(chunk)} segments...")
                chunk_results = await asyncio.gather(*[_translate_one(seg) for seg in chunk])
                print(f"✅ Chunk finished with {len(chunk_results)} results")
                for segment, result in zip(chunk, chunk_results, strict=True):
                    results_by_id[result.segment_id] = result
                    if result.error:
                        failed_segments.append(segment)

            # A slower second pass recovers transient failures without dropping straight to fallback.
            if failed_segments:
                print(f"🔄 Retrying {len(failed_segments)} failed segments sequentially...")
                for segment in failed_segments:
                    retry_result = await _translate_one(segment, use_semaphore=False)
                    if not retry_result.error:
                        results_by_id[retry_result.segment_id] = retry_result

        print(f"📊 Assembling results for {len(request.segments)} segments...")
        final_results = []
        for segment in request.segments:
            if segment.segment_id not in results_by_id:
                print(f"⚠️ MISSING segment_id: {segment.segment_id} in results_by_id! Adding placeholder.")
                final_results.append(TranslationResult(
                    segment_id=segment.segment_id,
                    translated_text="[TIMEOUT/FAILED]",
                    provider_tier="tmt_official",
                    error="Segment lost during batch processing"
                ))
            else:
                final_results.append(results_by_id[segment.segment_id])
        return final_results

    def _resolve_url(self) -> str:
        endpoint = (self.endpoint or "").strip()
        if not endpoint:
            raise ProviderConfigurationError(
                "TMT official API endpoint is not configured. Set SANAD_TMT_OFFICIAL_ENDPOINT."
            )
        parsed = urlsplit(endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ProviderConfigurationError(
                "SANAD_TMT_OFFICIAL_ENDPOINT must be an absolute http(s) URL."
            )
        path = parsed.path.rstrip("/")
        if not path.endswith("/lang-translate"):
            path = f"{path}/lang-translate" if path else "/lang-translate"
        return parsed._replace(path=path, query="", fragment="").geturl()

    def _build_headers(self) -> dict[str, str]:
        if not self.api_key:
            raise ProviderConfigurationError(
                "SANAD_TMT_API_KEY is required for the official TMT API. "
                "Ensure you have a valid authentication token for the primary API."
            )
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

    async def _post_with_retries(
        self, client: httpx.AsyncClient, url: str, headers: dict, payload: dict,
    ) -> dict:
        for attempt in range(1, self.retry_attempts + 1):
            try:
                if attempt > 1:
                    print(f"🔄 Retrying TMT API (attempt {attempt}/{self.retry_attempts})...")
                response = await client.post(url, headers=headers, json=payload)
            except (httpx.TimeoutException, httpx.NetworkError, httpx.TransportError) as exc:
                if attempt >= self.retry_attempts:
                    raise ValueError(
                        "Official TMT API request failed after retries (network/timeout)."
                    ) from exc
                print(f"⚠️ TMT API network error: {exc}. Retrying...")
                await asyncio.sleep(_RETRY_BACKOFF_SECONDS * attempt)
                continue

            if response.status_code == 429:
                if attempt >= self.retry_attempts:
                    raise ValueError("Official TMT API rate limit exceeded after retries.")
                print(f"⏳ TMT API rate limit (429). Waiting...")
                await self._retry_delay(response, attempt)
                continue

            if response.status_code in _RETRYABLE_STATUS_CODES:
                if attempt >= self.retry_attempts:
                    raise ValueError(
                        f"Official TMT API temporarily unavailable (status {response.status_code})."
                    )
                print(f"🔄 TMT API error {response.status_code}. Retrying...")
                await self._retry_delay(response, attempt)
                continue

            if response.status_code >= 400:
                raise ValueError(self._format_error(response))

            try:
                data = response.json()
            except ValueError as exc:
                raise ValueError("Official TMT API returned non-JSON response.") from exc
            if not isinstance(data, dict):
                raise ValueError("Official TMT API returned unexpected JSON payload.")
            return data
        raise ValueError("Official TMT API request failed after retries.")

    async def _retry_delay(self, response: httpx.Response, attempt: int) -> None:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                await asyncio.sleep(max(0.0, float(retry_after)))
                return
            except ValueError:
                pass
        await asyncio.sleep(_RETRY_BACKOFF_SECONDS * attempt)

    def _extract_output(self, data: dict) -> str:
        msg_type = data.get("message_type", "")
        if msg_type == "FAIL":
            detail = data.get("message", "Unknown error")
            raise ValueError(f"Official TMT API translation failed: {detail}")
        output = data.get("output")
        if isinstance(output, str) and output.strip():
            return output.strip()
        # Fallback: try any string value in case response shape differs
        for value in data.values():
            if isinstance(value, str) and value.strip() and value not in {"SUCCESS", "FAIL"}:
                return value.strip()
        raise ValueError("Official TMT API response did not include translated text.")

    def _format_error(self, response: httpx.Response) -> str:
        status = response.status_code
        if status in {401, 403}:
            return "Official TMT API authentication failed. Check SANAD_TMT_API_KEY."
        detail = ""
        try:
            payload = response.json()
            if isinstance(payload, dict):
                detail = payload.get("message", "") or payload.get("error", "") or payload.get("detail", "")
        except ValueError:
            detail = response.text.strip()[:200]
        if status == 400 and detail:
            return f"Official TMT API rejected request: {detail}"
        if detail:
            return f"Official TMT API error (status {status}): {detail}"
        return f"Official TMT API error (status {status})."


# ---------------------------------------------------------------------------
# Legacy TMT Provider (Tier 2 — /translate public workaround, no auth)
# ---------------------------------------------------------------------------

class LegacyTmtApiProvider:
    name = "tmt_legacy"
    is_implemented = True
    notes = (
        "HTTP adapter for the public TMT website /translate workaround. "
        "Used as automatic fallback when the official API is unavailable."
    )
    todos = [
        "This legacy endpoint may be deprecated in future releases.",
    ]

    def __init__(
        self,
        *,
        endpoint: str | None = None,
        api_key: str | None = None,
        auth_method: str | None = None,
        timeout_seconds: float = 20.0,
        batch_size: int = 25,
        rate_limit_delay: float = 0.0,
        concurrency: int = 8,
        transport: httpx.AsyncBaseTransport | None = None,
        retry_attempts: int = _DEFAULT_RETRY_ATTEMPTS,
    ) -> None:
        self.endpoint = endpoint
        self.api_key = api_key
        self.auth_method = auth_method
        self.timeout_seconds = timeout_seconds
        self.batch_size = max(1, batch_size)
        self.rate_limit_delay = max(0, rate_limit_delay)
        self.concurrency = max(1, concurrency)
        self.transport = transport
        self.retry_attempts = max(1, retry_attempts)

    async def translate_batch(self, request: TranslationBatchRequest) -> list[TranslationResult]:
        translate_url = self._resolve_translate_url()
        src_lang = _normalize_lang_for_api(request.source_lang)
        tgt_lang = _normalize_lang_for_api(request.target_lang)
        headers = self._build_headers()

        semaphore = asyncio.Semaphore(self.concurrency)
        pacer = _RequestPacer(self.rate_limit_delay)

        async def _translate_one(segment: TranslationSegmentRequest, *, use_semaphore: bool = True) -> TranslationResult:
            source_text = segment.source_text.strip()
            if not source_text:
                return TranslationResult(segment.segment_id, "", provider_tier="tmt_legacy", error="Empty source text")
            payload = {"src_lang": src_lang, "tgt_lang": tgt_lang, "text": source_text}

            async def _run_request() -> TranslationResult:
                try:
                    await pacer.wait()
                    print(f"📡 TMT LEGACY REQ: {src_lang} -> {tgt_lang} | Text: {source_text[:30]}...")
                    response_payload = await self._post_with_retries(client, translate_url, headers, payload)
                    print(f"📥 TMT LEGACY RESP: {str(response_payload)[:200]}...")
                    translated_text = self._extract_translated_text(response_payload)
                    return TranslationResult(
                        segment_id=segment.segment_id,
                        translated_text=translated_text,
                        provider_tier="tmt_legacy",
                    )
                except Exception as exc:
                    return TranslationResult(
                        segment_id=segment.segment_id,
                        translated_text="",
                        provider_tier="tmt_legacy",
                        error=str(exc)
                    )

            if use_semaphore:
                async with semaphore:
                    return await _run_request()
            return await _run_request()

        async with httpx.AsyncClient(timeout=self.timeout_seconds, transport=self.transport) as client:
            results_by_id: dict[str, TranslationResult] = {}
            failed_segments: list[TranslationSegmentRequest] = []
            for chunk in _segment_chunks(request.segments, self.batch_size):
                chunk_results = await asyncio.gather(*[_translate_one(seg) for seg in chunk])
                for segment, result in zip(chunk, chunk_results, strict=True):
                    results_by_id[result.segment_id] = result
                    if result.error:
                        failed_segments.append(segment)

            for segment in failed_segments:
                retry_result = await _translate_one(segment, use_semaphore=False)
                if not retry_result.error:
                    results_by_id[retry_result.segment_id] = retry_result

        return [results_by_id[segment.segment_id] for segment in request.segments]

    def _resolve_translate_url(self) -> str:
        endpoint = (self.endpoint or "").strip()
        if not endpoint:
            raise ProviderConfigurationError(
                "SANAD_TMT_API_ENDPOINT is required for the legacy TMT provider."
            )
        parsed = urlsplit(endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ProviderConfigurationError(
                "SANAD_TMT_API_ENDPOINT must be an absolute http(s) URL."
            )
        path = parsed.path.rstrip("/")
        if not path.endswith("/translate"):
            path = f"{path}/translate" if path else "/translate"
        return parsed._replace(path=path, query="", fragment="").geturl()

    def _build_headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        method = (self.auth_method or "none").strip().lower()
        if method in {"", "none"}:
            return headers
        if method in {"bearer", "token"}:
            if not self.api_key:
                raise ProviderConfigurationError("SANAD_TMT_API_KEY is required when SANAD_TMT_AUTH_METHOD=bearer.")
            headers["Authorization"] = f"Bearer {self.api_key}"
            return headers
        if method in {"x-api-key", "api_key", "apikey"}:
            if not self.api_key:
                raise ProviderConfigurationError("SANAD_TMT_API_KEY is required when SANAD_TMT_AUTH_METHOD=x-api-key.")
            headers["x-api-key"] = self.api_key
            return headers
        if method in {"authorization", "raw"}:
            if not self.api_key:
                raise ProviderConfigurationError("SANAD_TMT_API_KEY is required when SANAD_TMT_AUTH_METHOD=authorization.")
            headers["Authorization"] = self.api_key
            return headers
        raise ProviderConfigurationError(
            "Unsupported SANAD_TMT_AUTH_METHOD. Valid values: none, bearer, x-api-key, authorization."
        )

    async def _post_with_retries(self, client, url, headers, payload) -> dict:
        for attempt in range(1, self.retry_attempts + 1):
            try:
                if attempt > 1:
                    print(f"🔄 Retrying TMT LEGACY API (attempt {attempt}/{self.retry_attempts})...")
                response = await client.post(url, headers=headers, json=payload)
            except (httpx.TimeoutException, httpx.NetworkError, httpx.TransportError) as exc:
                if attempt >= self.retry_attempts:
                    raise ValueError("Legacy TMT provider request failed after retries (network/timeout).") from exc
                print(f"⚠️ TMT LEGACY API network error: {exc}. Retrying...")
                await asyncio.sleep(_RETRY_BACKOFF_SECONDS * attempt)
                continue

            if response.status_code == 429:
                if attempt >= self.retry_attempts:
                    raise ValueError("Legacy TMT provider rate limit exceeded after retries.")
                print(f"⏳ TMT LEGACY API rate limit (429). Waiting...")
                await self._retry_delay(response, attempt)
                continue

            if response.status_code in _RETRYABLE_STATUS_CODES:
                if attempt >= self.retry_attempts:
                    raise ValueError(f"Legacy TMT provider temporarily unavailable (status {response.status_code}).")
                print(f"🔄 TMT LEGACY API error {response.status_code}. Retrying...")
                await self._retry_delay(response, attempt)
                continue

            if response.status_code >= 400:
                raise ValueError(self._normalize_error_response(response))

            try:
                payload_json = response.json()
            except ValueError as exc:
                raise ValueError("Legacy TMT provider returned a non-JSON response.") from exc
            if not isinstance(payload_json, dict):
                raise ValueError("Legacy TMT provider returned an unexpected JSON payload.")
            return payload_json
        raise ValueError("Legacy TMT provider request failed after retries.")

    async def _retry_delay(self, response: httpx.Response, attempt: int) -> None:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                await asyncio.sleep(max(0.0, float(retry_after)))
                return
            except ValueError:
                pass
        await asyncio.sleep(_RETRY_BACKOFF_SECONDS * attempt)

    def _normalize_error_response(self, response: httpx.Response) -> str:
        status = response.status_code
        detail = self._extract_error_detail(response)
        if status in {401, 403}:
            return "Legacy TMT provider authentication failed."
        if status in {400, 404, 422}:
            return f"Legacy TMT provider rejected request: {detail}" if detail else "Legacy TMT provider rejected request."
        if status == 429:
            return "Legacy TMT provider rate limit exceeded."
        if status >= 500:
            return "Legacy TMT provider internal error."
        return f"Legacy TMT provider request failed (status {status}): {detail}" if detail else f"Legacy TMT provider request failed (status {status})."

    def _extract_error_detail(self, response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            return response.text.strip()
        if isinstance(payload, dict):
            for key in ("error", "detail", "message"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        return ""

    def _extract_translated_text(self, payload: dict) -> str:
        preferred = payload.get("NLLB200")
        if isinstance(preferred, str) and preferred.strip():
            return preferred.strip()
        for value in payload.values():
            if isinstance(value, str) and value.strip():
                return value.strip()
        raise ValueError("Legacy TMT provider response did not include translated text.")


# ---------------------------------------------------------------------------
# Smart TMT Provider (orchestrates Tier 1 → Tier 2 → Tier 3 fallback)
# ---------------------------------------------------------------------------

class SmartTmtProvider:
    name = "tmt_api"
    is_implemented = True
    notes = (
        "Smart multi-tier translation provider with automatic fallback. "
        "Tier 1: Official TMT API → Tier 2: Legacy public endpoint → Tier 3: Fixture."
    )

    def __init__(
        self,
        *,
        official: OfficialTmtApiProvider | None = None,
        legacy: LegacyTmtApiProvider | None = None,
        fixture: FixtureTranslationProvider | None = None,
        enable_fallback: bool = True,
    ) -> None:
        self.official = official
        self.legacy = legacy
        self.fixture = fixture or FixtureTranslationProvider()
        self.enable_fallback = enable_fallback
        self.last_provider_used: str = "none"
        self.last_fallback_reason: str | None = None
        self._api_available: bool | None = None
        self._api_checked_at: float = 0

    async def translate_batch(self, request: TranslationBatchRequest) -> list[TranslationResult]:
        final_results = []
        pending_segments = request.segments
        tier1_reason = None
        tier2_reason = None

        # --- Tier 1: Official API ---
        if self.official and pending_segments:
            tier_req = TranslationBatchRequest(
                source_lang=request.source_lang,
                target_lang=request.target_lang,
                domain=request.domain,
                subdomain=request.subdomain,
                segments=pending_segments,
            )
            try:
                tier1_results = await self.official.translate_batch(tier_req)
                successes = [r for r in tier1_results if not r.error]
                final_results.extend(successes)
                
                failed_ids = {r.segment_id for r in tier1_results if r.error}
                pending_segments = [s for s in pending_segments if s.segment_id in failed_ids]
                
                self.last_provider_used = "tmt_official"
                self.last_fallback_reason = None
                self._api_available = True
                self._api_checked_at = time.monotonic()
                logger.info(f"SmartTmtProvider: Tier 1 succeeded for {len(successes)} segments. {len(pending_segments)} failed.")
            except (ProviderConfigurationError, ValueError, Exception) as exc:
                tier1_reason = str(exc)
                logger.warning("SmartTmtProvider: Tier 1 failed completely: %s", tier1_reason)
                if not self.enable_fallback:
                    raise
        else:
            tier1_reason = "Official TMT API not configured (no API key or endpoint)."
            logger.info("SmartTmtProvider: Tier 1 skipped — %s", tier1_reason)

        # --- Tier 2: Legacy endpoint ---
        if self.legacy and pending_segments and self.enable_fallback:
            tier_req = TranslationBatchRequest(
                source_lang=request.source_lang,
                target_lang=request.target_lang,
                domain=request.domain,
                subdomain=request.subdomain,
                segments=pending_segments,
            )
            try:
                tier2_results = await self.legacy.translate_batch(tier_req)
                successes = [r for r in tier2_results if not r.error]
                final_results.extend(successes)
                
                failed_ids = {r.segment_id for r in tier2_results if r.error}
                pending_segments = [s for s in pending_segments if s.segment_id in failed_ids]
                
                if not tier1_reason:
                    tier1_reason = "Rate limit or partial failure on Official API"
                self.last_provider_used = "tmt_legacy" if len(successes) > 0 else self.last_provider_used
                self.last_fallback_reason = f"Cascaded to legacy: {tier1_reason}"
                logger.info(f"SmartTmtProvider: Tier 2 succeeded for {len(successes)} segments. {len(pending_segments)} failed.")
            except (ProviderConfigurationError, ValueError, Exception) as exc:
                tier2_reason = str(exc)
                logger.warning("SmartTmtProvider: Tier 2 failed completely: %s", tier2_reason)
        else:
            if not self.legacy:
                tier2_reason = "Legacy TMT endpoint not configured."
                logger.info("SmartTmtProvider: Tier 2 skipped — %s", tier2_reason)

        # --- Tier 3: Fixture fallback ---
        if pending_segments and self.enable_fallback:
            logger.info(f"SmartTmtProvider: Falling back to Tier 3 (fixture) for {len(pending_segments)} segments.")
            tier_req = TranslationBatchRequest(
                source_lang=request.source_lang,
                target_lang=request.target_lang,
                domain=request.domain,
                subdomain=request.subdomain,
                segments=pending_segments,
            )
            tier3_results = await self.fixture.translate_batch(tier_req)
            for r in tier3_results:
                final_results.append(
                    TranslationResult(
                        segment_id=r.segment_id,
                        translated_text=r.translated_text,
                        provider_tier="fixture_fallback",
                    )
                )
            self.last_provider_used = "fixture_fallback"
            self.last_fallback_reason = f"Partial/Total failure on API tiers. Tier 1: {tier1_reason}; Tier 2: {tier2_reason}"
            if len(pending_segments) == len(request.segments):
                self._api_available = False
            self._api_checked_at = time.monotonic()

        # Preserve original segment order
        order_map = {s.segment_id: i for i, s in enumerate(request.segments)}
        final_results.sort(key=lambda r: order_map.get(r.segment_id, 0))
        
        return final_results

    def get_status(self) -> dict:
        return {
            "last_provider_used": self.last_provider_used,
            "last_fallback_reason": self.last_fallback_reason,
            "official_configured": self.official is not None,
            "legacy_configured": self.legacy is not None,
            "fallback_enabled": self.enable_fallback,
            "api_available": self._api_available,
        }





# ---------------------------------------------------------------------------
# Provider factory
# ---------------------------------------------------------------------------

def get_provider(name: str) -> TranslationProvider:
    provider_name = (name or "fixture").strip().lower()
    if provider_name == "fixture":
        return FixtureTranslationProvider()
    if provider_name == "mock":
        return MockTranslationProvider()
    if provider_name in {"tmt_api", "smart"}:
        return _build_smart_provider()
    if provider_name == "tmt_official":
        settings = get_settings()
        return OfficialTmtApiProvider(
            endpoint=settings.tmt_official_endpoint,
            api_key=settings.tmt_api_key,
            timeout_seconds=settings.tmt_timeout_seconds,
            batch_size=settings.tmt_provider_batch_size,
            rate_limit_delay=settings.tmt_rate_limit_delay,
            concurrency=settings.tmt_concurrency,
        )
    if provider_name == "tmt_legacy":
        settings = get_settings()
        return LegacyTmtApiProvider(
            endpoint=settings.tmt_api_endpoint,
            api_key=settings.tmt_api_key,
            auth_method=settings.tmt_auth_method,
            timeout_seconds=settings.tmt_timeout_seconds,
            batch_size=settings.tmt_provider_batch_size,
            rate_limit_delay=settings.tmt_rate_limit_delay,
            concurrency=settings.tmt_concurrency,
        )
    raise ProviderConfigurationError(
        f"Unsupported SANAD_ACTIVE_PROVIDER={name!r}. Valid values are: fixture, mock, tmt_api, tmt_official, tmt_legacy."
    )


def _build_smart_provider() -> SmartTmtProvider:
    settings = get_settings()

    # Build official provider only if API key is configured
    official = None
    if settings.tmt_api_key:
        official = OfficialTmtApiProvider(
            endpoint=settings.tmt_official_endpoint,
            api_key=settings.tmt_api_key,
            timeout_seconds=settings.tmt_timeout_seconds,
            batch_size=settings.tmt_provider_batch_size,
            rate_limit_delay=settings.tmt_rate_limit_delay,
            concurrency=settings.tmt_concurrency,
        )

    # Build legacy provider if endpoint is configured
    legacy = None
    if settings.tmt_api_endpoint:
        legacy = LegacyTmtApiProvider(
            endpoint=settings.tmt_api_endpoint,
            api_key=settings.tmt_api_key,
            auth_method=settings.tmt_auth_method,
            timeout_seconds=settings.tmt_timeout_seconds,
            batch_size=settings.tmt_provider_batch_size,
            rate_limit_delay=settings.tmt_rate_limit_delay,
            concurrency=settings.tmt_concurrency,
        )

    return SmartTmtProvider(
        official=official,
        legacy=legacy,
        enable_fallback=settings.tmt_enable_fallback,
    )


def validate_provider_results(request: TranslationBatchRequest, results: list[TranslationResult]) -> None:
    expected = [segment.segment_id for segment in request.segments]
    received = [result.segment_id for result in results]
    if len(received) != len(set(received)):
        raise ProviderContractError("Translation provider returned duplicate segment ids.")
    if set(received) != set(expected):
        missing = sorted(set(expected) - set(received))
        extra = sorted(set(received) - set(expected))
        raise ProviderContractError(f"Translation provider result ids do not match request. Missing={missing}; extra={extra}.")
    for result in results:
        if not isinstance(result.translated_text, str) or not result.translated_text.strip():
            raise ProviderContractError(f"Translation provider returned empty text for segment {result.segment_id}.")
