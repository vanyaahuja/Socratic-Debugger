"""Real router + mocked HTTP: no keys, paid API calls, or downloaded models."""
import asyncio
import json
import logging
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from services import llm_provider as lp


HINT = {"message": "What invariant does the loop maintain?", "response_type": "question",
        "reasoning_stage": "identify_bug", "concept": "loops", "hint_level": 1,
        "solution_leakage": False}


@pytest.fixture(autouse=True)
def config(monkeypatch):
    monkeypatch.setenv("LLM_PRIMARY_PROVIDER", "gemini")
    monkeypatch.setenv("LLM_PRIMARY_API_KEY", "primary-test-secret")
    monkeypatch.setenv("LLM_PRIMARY_MODEL", "test-primary-model")
    monkeypatch.setenv("LLM_PRIMARY_BASE_URL", "https://primary.example/v1beta")
    monkeypatch.setenv("LLM_BACKUP_PROVIDER", "openai_compatible")
    monkeypatch.setenv("LLM_BACKUP_API_KEY", "backup-test-secret")
    monkeypatch.setenv("LLM_BACKUP_MODEL", "test-backup-model")
    monkeypatch.setenv("LLM_BACKUP_BASE_URL", "https://backup.example/v1")
    monkeypatch.setenv("LLM_TOTAL_TIMEOUT_SECONDS", "2")
    monkeypatch.setenv("LLM_ATTEMPT_TIMEOUT_SECONDS", "0.5")
    monkeypatch.setenv("LLM_MAX_ATTEMPTS", "2")
    monkeypatch.setenv("LLM_MAX_OUTPUT_TOKENS", "512")


def success(request, hint=HINT):
    if request.url.host == "primary.example":
        return httpx.Response(200, json={"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": json.dumps(hint)}]}}]})
    return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(hint)}}]})


def run(handler, validator=None):
    return asyncio.run(lp.generate_async("private conversation", validator, transport=httpx.MockTransport(handler)))


def test_primary_succeeds_without_backup():
    calls = []
    def handler(req):
        calls.append(req)
        assert req.headers["x-goog-api-key"] == "primary-test-secret"
        assert "key=" not in str(req.url)
        return success(req)
    assert json.loads(run(handler)) == HINT
    assert len(calls) == 1


def test_503_is_retried_then_uses_backup_with_same_context(monkeypatch, caplog):
    monkeypatch.setenv("LLM_TOTAL_TIMEOUT_SECONDS", "6")
    monkeypatch.setattr(lp.random, "uniform", lambda *args: 0)
    calls = []
    def handler(req):
        calls.append(req)
        if req.url.host == "primary.example":
            return httpx.Response(503, json={"error": "private provider body"})
        assert req.headers["Authorization"] == "Bearer backup-test-secret"
        return success(req)
    with caplog.at_level(logging.INFO, logger=lp.__name__):
        assert json.loads(run(handler)) == HINT
    assert [r.url.host for r in calls] == ["primary.example", "primary.example", "backup.example"]
    first, last = json.loads(calls[0].content), json.loads(calls[-1].content)
    assert first["contents"][0]["parts"][0]["text"] == last["messages"][0]["content"]
    assert "primary-test-secret" not in caplog.text and "backup-test-secret" not in caplog.text
    assert "private conversation" not in caplog.text and "private provider body" not in caplog.text


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422, 429])
def test_nontransient_statuses_switch_without_retry(status):
    calls = []
    def handler(req):
        calls.append(req.url.host)
        return httpx.Response(status) if req.url.host == "primary.example" else success(req)
    run(handler)
    assert calls == ["primary.example", "backup.example"]


def test_primary_can_recover_on_retry(monkeypatch):
    monkeypatch.setenv("LLM_TOTAL_TIMEOUT_SECONDS", "6")
    calls = []
    def handler(req):
        calls.append(req)
        return httpx.Response(503) if len(calls) == 1 else success(req)
    run(handler)
    assert len(calls) == 2 and all(r.url.host == "primary.example" for r in calls)


