"""Two configurable providers, bounded retries, and one deadline per tutor turn.

The rest of the application calls generate(); it does not need provider SDKs.
No keys or model defaults live in code. HTTP responses/prompts are never logged.
"""
import asyncio
import json
import logging
import os
import random
from dataclasses import dataclass, field
from urllib.parse import quote, urlparse

import httpx

from schemas import TutorHint

logger = logging.getLogger(__name__)
RETRYABLE = {408, 500, 502, 503, 504}


class LLMUnavailable(RuntimeError):
    def __init__(self, reason="provider_unavailable"):
        self.reason = reason
        super().__init__("No configured AI provider returned a valid tutor response.")


class InvalidOutput(ValueError):
    pass


@dataclass(frozen=True)
class Provider:
    slot: str
    kind: str
    model: str
    api_key: str = field(repr=False)
    base_url: str = ""


def _provider(slot):
    prefix = f"LLM_{slot.upper()}_"
    kind = os.getenv(prefix + "PROVIDER", "").strip()
    # Backward compatibility: the existing two Gemini variables still work.
    if slot == "primary" and not kind:
        kind = "gemini"
    if not kind:
        return None
    if kind not in ("gemini", "openai_compatible"):
        raise LLMUnavailable("configuration")
    key = os.getenv(prefix + "API_KEY", "").strip()
    model = os.getenv(prefix + "MODEL", "").strip()
    if slot == "primary" and kind == "gemini":
        key = key or os.getenv("GEMINI_API_KEY", "").strip()
        model = model or os.getenv("GEMINI_MODEL", "").strip()
    base = os.getenv(prefix + "BASE_URL", "").strip().rstrip("/")
    if kind == "gemini":
        base = base or "https://generativelanguage.googleapis.com/v1beta"
    parsed = urlparse(base)
    # Provider endpoints are configured by the backend operator, never the client.
    if not key or not model or parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.query or parsed.fragment:
        raise LLMUnavailable("configuration")
    return Provider(slot, kind, model, key, base)


def _number(name, default, minimum, maximum, cast=float):
    try:
        value = cast(os.getenv(name, str(default)))
        if not minimum <= value <= maximum:
            raise ValueError
        return value
    except ValueError:
        raise LLMUnavailable("configuration") from None


def _request(provider, prompt, max_tokens):
    if provider.kind == "gemini":
        return (
            f"{provider.base_url}/models/{quote(provider.model, safe='')}:generateContent",
            {"x-goog-api-key": provider.api_key},
            {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
             "generationConfig": {"responseMimeType": "application/json", "temperature": 0.3,
                                  "maxOutputTokens": max_tokens}},
        )
    return (
        f"{provider.base_url}/chat/completions",
        {"Authorization": f"Bearer {provider.api_key}"},
        {"model": provider.model, "messages": [{"role": "user", "content": prompt}],
         "response_format": {"type": "json_object"}, "max_tokens": max_tokens, "stream": False},
    )


def _text(provider, payload):
    try:
        if provider.kind == "gemini":
            candidate = payload["candidates"][0]
            if candidate.get("finishReason") != "STOP":
                raise InvalidOutput
            result = "".join(p.get("text", "") for p in candidate["content"]["parts"] if not p.get("thought"))
        else:
            choice = payload["choices"][0]
            if choice.get("finish_reason") != "stop":
                raise InvalidOutput
            result = choice["message"]["content"]
        if not isinstance(result, str) or not result.strip():
            raise InvalidOutput
        return result.strip()
    except (KeyError, IndexError, TypeError):
        raise InvalidOutput from None


async def _attempt(client, provider, prompt, max_tokens, validator):
    url, headers, body = _request(provider, prompt, max_tokens)
    # Bound response memory as well as waiting time.
    async with client.stream("POST", url, headers=headers, json=body) as response:
        if response.status_code >= 400:
            return None, response.status_code, response.headers.get("Retry-After")
        data = bytearray()
        async for chunk in response.aiter_bytes():
            data.extend(chunk)
            if len(data) > 1024 * 1024:
                raise InvalidOutput
    raw = _text(provider, json.loads(data))
    TutorHint.model_validate_json(raw)
    if validator:
        validator(raw)
    return raw, 200, None


