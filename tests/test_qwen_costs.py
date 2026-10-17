from __future__ import annotations

import json

import pytest

import as_all.report as report_module
from as_all.report import cost


def _write_ledger(path, completed):
    events = [
        {
            "event": "request_started",
            "request_id": "q1",
            "stage": "agent",
            "provider": "qwen",
        },
        {
            "event": "request_completed",
            "request_id": "q1",
            "stage": "agent",
            "provider": "qwen",
            **completed,
        },
    ]
    path.write_text(
        "\n".join(json.dumps(event) for event in events), encoding="utf-8"
    )


def test_qwen_cost_uses_openai_usage_without_double_counting_reasoning(tmp_path) -> None:
    path = tmp_path / "requests.jsonl"
    _write_ledger(
        path,
        {
            "raw_usage": {
                "prompt_tokens": 120,
                "completion_tokens": 17,
                "completion_tokens_details": {"reasoning_tokens": 11},
                "prompt_tokens_details": {"cached_tokens": 40},
            }
        },
    )

    data = cost(path)["agent"]
    assert data["requests"] == data["responses"] == 1
    assert data["raw_input"] == 120
    assert data["cached_input"] == 40
    assert data["noncached_input"] == 80
    assert data["output"] == 17
    assert data["missing_usage"] == data["unknown_cache"] == 0


def test_qwen_retry_usage_and_missing_cache_are_preserved(tmp_path) -> None:
    path = tmp_path / "requests.jsonl"
    _write_ledger(
        path,
        {
            "raw_usage": {"prompt_tokens": 30, "completion_tokens": 4},
            "transport_attempts": [
                {
                    "retry": True,
                    "raw_usage": {
                        "prompt_tokens": 20,
                        "completion_tokens": 3,
                        "prompt_tokens_details": {"cached_tokens": 5},
                    },
                },
                {"retry": True},
                {"status_code": 200},
            ],
        },
    )

    data = cost(path)["agent"]
    assert data["requests"] == 3
    assert data["responses"] == 2
    assert data["raw_input"] == 50 and data["output"] == 7
    assert data["cached_input"] == 5 and data["noncached_input"] == 15
    assert data["missing_usage"] == 1
    assert data["unknown_cache"] == 1


def test_qwen_invalid_cache_count_is_rejected(tmp_path) -> None:
    path = tmp_path / "requests.jsonl"
    _write_ledger(
        path,
        {
            "raw_usage": {
                "prompt_tokens": 10,
                "completion_tokens": 2,
                "prompt_tokens_details": {"cached_tokens": 11},
            }
        },
    )
    with pytest.raises(ValueError, match="cache"):
        cost(path)


def test_report_uses_manifest_identity_and_rejects_cross_experiment_case(
    tmp_path, monkeypatch
) -> None:
    manifest = {
        "experiment_id": "qwen-tool-knowledge",
        "model": "qwen3.5-flash",
        "attack": "tool_knowledge",
        "provider": "qwen",
        "source_hashes": {},
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    case = tmp_path / "cases" / "one"
    case.mkdir(parents=True)
    payload = {
        "id": "one",
        "case_id": "slack:0:clean",
        "method": "no_defense",
        "experiment_id": "qwen-tool-knowledge",
        "injection": None,
        "utility": True,
        "asr": None,
        "error": None,
        "duration_seconds": 1.0,
        "costs": cost(case / "missing.jsonl"),
    }
    (case / "result.json").write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(
        report_module,
        "status",
        lambda _run: {"all_terminal": False, "runtime_errors": 0},
    )

    report_module.report(tmp_path)
    summary = (tmp_path / "report" / "summary.md").read_text(encoding="utf-8")
    assert summary.startswith("# qwen3.5-flash tool_knowledge 十一方法结果")
    assert "`qwen-tool-knowledge`" in summary

    payload["experiment_id"] = "gemini-important"
    (case / "result.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="belongs to experiment"):
        report_module.report(tmp_path)
