"""Safe Linux bootstrap for the public AS-all experiment package."""

from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from typing import Mapping, Sequence


MODEL = "gemini-2.5-flash"
DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
TOTAL_CASES = 11_506
METHODS = 11
DEFAULT_WORKERS = 4


class BootstrapError(RuntimeError):
    """A user-actionable bootstrap failure."""


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _run(
    args: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str] | None = None,
    check: bool = True,
    capture_output: bool = False,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args),
        cwd=cwd,
        env=dict(env) if env is not None else None,
        check=check,
        text=True,
        capture_output=capture_output,
    )


def _require_program(name: str, help_text: str) -> None:
    if shutil.which(name) is None:
        raise BootstrapError(f"{name} is required. {help_text}")


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise BootstrapError(f"Invalid entry in {path} at line {line_number}")
        key, value = line.split("=", 1)
        if not key or not key.replace("_", "").isalnum():
            raise BootstrapError(f"Invalid variable name in {path} at line {line_number}")
        values[key] = value
    return values


def _write_secrets(path: Path, values: Mapping[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(path, flags, 0o600)
    try:
        os.fchmod(fd, 0o600)
        content = "".join(f"{key}={value}\n" for key, value in values.items())
        os.write(fd, content.encode("utf-8"))
    finally:
        os.close(fd)


def configure_secrets(root: Path, *, non_interactive: bool = False) -> Path:
    path = root / ".secrets.env"
    current = _parse_env_file(path)
    api_key = current.get("GEMINI_API_KEY", "")
    base_url = current.get("GEMINI_BASE_URL", DEFAULT_BASE_URL)
    hf_token = current.get("HF_TOKEN", "")

    if not api_key:
        if non_interactive:
            raise BootstrapError("GEMINI_API_KEY is missing from .secrets.env")
        api_key = getpass.getpass("Gemini API key (hidden): ").strip()
        if not api_key:
            raise BootstrapError("Gemini API key cannot be empty")
        entered_base = input(f"Gemini API base [{DEFAULT_BASE_URL}]: ").strip()
        base_url = entered_base or DEFAULT_BASE_URL
        hf_token = getpass.getpass(
            "Hugging Face token (optional, hidden; press Enter to skip): "
        ).strip()

    _write_secrets(
        path,
        {
            "GEMINI_API_KEY": api_key,
            "GEMINI_BASE_URL": base_url,
            "GEMINI_MODEL": MODEL,
            **({"HF_TOKEN": hf_token} if hf_token else {}),
        },
    )
    return path


def runtime_env(root: Path) -> dict[str, str]:
    env = dict(os.environ)
    env.update(_parse_env_file(root / ".secrets.env"))
    env["GEMINI_MODEL"] = MODEL
    env["AS_ALL_WORKERS"] = str(DEFAULT_WORKERS)
    return env


def _active_path(root: Path) -> Path:
    return root / ".state" / "active_run.json"


def _session_name(root: Path) -> str:
    digest = hashlib.sha256(str(root.resolve()).encode("utf-8")).hexdigest()[:10]
    return f"as-all-{digest}"


def _tmux_running(root: Path, session: str) -> bool:
    result = _run(
        ["tmux", "has-session", "-t", session],
        cwd=root,
        check=False,
        capture_output=True,
    )
    return result.returncode == 0


def _read_active(root: Path) -> dict[str, str] | None:
    path = _active_path(root)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise BootstrapError(f"Cannot read active-run state: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("run_dir"), str):
        raise BootstrapError("Active-run state has an invalid format")
    return data


def _write_active(root: Path, *, run_dir: Path, session: str, mode: str) -> None:
    path = _active_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_dir": str(run_dir.resolve()),
        "session": session,
        "mode": mode,
        "model": MODEL,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _new_run_dir(root: Path, *, mode: str) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    candidate = root / "results" / f"{mode}-{stamp}"
    counter = 1
    while candidate.exists():
        candidate = root / "results" / f"{mode}-{stamp}-{counter}"
        counter += 1
    candidate.mkdir(parents=True)
    return candidate.resolve()


def _cli_args(command: str, run_dir: Path, *, acceptance: bool = False) -> list[str]:
    args = [
        "uv",
        "run",
        "--frozen",
        "--python",
        "3.12",
        "python",
        "-m",
        "as_all.cli",
        command,
    ]
    args.extend(["--run-dir", str(run_dir.resolve())])
    if acceptance:
        args.append("--acceptance")
    return args


def _sync(root: Path) -> None:
    _run(["uv", "sync", "--frozen", "--python", "3.12"], cwd=root)


def _cron_marker(root: Path) -> str:
    digest = hashlib.sha256(str(root.resolve()).encode("utf-8")).hexdigest()[:12]
    return f"AS_ALL_READONLY_WATCHDOG_{digest}"


def _tmux_shell_command(run_dir: Path, *, acceptance: bool) -> str:
    args = [
        "uv",
        "run",
        "--frozen",
        "--python",
        "3.12",
        "python",
        "-m",
        "as_all.bootstrap",
        "_run-cli",
        "--run-dir",
        str(run_dir.resolve()),
    ]
    if acceptance:
        args.append("--acceptance")
    return shlex.join(args)


def _install_crontab(root: Path, run_dir: Path) -> None:
    """Install cron using stdin; split out for deterministic tests."""
    marker = _cron_marker(root)
    listed = _run(["crontab", "-l"], cwd=root, check=False, capture_output=True)
    if listed.returncode not in (0, 1):
        raise BootstrapError(f"Cannot read the current crontab: {listed.stderr.strip()}")
    existing = listed.stdout if listed.returncode == 0 else ""
    state_dir = root / ".state"
    state_dir.mkdir(parents=True, exist_ok=True)
    backup = state_dir / "crontab.before-watchdog.txt"
    if not backup.exists():
        backup.write_text(existing, encoding="utf-8")

    lines = existing.splitlines()
    kept: list[str] = []
    index = 0
    while index < len(lines):
        if lines[index] == f"# {marker}":
            index += 2
            continue
        kept.append(lines[index])
        index += 1

    uv = shutil.which("uv")
    if uv is None:
        raise BootstrapError("uv disappeared before watchdog installation")
    shell_command = " ".join(
        [
            "cd",
            shlex.quote(str(root.resolve())),
            "&&",
            shlex.quote(uv),
            "run",
            "--frozen",
            "--python",
            "3.12",
            "python",
            "-m",
            "as_all.cli",
            "watchdog",
            "--run-dir",
            shlex.quote(str(run_dir.resolve())),
        ]
    )
    kept.extend([f"# {marker}", f"*/10 * * * * {shell_command}"])
    content = "\n".join(kept).rstrip() + "\n"
    subprocess.run(
        ["crontab", "-"],
        cwd=root,
        input=content,
        text=True,
        check=True,
    )


def _confirm_full_run(*, assume_yes: bool) -> None:
    if assume_yes:
        return
    print(
        f"This will run {TOTAL_CASES:,} paid Gemini cases "
        f"({METHODS} methods; 97 Clean + 949 Attack per method)."
    )
    answer = input('Type "RUN 11506" to start the paid full experiment: ').strip()
    if answer != "RUN 11506":
        raise BootstrapError("Full experiment was not confirmed; nothing was started")


def _remove_watchdog(root: Path) -> None:
    listed = _run(["crontab", "-l"], cwd=root, check=False, capture_output=True)
    if listed.returncode == 1:
        return
    if listed.returncode:
        raise BootstrapError("Cannot read crontab for watchdog retirement")
    lines = listed.stdout.splitlines()
    kept = []
    index = 0
    while index < len(lines):
        if lines[index] == f"# {_cron_marker(root)}":
            index += 2
        else:
            kept.append(lines[index])
            index += 1
    if kept != lines:
        subprocess.run(["crontab", "-"], cwd=root, input="\n".join(kept) + "\n", text=True, check=True)


def start(
    root: Path,
    *,
    assume_yes: bool = False,
    non_interactive: bool = False,
    acceptance: bool = False,
) -> Path:
    _require_program("uv", "See https://docs.astral.sh/uv/getting-started/installation/")
    _require_program("tmux", "Install it with your Linux package manager.")
    _require_program("crontab", "Install your distribution's cron package.")
    configure_secrets(root, non_interactive=non_interactive)
    _sync(root)

    session = _session_name(root)
    active = _read_active(root)
    requested_mode = "acceptance" if acceptance else "full"
    is_new = active is None
    if active is not None:
        run_dir = Path(active["run_dir"])
        if _tmux_running(root, session):
            active_mode = active.get("mode", "full")
            if active_mode != requested_mode:
                raise BootstrapError(
                    f"A {active_mode} run is already active in tmux session {session}"
                )
            _install_crontab(root, run_dir)
            print(f"Experiment is already running in tmux session: {session}")
            print(f"Results: {run_dir.resolve()}")
            return run_dir.resolve()
        if active.get("mode", "full") != requested_mode:
            run_dir = _new_run_dir(root, mode=requested_mode)
            is_new = True
        elif not run_dir.is_dir():
            raise BootstrapError(f"Active result directory does not exist: {run_dir}")
    else:
        run_dir = _new_run_dir(root, mode=requested_mode)

    if is_new:
        env = runtime_env(root)
        _run(_cli_args("preflight", run_dir, acceptance=acceptance), cwd=root, env=env)
    if not acceptance:
        _confirm_full_run(assume_yes=assume_yes)

    launcher = [
        "tmux",
        "new-session",
        "-d",
        "-s",
        session,
        "-c",
        str(root.resolve()),
        _tmux_shell_command(run_dir, acceptance=acceptance),
    ]
    _run(launcher, cwd=root)
    _write_active(root, run_dir=run_dir, session=session, mode=requested_mode)
    _install_crontab(root, run_dir)

    print(f"Started tmux session: {session}")
    print(f"Results: {run_dir.resolve()}")
    print("Status: bash run.sh status")
    print(f"Attach: tmux attach -t {session}")
    return run_dir.resolve()


def show_status(root: Path) -> int:
    active = _read_active(root)
    if active is None:
        print("No AS-all run has been started from this checkout.")
        return 1
    run_dir = Path(active["run_dir"]).resolve()
    print(f"Results: {run_dir}")
    result = _run(_cli_args("status", run_dir), cwd=root, env=runtime_env(root), check=False)
    return result.returncode


def _run_cli(root: Path, run_dir: Path, *, acceptance: bool) -> int:
    env = runtime_env(root)
    result = _run(
        _cli_args("run", run_dir, acceptance=acceptance),
        cwd=root,
        env=env,
        check=False,
    )
    completion = run_dir / "completion.json"
    if completion.exists() and json.loads(completion.read_text()).get("all_terminal"):
        _remove_watchdog(root)
    return result.returncode


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    start_parser = subparsers.add_parser("start", help="configure and start the experiment")
    start_parser.add_argument("--yes", action="store_true", help="accept the full-run charge warning")
    start_parser.add_argument("--non-interactive", action="store_true")
    start_parser.add_argument("--acceptance", action="store_true", help="run the 22-case acceptance set")
    subparsers.add_parser("status", help="show the active run status")
    internal = subparsers.add_parser("_run-cli", help=argparse.SUPPRESS)
    internal.add_argument("--run-dir", type=Path, required=True)
    internal.add_argument("--acceptance", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = repo_root()
    try:
        if args.command == "start":
            start(
                root,
                assume_yes=args.yes,
                non_interactive=args.non_interactive,
                acceptance=args.acceptance,
            )
            return 0
        if args.command == "status":
            return show_status(root)
        if args.command == "_run-cli":
            return _run_cli(root, args.run_dir, acceptance=args.acceptance)
    except (BootstrapError, subprocess.CalledProcessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    raise AssertionError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
