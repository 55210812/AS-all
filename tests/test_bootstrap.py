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


def test_start_does_not_duplicate_live_tmux_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run_dir = tmp_path / "results" / "existing"
    run_dir.mkdir(parents=True)
    state = tmp_path / ".state" / "active_run.json"
    state.parent.mkdir()
    state.write_text(json.dumps({"run_dir": str(run_dir)}), encoding="utf-8")
    (tmp_path / ".secrets.env").write_text("GEMINI_API_KEY=x\n", encoding="utf-8")
    os.chmod(tmp_path / ".secrets.env", 0o600)
    calls: list[list[str]] = []

    monkeypatch.setattr(bootstrap, "_require_program", lambda *_args: None)
    monkeypatch.setattr(bootstrap, "_sync", lambda _root: None)
    monkeypatch.setattr(bootstrap, "_tmux_running", lambda _root, _session: True)
    monkeypatch.setattr(bootstrap, "_install_crontab", lambda _root, _run_dir: None)
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
    assert (root / ".state" / "crontab.before-watchdog.txt").read_text() == (
        "5 * * * * /usr/bin/backup\n"
    )


def test_cli_command_uses_argument_vector_for_hostile_run_path(tmp_path: Path) -> None:
    run_dir = tmp_path / "a; touch injected"
    args = bootstrap._cli_args("run", run_dir)
    assert args[-2:] == ["--run-dir", str(run_dir.resolve())]
    assert len([part for part in args if "touch injected" in part]) == 1


def test_tmux_command_quotes_hostile_path_and_contains_no_secret(tmp_path: Path) -> None:
    run_dir = tmp_path / "run; touch injected"
    command = bootstrap._tmux_shell_command(run_dir, acceptance=False)
    split_command = shlex.split(command)
    assert split_command[-2:] == ["--run-dir", str(run_dir.resolve())]
    assert "GEMINI_API_KEY" not in command


def test_noninteractive_requires_secret(tmp_path: Path) -> None:
    with pytest.raises(bootstrap.BootstrapError, match="GEMINI_API_KEY"):
        bootstrap.configure_secrets(tmp_path, non_interactive=True)


def test_stopped_existing_run_resumes_without_repeating_preflight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = tmp_path / "results" / "full-existing"
    run_dir.mkdir(parents=True)
    state = tmp_path / ".state" / "active_run.json"
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
    monkeypatch.setattr(bootstrap, "_install_crontab", lambda _root, _run_dir: None)
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
