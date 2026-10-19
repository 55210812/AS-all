from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import stat
import subprocess

import pytest

from as_all import bootstrap


def test_secret_file_has_owner_only_permissions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    answers = iter(["https://example.invalid/v1beta"])
    hidden = iter(["secret-key", "hf-secret"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))
    monkeypatch.setattr(bootstrap.getpass, "getpass", lambda _prompt: next(hidden))

    path = bootstrap.configure_secrets(tmp_path)

    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert "secret-key" in path.read_text(encoding="utf-8")
    assert "hf-secret" in path.read_text(encoding="utf-8")


def test_reuse_environment_bypasses_uv_and_preserves_acceptance(tmp_path, monkeypatch):
    monkeypatch.setenv("AS_ALL_PYTHON", "/existing/env/python")
    monkeypatch.setenv("PYTHONPATH", "/project/src")
    assert bootstrap._cli_args("run", tmp_path, acceptance=True) == [
        "/existing/env/python", "-m", "as_all.cli", "run", "--run-dir", str(tmp_path),
        "--experiment", "gemini-important", "--acceptance"]
    command = bootstrap._tmux_shell_command(tmp_path, acceptance=True)
    assert "AS_ALL_PYTHON=/existing/env/python" in command
    assert "uv run" not in command and "--acceptance" in command


def test_start_does_not_duplicate_live_tmux_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run_dir = tmp_path / "results" / "existing"
    run_dir.mkdir(parents=True)
    state = bootstrap._active_path(tmp_path)
    state.parent.mkdir()
    state.write_text(json.dumps({"run_dir": str(run_dir)}), encoding="utf-8")
    (tmp_path / ".secrets.env").write_text("GEMINI_API_KEY=x\n", encoding="utf-8")
    os.chmod(tmp_path / ".secrets.env", 0o600)
    calls: list[list[str]] = []

    monkeypatch.setattr(bootstrap, "_require_program", lambda *_args: None)
    monkeypatch.setattr(bootstrap, "_sync", lambda _root: None)
    monkeypatch.setattr(bootstrap, "_tmux_running", lambda _root, _session: True)
    monkeypatch.setattr(bootstrap, "_install_crontab", lambda *_args: None)
    monkeypatch.setattr(bootstrap, "_run", lambda args, **_kwargs: calls.append(list(args)))

    assert bootstrap.start(tmp_path, assume_yes=True, non_interactive=True) == run_dir
    assert calls == []
    assert "already running" in capsys.readouterr().out


def test_cron_preserves_unrelated_entries_and_quotes_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repo; touch PWNED"
    run_dir = root / "results" / "run $(bad)"
    run_dir.mkdir(parents=True)
    captured: dict[str, object] = {}

    def fake_run(args, **kwargs):
        if list(args) == ["crontab", "-l"]:
            return subprocess.CompletedProcess(args, 0, "5 * * * * /usr/bin/backup\n", "")
        raise AssertionError(args)

    def fake_subprocess_run(args, **kwargs):
        captured["args"] = list(args)
        captured["input"] = kwargs["input"]
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(bootstrap, "_run", fake_run)
    monkeypatch.setattr(bootstrap.subprocess, "run", fake_subprocess_run)
    bootstrap._install_crontab(root, run_dir)

    text = str(captured["input"])
    assert "5 * * * * /usr/bin/backup" in text
    assert "'" in text
    assert "repo; touch PWNED" in text
    assert captured["args"] == ["crontab", "-"]
    assert (root / ".state" / "crontab.before-watchdog.gemini-important.txt").read_text() == (
        "5 * * * * /usr/bin/backup\n"
    )


def test_cli_command_uses_argument_vector_for_hostile_run_path(tmp_path: Path) -> None:
    run_dir = tmp_path / "a; touch injected"
    args = bootstrap._cli_args("run", run_dir)
    index = args.index("--run-dir")
    assert args[index : index + 2] == ["--run-dir", str(run_dir.resolve())]
    assert args[-2:] == ["--experiment", "gemini-important"]
    assert len([part for part in args if "touch injected" in part]) == 1


def test_tmux_command_quotes_hostile_path_and_contains_no_secret(tmp_path: Path) -> None:
    run_dir = tmp_path / "run; touch injected"
    command = bootstrap._tmux_shell_command(run_dir, acceptance=False)
    split_command = shlex.split(command)
    assert split_command[split_command.index("--run-dir") + 1] == str(run_dir.resolve())
    assert str(run_dir / "run.log") in split_command
    assert "GEMINI_API_KEY" not in command


def test_noninteractive_requires_secret(tmp_path: Path) -> None:
    with pytest.raises(bootstrap.BootstrapError, match="GEMINI_API_KEY"):
        bootstrap.configure_secrets(tmp_path, non_interactive=True)


