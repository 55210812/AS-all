import json
import pytest
from as_all.cli import atomic, manager_lock, preflight, registry, source_hashes
from as_all.report import cost, report


def test_manifest_freezes_sources_and_expected_counts(tmp_path):
    data = preflight(tmp_path, acceptance=True, download=False)
    assert len(data["cases"]) == 22
    assert data["case_retries"] == data["manager_restores"] == 0
    assert preflight(tmp_path, acceptance=True, download=False) == data
    with pytest.raises(RuntimeError, match="Frozen"):
        preflight(tmp_path, acceptance=False, download=False)


def test_manager_lock_prevents_duplicate(tmp_path):
    with manager_lock(tmp_path), pytest.raises(BlockingIOError), manager_lock(tmp_path):
        pass


def test_raw_cache_and_thinking_counted_once(tmp_path):
    path = tmp_path / "requests.jsonl"
    events = [dict(event="request_started", request_id="r1", stage="agent"),
              dict(event="request_completed", request_id="r1", stage="agent", elapsed_seconds=1,
                   raw_usage=dict(promptTokenCount=100, candidatesTokenCount=5, thoughtsTokenCount=10,
                                  totalTokenCount=115, cachedContentTokenCount=25))]
    path.write_text("\n".join(json.dumps(e) for e in events))
    data = cost(path)["agent"]
    assert data["raw_input"] == 100 and data["noncached_input"] == 75 and data["output"] == 15
    assert data["requests"] == 1
    events[1]["raw_usage"].pop("cachedContentTokenCount")
    path.write_text("\n".join(json.dumps(e) for e in events))
    assert cost(path)["agent"]["unknown_cache"] == 1


def test_runtime_error_not_success_and_report_incomplete(tmp_path):
    cases = registry(True)
    atomic(tmp_path / "manifest.json", {"cases": cases, "source_hashes": source_hashes()})
    atomic(tmp_path / "cases" / cases[0]["id"] / "result.json",
           {**cases[0], "utility": None, "asr": None, "error": "InterruptedSingleAuthorizedAttempt",
            "duration_seconds": None})
    state = report(tmp_path)
    assert state["terminal"] == 1 and state["runtime_errors"] == 1 and not state["all_terminal"]
    summaries = json.loads((tmp_path / "report/summary.json").read_text())
    assert all(r["normal"] == 0 for r in summaries)


def test_retry_usage_not_discarded_and_unknown_separate(tmp_path):
    path = tmp_path / "requests.jsonl"
    usage = dict(promptTokenCount=100, candidatesTokenCount=5, totalTokenCount=115)
    events = [dict(event="request_started", request_id="r1", stage="agent"),
              dict(event="request_completed", request_id="r1", stage="agent", raw_usage=usage,
                   transport_attempts=[dict(retry=True, raw_usage=usage),
                                       dict(retry=True), dict(status_code=200)])]
    path.write_text("\n".join(json.dumps(e) for e in events))
    data = cost(path)["agent"]
    assert data["requests"] == 3
    assert data["raw_input"] == 200 and data["output"] == 30
    assert data["missing_usage"] == 1 and data["unknown_cache"] == 2


def test_request_boundary_blocks_frozen_changes(tmp_path, monkeypatch):
    from as_all.cli import check_request_boundary
    preflight(tmp_path, acceptance=True, download=False)
    monkeypatch.setattr("as_all.cli.source_hashes", lambda: {})
    with pytest.raises(RuntimeError, match="FrozenSourceMismatch"):
        check_request_boundary(tmp_path)
    assert json.loads((tmp_path / "STOP.json").read_text())["reason"] == "FrozenSourceMismatch"
