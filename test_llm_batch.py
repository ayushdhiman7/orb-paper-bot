import json

import llm_gate


class FakeQuota:
    def __init__(self, outcomes):
        self.outcomes = iter(outcomes)
        self.calls = 0

    def reserve(self, now):
        self.calls += 1
        return next(self.outcomes)


def test_review_batch_uses_one_quota_reserved_and_audited_request(monkeypatch):
    quota = FakeQuota([(True, "reserved")])
    events = []
    monkeypatch.setattr(llm_gate, "_quota", quota)
    monkeypatch.setattr(llm_gate, "_audit", lambda event: events.append(event) or True)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(llm_gate, "_models", lambda: ["model-a"])
    calls = []

    def post(model, body, key):
        calls.append(body)
        raw = {"decisions": [
            {"symbol": "AAA", "decision": "BUY", "confidence": 0.9,
             "reason": "breakout with VWAP", "stop": 98, "target": 104, "rank": 1},
            {"symbol": "BBB", "decision": "SKIP", "confidence": 0.2,
             "reason": "weak momentum", "stop": None, "target": None, "rank": 2},
        ]}
        return {"candidates": [{"content": {"parts": [{"text": json.dumps(raw)}]}}]}

    monkeypatch.setattr(llm_gate, "_post", post)
    result = llm_gate.review_batch([{"symbol": "AAA"}, {"symbol": "BBB"}], {"AAA", "BBB"})
    assert result is not None
    assert len(result["decisions"]) == 2
    assert quota.calls == 1
    assert len(calls) == 1
    assert events[-1]["decision"] == "batch"
    assert events[-1]["status"] == "approved"


def test_review_batch_rejects_partial_or_invalid_response(monkeypatch):
    quota = FakeQuota([(True, "reserved")])
    events = []
    monkeypatch.setattr(llm_gate, "_quota", quota)
    monkeypatch.setattr(llm_gate, "_audit", lambda event: events.append(event) or True)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(llm_gate, "_models", lambda: ["model-a"])
    monkeypatch.setattr(llm_gate, "_post", lambda *args: {
        "candidates": [{"content": {"parts": [{"text": '{"decisions":[]}'}]}}]
    })
    assert llm_gate.review_batch([{"symbol": "AAA"}], {"AAA"}) is None
    assert events[-1]["status"] == "invalid_response"


def test_review_batch_audit_failure_suppresses_decisions(monkeypatch):
    quota = FakeQuota([(True, "reserved")])
    monkeypatch.setattr(llm_gate, "_quota", quota)
    monkeypatch.setattr(llm_gate, "_audit", lambda event: False)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(llm_gate, "_models", lambda: ["model-a"])
    monkeypatch.setattr(llm_gate, "_post", lambda *args: {
        "candidates": [{"content": {"parts": [{"text": json.dumps({"decisions": [
            {"symbol": "AAA", "decision": "SKIP", "confidence": 0.2,
             "reason": "no setup", "stop": None, "target": None, "rank": 1}
        ]})}]}}]
    })
    assert llm_gate.review_batch([{"symbol": "AAA"}], {"AAA"}) is None


def test_review_batch_quota_denial_makes_no_http_request(monkeypatch):
    quota = FakeQuota([(False, "daily_quota_exhausted")])
    events = []
    monkeypatch.setattr(llm_gate, "_quota", quota)
    monkeypatch.setattr(llm_gate, "_audit", lambda event: events.append(event) or True)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(llm_gate, "_models", lambda: ["model-a"])
    monkeypatch.setattr(llm_gate, "_post", lambda *args: (_ for _ in ()).throw(AssertionError("HTTP called")))
    assert llm_gate.review_batch([{"symbol": "AAA"}], {"AAA"}) is None
    assert quota.calls == 1
    assert events[-1]["status"] == "quota_blocked"