def test_malformed_output_switches_to_backup():
    def handler(req):
        return httpx.Response(200, json={"candidates": []}) if req.url.host == "primary.example" else success(req)
    assert json.loads(run(handler)) == HINT


def test_teaching_validator_can_reject_primary():
    bad = {**HINT, "hint_level": 5}
    def validate(raw):
        if json.loads(raw)["hint_level"] > 1:
            raise lp.InvalidOutput
    assert json.loads(run(lambda req: success(req, bad if req.url.host == "primary.example" else HINT), validate)) == HINT


def test_truncated_output_switches_to_backup():
    def handler(req):
        if req.url.host == "primary.example":
            return httpx.Response(200, json={"candidates": [{"finishReason": "MAX_TOKENS"}]})
        return success(req)
    assert json.loads(run(handler)) == HINT


def test_both_providers_fail_with_safe_error():
    with pytest.raises(lp.LLMUnavailable, match="No configured AI provider"):
        run(lambda req: httpx.Response(429, json={"secret": "must-not-escape"}))


def test_long_retry_after_switches_to_backup():
    calls = []
    def handler(req):
        calls.append(req.url.host)
        return httpx.Response(503, headers={"Retry-After": "120"}) if req.url.host == "primary.example" else success(req)
    run(handler)
    assert calls == ["primary.example", "backup.example"]


def test_slow_primary_leaves_time_for_backup(monkeypatch):
    monkeypatch.setenv("LLM_TOTAL_TIMEOUT_SECONDS", "1")
    monkeypatch.setenv("LLM_ATTEMPT_TIMEOUT_SECONDS", "1")
    calls = []
    async def handler(req):
        calls.append(req.url.host)
        if req.url.host == "primary.example":
            await asyncio.sleep(5)
        return success(req)
    assert json.loads(run(handler)) == HINT
    assert calls == ["primary.example", "backup.example"]


def test_global_deadline(monkeypatch):
    monkeypatch.setenv("LLM_TOTAL_TIMEOUT_SECONDS", "1")
    async def handler(req):
        await asyncio.sleep(5)
        return success(req)
    with pytest.raises(lp.LLMUnavailable):
        run(handler)


def test_model_is_required_not_hardcoded(monkeypatch):
    monkeypatch.delenv("LLM_PRIMARY_MODEL")
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    monkeypatch.setenv("LLM_BACKUP_PROVIDER", "")
    with pytest.raises(lp.LLMUnavailable) as exc:
        run(lambda req: pytest.fail("Should not make a request"))
    assert exc.value.reason == "configuration"


def test_backup_disabled_means_no_other_destination(monkeypatch):
    monkeypatch.setenv("LLM_BACKUP_PROVIDER", "")
    monkeypatch.setenv("LLM_MAX_ATTEMPTS", "1")
    calls = []
    def handler(req):
        calls.append(req.url.host)
        return httpx.Response(503)
    with pytest.raises(lp.LLMUnavailable):
        run(handler)
    assert calls == ["primary.example"]


def test_invalid_limits_fail_without_network(monkeypatch):
    monkeypatch.setenv("LLM_TOTAL_TIMEOUT_SECONDS", "nan")
    with pytest.raises(lp.LLMUnavailable):
        run(lambda req: pytest.fail("Should not make a request"))


def test_ten_concurrent_turns_keep_contexts_separate(monkeypatch):
    monkeypatch.setenv("LLM_MAX_ATTEMPTS", "1")
    async def handler(req):
        if req.url.host == "primary.example":
            return httpx.Response(503)
        prompt = json.loads(req.content)["messages"][0]["content"]
        await asyncio.sleep(0.01)
        return success(req, {**HINT, "message": prompt})
    async def concurrent():
        return await asyncio.gather(*(lp.generate_async(f"unique turn {i}", transport=httpx.MockTransport(handler)) for i in range(10)))
    results = asyncio.run(concurrent())
    assert [json.loads(r)["message"] for r in results] == [f"unique turn {i}" for i in range(10)]
