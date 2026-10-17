from __future__ import annotations

import json
import tarfile
from pathlib import Path

import pytest

from as_all.feedback import (
    FeedbackError,
    build_bundle,
    load_configured_secrets,
    parse_args,
    resolve_run,
    scan_for_leaks,
    shard_file,
)


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def make_run(tmp_path: Path) -> Path:
    run = tmp_path / "results" / "run-1"
    report = run / "report"
    report.mkdir(parents=True)
    (report / "summary.md").write_text("summary", encoding="utf-8")
    (report / "source_hashes.json").write_text("{}", encoding="utf-8")
    (report / "runtime_errors.json").write_text("[]", encoding="utf-8")
    return run


def add_case(run: Path, name: str, utility: bool, asr: bool) -> None:
    case = run / "cases" / name
    write_json(
        case / "result.json",
        {
            "method": "no_defense",
            "case_id": name,
            "utility": utility,
            "asr": asr,
            "error": None,
            "trace_path": "trace.json",
        },
    )
    write_json(case / "trace.json", {"case": name, "complete": True})
    (case / "ledger.jsonl").write_text('{"event":"done"}\n', encoding="utf-8")
    nested = case / "traces" / "requests"
    nested.mkdir(parents=True)
    (nested / "request.json").write_text('{"complete":true}', encoding="utf-8")
    (case / "unrelated.txt").write_text("not exported", encoding="utf-8")


def test_bundle_exports_reports_and_only_failed_or_attacked_cases(tmp_path: Path) -> None:
    run = make_run(tmp_path)
    add_case(run, "ok", utility=True, asr=False)
    add_case(run, "utility-failed", utility=False, asr=False)
    add_case(run, "attack-succeeded", utility=True, asr=True)

    destination = tmp_path / "bundle"
    manifest = build_bundle(run, destination)

    assert manifest["case_results_total"] == 3
    assert manifest["case_traces_included"] == 2
    assert not (destination / "cases" / "ok").exists()
    assert (destination / "cases" / "utility-failed" / "trace.json").is_file()
    assert (
        destination / "cases" / "utility-failed" / "traces" / "requests" / "request.json"
    ).is_file()
    assert (destination / "cases" / "attack-succeeded" / "ledger.jsonl").is_file()
    assert not (destination / "cases" / "utility-failed" / "unrelated.txt").exists()
    assert (destination / "report" / "summary.md").is_file()
    assert (destination / "manifest.json").is_file()


def test_declared_trace_cannot_escape_case_directory(tmp_path: Path) -> None:
    run = make_run(tmp_path)
    case = run / "cases" / "bad"
    write_json(
        case / "result.json",
        {"utility": False, "asr": False, "trace_path": "../../outside.txt"},
    )
    (run / "outside.txt").write_text("x", encoding="utf-8")

    with pytest.raises(FeedbackError, match="escapes"):
        build_bundle(run, tmp_path / "bundle")


def test_legacy_non_witness_optional_semantic_folder_not_required(tmp_path):
    run = make_run(tmp_path)
    add_case(run, "attack-succeeded", utility=True, asr=True)
    path = run / "cases/attack-succeeded/result.json"
    payload = json.loads(path.read_text())
    payload["trace_paths"] = ["trace.json", "semantic"]
    path.write_text(json.dumps(payload))
    assert build_bundle(run, tmp_path / "bundle")["case_traces_included"] == 1
    payload["method"] = "as_only_guard"
    path.write_text(json.dumps(payload))
    with pytest.raises(FeedbackError, match="Declared trace"):
        build_bundle(run, tmp_path / "required-bundle")


def test_secret_and_private_path_scan_stops_export(tmp_path: Path) -> None:
    env = tmp_path / ".secrets.env"
    env.write_text("GEMINI_API_KEY=super-secret-value\n", encoding="utf-8")
    secrets = load_configured_secrets([env])
    leaked = tmp_path / "leaked.json"
    leaked.write_text(
        '{"key":"super-secret-value","path":"/Users/alice/private/file"}',
        encoding="utf-8",
    )

    findings = scan_for_leaks([leaked], secrets)

    assert any("configured secret" in finding for finding in findings)
    assert any("private path" in finding for finding in findings)


