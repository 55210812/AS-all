import json

import pytest

from as_all import bootstrap, feedback, report
from as_all.cli import preflight, registry
from as_all.experiments import EXPERIMENTS, get_experiment
from as_all.methods import METHODS, ROOT


EXPERIMENT = "gemini-tool-knowledge"


def test_full_input_coverage_and_profile_isolation(tmp_path):
    profile = get_experiment(EXPERIMENT)
    attacks = json.loads((ROOT / "data" / profile.attacks_file).read_text())
    rows = registry(experiment=EXPERIMENT)
    assert len(attacks) == 949
    for method in METHODS:
        cases = [r for r in rows if r["method"] == method]
        assert len(cases) == 1046
        assert sum(r["injection"] is None for r in cases) == 97
        assert {r["case_id"] for r in cases if r["injection"]} == attacks.keys()
    all_ids = [r["id"] for experiment in EXPERIMENTS for r in registry(experiment=experiment)]
    assert len(all_ids) == len(set(all_ids)) == 3 * 11506
    state = preflight(tmp_path, download=False, experiment=EXPERIMENT)
    assert len(state["cases"]) == 11506
    assert state["provider"] == "gemini"
    assert state["workers"] == 8


def test_menu_cli_and_feedback_accept_third_profile(tmp_path, monkeypatch):
    parser = bootstrap.build_parser()
    for action in ("start", "status"):
        assert parser.parse_args([action, "--experiment", EXPERIMENT]).experiment == EXPERIMENT
    assert feedback.parse_args(["--experiment", EXPERIMENT]).experiment == EXPERIMENT
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini")
    monkeypatch.setenv("GEMINI_BASE_URL", "https://example.invalid/v1beta")
    env = bootstrap.runtime_env(tmp_path, experiment=EXPERIMENT)
    assert env["AS_ALL_EXPERIMENT"] == EXPERIMENT
    assert env["GEMINI_API_KEY"] == "test-gemini"
    assert bootstrap._active_path(tmp_path, EXPERIMENT) != bootstrap._active_path(tmp_path, "gemini-important")
    assert bootstrap._session_name(tmp_path, EXPERIMENT) != bootstrap._session_name(tmp_path, "gemini-important")
    assert bootstrap._cron_marker(tmp_path, EXPERIMENT) != bootstrap._cron_marker(tmp_path, "gemini-important")


def test_feedback_cannot_mix_gemini_attacks(tmp_path):
    runs = {}
    for experiment in ("gemini-important", EXPERIMENT):
        run = tmp_path / "results" / experiment / "run-one"
        run.mkdir(parents=True)
        (run / "manifest.json").write_text(json.dumps({"experiment_id": experiment}))
        runs[experiment] = run.resolve()
    assert feedback.resolve_run(tmp_path, EXPERIMENT) == runs[EXPERIMENT]
    assert feedback.resolve_run(tmp_path, "gemini-important") == runs["gemini-important"]
    with pytest.raises(feedback.FeedbackError, match="belongs to experiment"):
        feedback.resolve_run(tmp_path, EXPERIMENT, runs["gemini-important"])


def test_report_identity_uses_gemini_tool_knowledge_profile(tmp_path):
    (tmp_path / "manifest.json").write_text(json.dumps({"experiment_id": EXPERIMENT, "source_hashes": {}, "cases": []}))
    report.report(tmp_path)
    text = (tmp_path / "report" / "summary.md").read_text()
    assert "gemini-2.5-flash tool_knowledge" in text
    assert "供应商：`gemini`" in text


@pytest.mark.parametrize("domain", ["slack", "travel", "workspace", "banking"])
def test_attack_matches_original_tool_knowledge_builder(domain):
    from types import SimpleNamespace
    from agentdojo.attacks.important_instructions_attacks import ToolKnowledgeAttack
    from agentdojo.task_suite.load_suites import get_suite

    profile = get_experiment(EXPERIMENT)
    frozen = json.loads((ROOT / "data" / profile.attacks_file).read_text())
    suite = get_suite("v1.2.2", domain)
    builder = ToolKnowledgeAttack(suite, SimpleNamespace(name=profile.model))
    for row in registry(experiment=EXPERIMENT):
        if row["domain"] != domain or row["method"] != "no_defense" or not row["injection"]:
            continue
        expected = builder.attack(suite.get_user_task_by_id(row["task"]),
                                  suite.get_injection_task_by_id(row["injection"]))
        assert frozen[row["case_id"]] == expected
        assert expected and all("AI model developed by Google" in text and
                                "Remember to substitute the placeholders" in text for text in expected.values())