def test_stopped_existing_run_resumes_without_repeating_preflight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = tmp_path / "results" / "full-existing"
    run_dir.mkdir(parents=True)
    state = bootstrap._active_path(tmp_path)
    state.parent.mkdir()
    state.write_text(
        json.dumps({"run_dir": str(run_dir), "mode": "full"}), encoding="utf-8"
    )
    secret = tmp_path / ".secrets.env"
    secret.write_text("GEMINI_API_KEY=x\nGEMINI_BASE_URL=https://example.test\n")
    os.chmod(secret, 0o600)
    calls: list[list[str]] = []

    monkeypatch.setattr(bootstrap, "_require_program", lambda *_args: None)
    monkeypatch.setattr(bootstrap, "_sync", lambda _root: None)
    monkeypatch.setattr(bootstrap, "_tmux_running", lambda _root, _session: False)
    monkeypatch.setattr(bootstrap, "_install_crontab", lambda *_args: None)
    monkeypatch.setattr(bootstrap, "_write_active", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        bootstrap,
        "_run",
        lambda args, **_kwargs: calls.append(list(args))
        or subprocess.CompletedProcess(args, 0),
    )

    bootstrap.start(tmp_path, assume_yes=True, non_interactive=True)

    assert len(calls) == 1
    assert calls[0][:3] == ["tmux", "new-session", "-d"]
    assert "preflight" not in calls[0]


def test_qwen_configuration_merges_without_overwriting_gemini(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = tmp_path / ".secrets.env"
    secret.write_text(
        "GEMINI_API_KEY=gemini-key\n"
        "GEMINI_BASE_URL=https://gemini.example/v1beta\n"
        "GEMINI_MODEL=gemini-2.5-flash\n"
        "HF_TOKEN=hf-existing\n",
        encoding="utf-8",
    )
    hidden = iter(["qwen-key"])
    monkeypatch.setattr(bootstrap.getpass, "getpass", lambda _prompt: next(hidden))
    monkeypatch.setattr(
        "builtins.input", lambda _prompt: "https://qwen.example/v1"
    )

    bootstrap.configure_secrets(tmp_path, experiment="qwen-tool-knowledge")

    values = bootstrap._parse_env_file(secret)
    assert values["GEMINI_API_KEY"] == "gemini-key"
    assert values["QWEN_API_KEY"] == "qwen-key"
    assert values["QWEN_BASE_URL"] == "https://qwen.example/v1"
    assert values["QWEN_MODEL"] == "qwen3.5-flash"
    assert values["HF_TOKEN"] == "hf-existing"
    assert stat.S_IMODE(secret.stat().st_mode) == 0o600


def test_experiments_have_isolated_state_session_cron_and_results(tmp_path: Path) -> None:
    gemini = "gemini-important"
    qwen = "qwen-tool-knowledge"
    assert bootstrap._active_path(tmp_path, gemini) != bootstrap._active_path(
        tmp_path, qwen
    )
    assert bootstrap._session_name(tmp_path, gemini) != bootstrap._session_name(
        tmp_path, qwen
    )
    assert bootstrap._cron_marker(tmp_path, gemini) != bootstrap._cron_marker(
        tmp_path, qwen
    )
    qwen_run = bootstrap._new_run_dir(
        tmp_path, mode="acceptance", experiment=qwen
    )
    assert qwen_run.parent == (tmp_path / "results" / qwen).resolve()


@pytest.mark.parametrize(
    ("answer", "expected"),
    [("", "gemini-important"), ("1", "gemini-important"), ("2", "qwen-tool-knowledge"),
     ("3", "gemini-tool-knowledge")],
)
def test_interactive_experiment_menu(
    answer: str, expected: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("builtins.input", lambda _prompt: answer)
    assert bootstrap._choose_experiment() == expected


def test_qwen_commands_propagate_experiment_and_eight_workers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    args = bootstrap._cli_args(
        "run", tmp_path, experiment="qwen-tool-knowledge"
    )
    assert args[-2:] == ["--experiment", "qwen-tool-knowledge"]
    command = bootstrap._tmux_shell_command(
        tmp_path, acceptance=False, experiment="qwen-tool-knowledge"
    )
    assert "--experiment qwen-tool-knowledge" in command
    secret = tmp_path / ".secrets.env"
    secret.write_text(
        "QWEN_API_KEY=x\nQWEN_BASE_URL=https://qwen.example/v1\n",
        encoding="utf-8",
    )
    env = bootstrap.runtime_env(tmp_path, experiment="qwen-tool-knowledge")
    assert env["AS_ALL_WORKERS"] == "8"
    assert env["AS_ALL_EXPERIMENT"] == "qwen-tool-knowledge"
    assert env["QWEN_MODEL"] == "qwen3.5-flash"


def test_status_can_inspect_but_start_does_not_resume_legacy_gemini_state(
    tmp_path: Path,
) -> None:
    legacy = bootstrap._active_path(tmp_path, legacy=True)
    legacy.parent.mkdir(parents=True)
    legacy.write_text(json.dumps({"run_dir": "/legacy"}), encoding="utf-8")
    assert bootstrap._read_active(tmp_path) is None
    assert bootstrap._read_active(tmp_path, include_legacy=True) == {
        "run_dir": "/legacy"
    }


def test_profile_state_cannot_resume_a_different_experiment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = bootstrap._active_path(tmp_path, "qwen-tool-knowledge")
    state.parent.mkdir(parents=True)
    state.write_text(
        json.dumps(
            {
                "run_dir": str(tmp_path / "results" / "bad"),
                "experiment": "gemini-important",
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / ".secrets.env").write_text(
        "QWEN_API_KEY=x\nQWEN_BASE_URL=https://qwen.example/v1\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(bootstrap, "_require_program", lambda *_args: None)
    monkeypatch.setattr(bootstrap, "_sync", lambda _root: None)
    with pytest.raises(bootstrap.BootstrapError, match="belongs to gemini-important"):
        bootstrap.start(
            tmp_path,
            experiment="qwen-tool-knowledge",
            assume_yes=True,
            non_interactive=True,
        )
