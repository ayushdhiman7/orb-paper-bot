import json
import os

import pytest

from ai_audit import AuditWriteError, append_decision


def event(**overrides):
    value = {
        "event_type": "entry_review", "symbol": "RELIANCE",
        "model": "gemini-test", "attempt": 1, "status": "approved",
        "decision": "take", "reason": "setup aligned", "duration_ms": 120,
    }
    value.update(overrides)
    return value


def test_appends_structured_record_without_prompt_or_secret(tmp_path):
    path = tmp_path / "audit.jsonl"
    append_decision(event(reason="good setup"), path=path)
    record = json.loads(path.read_text().strip())
    assert record["symbol"] == "RELIANCE"
    assert record["decision"] == "take"
    assert "prompt" not in record
    assert "raw_response" not in record
    assert os.stat(path).st_mode & 0o777 == 0o600


def test_sanitizes_multiline_and_limits_text(tmp_path):
    path = tmp_path / "audit.jsonl"
    append_decision(event(reason="line1\nline2" + "x" * 300), path=path)
    record = json.loads(path.read_text().strip())
    assert "\n" not in record["reason"]
    assert len(record["reason"]) == 200


def test_rejects_unknown_event_and_status(tmp_path):
    with pytest.raises(AuditWriteError):
        append_decision(event(event_type="unknown"), path=tmp_path / "a.jsonl")
    with pytest.raises(AuditWriteError):
        append_decision(event(status="secret"), path=tmp_path / "a.jsonl")


def test_audit_write_failure_raises(tmp_path):
    directory = tmp_path / "is-a-directory"
    directory.mkdir()
    with pytest.raises(AuditWriteError):
        append_decision(event(), path=directory)


def test_appends_multiple_records(tmp_path):
    path = tmp_path / "audit.jsonl"
    append_decision(event(), path=path)
    append_decision(event(status="rejected", decision="skip"), path=path)
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert len(rows) == 2
    assert rows[0]["event_id"] != rows[1]["event_id"]