async def _try_provider(client, provider, prompt, validator, attempts, attempt_timeout, max_tokens):
    reason = "provider_unavailable"
    for attempt in range(attempts):
        retry_after = None
        try:
            raw, status, retry_after = await asyncio.wait_for(
                _attempt(client, provider, prompt, max_tokens, validator), attempt_timeout)
            if raw is not None:
                logger.info("Tutor provider succeeded slot=%s attempt=%s", provider.slot, attempt + 1)
                return raw
            reason = ("rate_limited" if status == 429 else "authentication" if status in (401, 403)
                      else "configuration" if status in (400, 404, 422) else "provider_unavailable")
            logger.warning("Tutor provider failed slot=%s status=%s attempt=%s", provider.slot, status, attempt + 1)
            # A quota or credential problem will not be fixed by immediate retries.
            if status not in RETRYABLE:
                break
        except (InvalidOutput, ValueError, TypeError):
            reason = "invalid_output"
            logger.warning("Tutor provider output rejected slot=%s", provider.slot)
            break  # Try the backup rather than repeat the same invalid generation.
        except (httpx.RequestError, asyncio.TimeoutError):
            logger.warning("Tutor provider network failure slot=%s attempt=%s", provider.slot, attempt + 1)
        if attempt + 1 < attempts:
            delay = min(2 ** attempt, 3) + random.uniform(0, 0.25)
            if retry_after:
                try:
                    delay = max(delay, float(retry_after))
                except ValueError:
                    break  # Unknown/date-valued cooldown: switch providers, do not retry early.
                if delay > 3:
                    break
            await asyncio.sleep(delay)
    raise LLMUnavailable(reason)


async def generate_async(prompt, validator=None, *, transport=None):
    """Reserve time for the backup; all network calls and sleeps are cancellable."""
    total = _number("LLM_TOTAL_TIMEOUT_SECONDS", 30, 1, 30)
    attempt_timeout = _number("LLM_ATTEMPT_TIMEOUT_SECONDS", 8, 0.1, 15)
    attempts = _number("LLM_MAX_ATTEMPTS", 2, 1, 3, int)
    max_tokens = _number("LLM_MAX_OUTPUT_TOKENS", 1024, 128, 4096, int)
    providers = []
    failures = []
    for slot in ("primary", "backup"):
        try:
            provider = _provider(slot)
            if provider:
                providers.append(provider)
        except LLMUnavailable as exc:
            failures.append(exc.reason)
            logger.warning("Tutor provider configuration invalid slot=%s", slot)
    if not providers:
        raise LLMUnavailable("configuration")

    async def run():
        async with httpx.AsyncClient(transport=transport, timeout=attempt_timeout, follow_redirects=False) as client:
            for index, provider in enumerate(providers):
                # Primary cannot consume the backup's reserved share of the deadline.
                budget = total / 2 if len(providers) == 2 and index == 0 else total
                try:
                    return await asyncio.wait_for(_try_provider(
                        client, provider, prompt, validator, attempts, attempt_timeout, max_tokens), budget)
                except LLMUnavailable as exc:
                    failures.append(exc.reason)
                except asyncio.TimeoutError:
                    failures.append("provider_unavailable")
            raise LLMUnavailable(failures[-1] if failures else "provider_unavailable")
    try:
        return await asyncio.wait_for(run(), total)
    except asyncio.TimeoutError:
        raise LLMUnavailable("provider_unavailable") from None


def generate(prompt, validator=None):
    # Existing FastAPI endpoints are synchronous worker-thread functions.
    return asyncio.run(generate_async(prompt, validator))
