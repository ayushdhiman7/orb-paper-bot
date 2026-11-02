import llm_gate


class FakeQuota:
    def __init__(self, outcomes):
        self.outcomes = iter(outcomes)
        self.calls = 0

    def reserve(self, now):
        self.calls += 1
        return next(self.outcomes)


def _allow_audit(monkeypatch):
    events = []
    monkeypatch.setattr(llm_gate, "_audit", lambda event: events.append(event) or True)
    return events


def test_every_http_attempt_reserves_quota_and_audits_retry(monkeypatch):
    quota = FakeQuota([(True, "reserved"), (True, "reserved")])
    monkeypatch.setattr(llm_gate, "_quota", quota)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(llm_gate, "_models", lambda: ["model-a"])
    events = _allow_audit(monkeypatch)
    calls = []

    def post(model, body, key):
        calls.append(body)
        if len(calls) == 1:
            raise llm_gate.urllib.error.HTTPError("url", 400, "bad config", {}, None)
        return {"candidates": [{"content": {"parts": [{"text": '{"decision":"take","reason":"ok"}'}]}}]}

    monkeypatch.setattr(llm_gate, "_post", post)
    result = llm_gate._ask("private prompt", ("take", "skip"), symbol="RELIANCE")
    assert result["decision"] == "take"
    assert quota.calls == 2
    assert len(calls) == 2
    assert [e["http_status"] for e in events if e.get("http_status")] == [400]
    assert events[-1]["decision"] == "take"
    assert all("private prompt" not in str(e) for e in events)


def test_model_fallback_also_consumes_quota_and_audits(monkeypatch):
    quota = FakeQuota([(True, "reserved"), (True, "reserved")])
    monkeypatch.setattr(llm_gate, "_quota", quota)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(llm_gate, "_models", lambda: ["missing-model", "working-model"])
    events = _allow_audit(monkeypatch)
    calls = []

    def post(model, body, key):
        calls.append(model)
        if model == "missing-model":
            raise llm_gate.urllib.error.HTTPError("url", 404, "missing", {}, None)
        return {"candidates": [{"content": {"parts": [{"text": '{"decision":"take","reason":"ok"}'}]}}]}

    monkeypatch.setattr(llm_gate, "_post", post)
    assert llm_gate._ask("prompt", ("take", "skip"))["decision"] == "take"
    assert calls == ["missing-model", "working-model"]
    assert quota.calls == 2
    assert len(events) == 2


def test_quota_denial_prevents_network_call_and_is_audited(monkeypatch):
    quota = FakeQuota([(False, "per_minute_quota_exhausted")])
    monkeypatch.setattr(llm_gate, "_quota", quota)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(llm_gate, "_models", lambda: ["model-a"])
    events = _allow_audit(monkeypatch)
    monkeypatch.setattr(llm_gate, "_post", lambda *args: (_ for _ in ()).throw(AssertionError("network called")))
    assert llm_gate._ask("prompt", ("take", "skip")) is None
    assert quota.calls == 1
    assert events[0]["status"] == "quota_blocked"


def test_missing_key_is_audited_without_consuming_quota(monkeypatch):
    quota = FakeQuota([])
    monkeypatch.setattr(llm_gate, "_quota", quota)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    events = _allow_audit(monkeypatch)
    assert llm_gate._ask("prompt", ("take", "skip")) is None
    assert quota.calls == 0
    assert events[0]["error_type"] == "MissingApiKey"


def test_quota_storage_failure_fails_closed(monkeypatch):
    class BrokenQuota:
        def reserve(self, now):
            raise llm_gate.QuotaStateError("disk failure")
    monkeypatch.setattr(llm_gate, "_quota", BrokenQuota())
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(llm_gate, "_models", lambda: ["model-a"])
    _allow_audit(monkeypatch)
    monkeypatch.setattr(llm_gate, "_post", lambda *args: (_ for _ in ()).throw(AssertionError("network called")))
    assert llm_gate._ask("prompt", ("take", "skip")) is None


def test_audit_failure_suppresses_valid_ai_decision(monkeypatch):
    quota = FakeQuota([(True, "reserved")])
    monkeypatch.setattr(llm_gate, "_quota", quota)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(llm_gate, "_models", lambda: ["model-a"])
    monkeypatch.setattr(llm_gate, "_audit", lambda event: False)
    monkeypatch.setattr(llm_gate, "_post", lambda *args: {
        "candidates": [{"content": {"parts": [{"text": '{"decision":"take","reason":"ok"}'}]}}]
    })
    assert llm_gate._ask("prompt", ("take", "skip")) is None


def test_review_helpers_set_audit_type_and_symbol(monkeypatch):
    seen = {}
    monkeypatch.setattr(llm_gate, "_ask", lambda prompt, allowed, **kwargs: seen.update(kwargs) or None)
    llm_gate.review({"symbol": "TCS", "price": 123})
    assert seen == {"event_type": "entry_review", "symbol": "TCS"}
    llm_gate.review_exit({"symbol": "INFY"})
    assert seen == {"event_type": "position_review", "symbol": "INFY"}



def test_audit_failure_on_http_error_stops_model_fallback(monkeypatch):
    quota = FakeQuota([(True, "reserved")])
    monkeypatch.setattr(llm_gate, "_quota", quota)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(llm_gate, "_models", lambda: ["broken-model", "fallback-model"])
    monkeypatch.setattr(llm_gate, "_audit", lambda event: False)
    calls = []

    def post(model, body, key):
        calls.append(model)
        raise llm_gate.urllib.error.HTTPError("url", 404, "missing", {}, None)

    monkeypatch.setattr(llm_gate, "_post", post)
    assert llm_gate._ask("prompt", ("take", "skip")) is None
    assert calls == ["broken-model"]