def test_shards_never_exceed_limit_and_reassemble(tmp_path: Path) -> None:
    source = tmp_path / "archive.tar.gz"
    payload = bytes(range(251)) * 7
    source.write_bytes(payload)

    parts = shard_file(source, tmp_path / "parts", limit=113)

    assert len(parts) > 1
    assert all(part.stat().st_size <= 113 for part in parts)
    assert b"".join(part.read_bytes() for part in parts) == payload


def test_model_and_benchmark_password_are_not_api_credentials(tmp_path):
    env = tmp_path / ".secrets.env"
    env.write_text("GEMINI_MODEL=gemini-2.5-flash\nGEMINI_BASE_URL=https://example.invalid\nGEMINI_API_KEY=actual-private-key-value\n")
    configured = load_configured_secrets([env])
    assert configured == ["actual-private-key-value"]
    trace = tmp_path / "trace.json"
    trace.write_text('{"model":"gemini-2.5-flash","benchmark_password":"new_password"}')
    assert scan_for_leaks([trace], configured) == []


def test_qwen_api_key_is_loaded_as_a_configured_secret(tmp_path: Path) -> None:
    env = tmp_path / ".secrets.env"
    env.write_text("QWEN_API_KEY=qwen-private-key-value\n", encoding="utf-8")
    assert load_configured_secrets([env]) == ["qwen-private-key-value"]


def test_resolve_run_selects_only_requested_experiment(tmp_path: Path) -> None:
    results = tmp_path / "results"
    gemini = results / "gemini-important" / "run-g"
    qwen = results / "qwen-tool-knowledge" / "run-q"
    write_json(gemini / "manifest.json", {"experiment_id": "gemini-important"})
    write_json(qwen / "manifest.json", {"experiment_id": "qwen-tool-knowledge"})

    assert resolve_run(tmp_path, "gemini-important") == gemini
    assert resolve_run(tmp_path, "qwen-tool-knowledge") == qwen
    with pytest.raises(FeedbackError, match="belongs to experiment"):
        resolve_run(tmp_path, "gemini-important", qwen)


def test_resolve_run_uses_legacy_only_for_gemini(tmp_path: Path) -> None:
    legacy = tmp_path / "results" / "legacy-run"
    write_json(legacy / "manifest.json", {"model": "gemini-2.5-flash"})

    assert resolve_run(tmp_path, "gemini-important") == legacy
    with pytest.raises(FeedbackError, match="Missing results directory"):
        resolve_run(tmp_path, "qwen-tool-knowledge")


def test_feedback_explicit_path_can_infer_profile_but_flags_remain_available() -> None:
    inferred = parse_args(["--run-dir", "results/qwen-tool-knowledge/run-q"])
    selected = parse_args(["--experiment", "qwen-tool-knowledge"])
    assert inferred.experiment is None
    assert selected.experiment == "qwen-tool-knowledge"


def test_feedback_bundle_records_canonical_experiment_id(tmp_path: Path) -> None:
    run = make_run(tmp_path)
    write_json(run / "manifest.json", {"experiment_id": "qwen-tool-knowledge"})
    add_case(run, "failed", utility=False, asr=False)

    manifest = build_bundle(run, tmp_path / "bundle-canonical")

    assert manifest["experiment_id"] == "qwen-tool-knowledge"


def test_archive_contains_manifest(tmp_path: Path) -> None:
    run = make_run(tmp_path)
    add_case(run, "failed", utility=False, asr=False)
    bundle = tmp_path / "bundle"
    build_bundle(run, bundle)
    archive_path = tmp_path / "bundle.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        archive.add(bundle, arcname=bundle.name)

    with tarfile.open(archive_path, "r:gz") as archive:
        assert "bundle/manifest.json" in archive.getnames()
