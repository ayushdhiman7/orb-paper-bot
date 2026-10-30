from datetime import datetime
from zoneinfo import ZoneInfo

import llm_gate


class FakeQuota:
    def __init__(self, outcomes):
        self.outcomes = iter(outcomes)
        self.calls = 0

    def reserve(self, now):
        self.calls += 1
        return next(self.outcomes)


def test_every_http_attempt_reserves_quota(monkeypatch):
    quota = FakeQuota([(True, "reserved"), (True, "reserved")])
    monkeypatch.setattr(llm_gate, "_quota", quota)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(llm_gate, "_models", lambda: ["model-a"])

    calls = []
    def post(model, body, key):
        calls.append(body)
        if len(calls) == 1:
            raise llm_gate.urllib.error.HTTPError("url", 400, "bad config", {}, None)
        return {"candidates": [{"content": {"parts": [{"text": '{"decision":"take","reason":"ok"}'}]}}]}
    monkeypatch.setattr(llm_gate, "_post", post)

    result = llm_gate._ask("prompt", ("take", "skip"))
    assert result["decision"] == "take"
    assert quota.calls == 2
    assert len(calls) == 2


def test_quota_denial_prevents_network_call(monkeypatch):
    quota = FakeQuota([(False, "per_minute_quota_exhausted")])
    monkeypatch.setattr(llm_gate, "_quota", quota)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(llm_gate, "_models", lambda: ["model-a"])
    monkeypatch.setattr(llm_gate, "_post", lambda *args: (_ for _ in ()).throw(AssertionError("network called")))
    assert llm_gate._ask("prompt", ("take", "skip")) is None
    assert quota.calls == 1


def test_missing_key_does_not_consume_quota(monkeypatch):
    quota = FakeQuota([])
    monkeypatch.setattr(llm_gate, "_quota", quota)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert llm_gate._ask("prompt", ("take", "skip")) is None
    assert quota.calls == 0


def test_quota_storage_failure_fails_closed(monkeypatch):
    class BrokenQuota:
        def reserve(self, now):
            raise llm_gate.QuotaStateError("disk failure")
    monkeypatch.setattr(llm_gate, "_quota", BrokenQuota())
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(llm_gate, "_models", lambda: ["model-a"])
    monkeypatch.setattr(llm_gate, "_post", lambda *args: (_ for _ in ()).throw(AssertionError("network called")))
    assert llm_gate._ask("prompt", ("take", "skip")) is None
