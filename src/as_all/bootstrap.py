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

from .experiments import DEFAULT_EXPERIMENT, WORKERS, Experiment, get_experiment

TOTAL_CASES = 11_506
METHODS = 11
DEFAULT_WORKERS = WORKERS


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


def _model_env(profile: Experiment) -> str:
    return f"{profile.provider.upper()}_MODEL"


def configure_secrets(
    root: Path,
    *,
    experiment: str = DEFAULT_EXPERIMENT,
    non_interactive: bool = False,
) -> Path:
    profile = get_experiment(experiment)
    path = root / ".secrets.env"
    current = _parse_env_file(path)
    api_key = current.get(profile.key_env, "")
    base_url = current.get(profile.base_env, profile.default_base)
    hf_token = current.get("HF_TOKEN", "")

    if not api_key or not base_url:
        if non_interactive:
            missing = profile.key_env if not api_key else profile.base_env
            raise BootstrapError(f"{missing} is missing from .secrets.env")
        label = "Gemini" if profile.provider == "gemini" else "Qwen"
        if not api_key:
            api_key = getpass.getpass(f"{label} API key (hidden): ").strip()
            if not api_key:
                raise BootstrapError(f"{label} API key cannot be empty")
        if not base_url:
            base_url = input(f"{label} API base (required): ").strip()
            if not base_url:
                raise BootstrapError(f"{label} API base cannot be empty")
        elif profile.default_base:
            entered_base = input(f"{label} API base [{profile.default_base}]: ").strip()
            base_url = entered_base or profile.default_base
        if not hf_token:
            hf_token = getpass.getpass(
                "Hugging Face token (optional, hidden; press Enter to skip): "
            ).strip()

    merged = dict(current)
    merged.update(
        {
            profile.key_env: api_key,
            profile.base_env: base_url,
            _model_env(profile): profile.model,
        }
    )
    if hf_token:
        merged["HF_TOKEN"] = hf_token
    _write_secrets(
        path,
        merged,
    )
    return path


def runtime_env(
    root: Path, *, experiment: str = DEFAULT_EXPERIMENT
) -> dict[str, str]:
    profile = get_experiment(experiment)
    env = dict(os.environ)
    env.update(_parse_env_file(root / ".secrets.env"))
    env[_model_env(profile)] = profile.model
    env["AS_ALL_EXPERIMENT"] = profile.id
    env["AS_ALL_WORKERS"] = str(DEFAULT_WORKERS)
    return env


def _active_path(
    root: Path, experiment: str = DEFAULT_EXPERIMENT, *, legacy: bool = False
) -> Path:
    name = "active_run.json" if legacy else f"active_run.{experiment}.json"
    return root / ".state" / name


def _session_name(root: Path, experiment: str = DEFAULT_EXPERIMENT) -> str:
    identity = f"{root.resolve()}\0{experiment}"
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:10]
    return f"as-all-{experiment}-{digest}"


def _tmux_running(root: Path, session: str) -> bool:
    result = _run(
        ["tmux", "has-session", "-t", session],
        cwd=root,
        check=False,
        capture_output=True,
    )
    return result.returncode == 0


def _read_active(
    root: Path,
    experiment: str = DEFAULT_EXPERIMENT,
    *,
    include_legacy: bool = False,
) -> dict[str, str] | None:
    path = _active_path(root, experiment)
    if not path.exists() and include_legacy and experiment == DEFAULT_EXPERIMENT:
        path = _active_path(root, legacy=True)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise BootstrapError(f"Cannot read active-run state: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("run_dir"), str):
        raise BootstrapError("Active-run state has an invalid format")
    return data


def _write_active(
    root: Path,
    *,
    run_dir: Path,
    session: str,
    mode: str,
    experiment: str = DEFAULT_EXPERIMENT,
) -> None:
    profile = get_experiment(experiment)
    path = _active_path(root, experiment)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_dir": str(run_dir.resolve()),
        "session": session,
        "mode": mode,
        "experiment": profile.id,
        "model": profile.model,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _new_run_dir(
    root: Path, *, mode: str, experiment: str = DEFAULT_EXPERIMENT
) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = root / "results" / experiment
    candidate = base / f"{mode}-{stamp}"
    counter = 1
    while candidate.exists():
        candidate = base / f"{mode}-{stamp}-{counter}"
        counter += 1
    candidate.mkdir(parents=True)
    return candidate.resolve()


def _cli_args(
    command: str,
    run_dir: Path,
    *,
    acceptance: bool = False,
    experiment: str = DEFAULT_EXPERIMENT,
) -> list[str]:
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
    args.extend(["--experiment", experiment])
    if os.environ.get("AS_ALL_PYTHON"):
        args = [
            os.environ["AS_ALL_PYTHON"], "-m", "as_all.cli", command,
            "--run-dir", str(run_dir.resolve()), "--experiment", experiment,
        ]
    if acceptance:
        args.append("--acceptance")
    return args


def _sync(root: Path) -> None:
    if os.environ.get("AS_ALL_PYTHON"):
        _run([os.environ["AS_ALL_PYTHON"], "-c",
              "import sys,httpx,torch,transformers,openai,pydantic; assert sys.version_info[:2] == (3,12), 'Python3.12 required'"], cwd=root)
        return
    _run(["uv", "sync", "--frozen", "--python", "3.12"], cwd=root)


def _cron_marker(root: Path, experiment: str = DEFAULT_EXPERIMENT) -> str:
    identity = f"{root.resolve()}\0{experiment}"
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]
    return f"AS_ALL_READONLY_WATCHDOG_{digest}"


def _tmux_shell_command(
    run_dir: Path,
    *,
    acceptance: bool,
    experiment: str = DEFAULT_EXPERIMENT,
) -> str:
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
        "--experiment",
        experiment,
    ]
    if acceptance:
        args.append("--acceptance")
    if os.environ.get("AS_ALL_PYTHON"):
        args = [
            os.environ["AS_ALL_PYTHON"], "-m", "as_all.bootstrap", "_run-cli",
            "--run-dir", str(run_dir.resolve()), "--experiment", experiment,
        ]
        if acceptance:
            args.append("--acceptance")
        return " ".join([f"AS_ALL_PYTHON={shlex.quote(os.environ['AS_ALL_PYTHON'])}",
                         f"PYTHONPATH={shlex.quote(os.environ.get('PYTHONPATH', ''))}", shlex.join(args)]) + " > " + shlex.quote(str(run_dir / "run.log")) + " 2>&1"
    return shlex.join(args) + " > " + shlex.quote(str(run_dir / "run.log")) + " 2>&1"


def _install_crontab(
    root: Path, run_dir: Path, experiment: str = DEFAULT_EXPERIMENT
) -> None:
    """Install cron using stdin; split out for deterministic tests."""
    marker = _cron_marker(root, experiment)
    listed = _run(["crontab", "-l"], cwd=root, check=False, capture_output=True)
    if listed.returncode not in (0, 1):
        raise BootstrapError(f"Cannot read the current crontab: {listed.stderr.strip()}")
    existing = listed.stdout if listed.returncode == 0 else ""
    state_dir = root / ".state"
    state_dir.mkdir(parents=True, exist_ok=True)
    backup = state_dir / f"crontab.before-watchdog.{experiment}.txt"
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
    if uv is None and not os.environ.get("AS_ALL_PYTHON"):
        raise BootstrapError("uv disappeared before watchdog installation")
    environment = ""
    if os.environ.get("AS_ALL_PYTHON"):
        environment = f"AS_ALL_PYTHON={shlex.quote(os.environ['AS_ALL_PYTHON'])} PYTHONPATH={shlex.quote(os.environ.get('PYTHONPATH', ''))} "
    command = _cli_args("watchdog", run_dir, experiment=experiment)
    if not os.environ.get("AS_ALL_PYTHON"):
        command[0] = uv
    shell_command = f"cd {shlex.quote(str(root.resolve()))} && {environment}{shlex.join(command)}"
    kept.extend([f"# {marker}", f"*/10 * * * * {shell_command}"])
    content = "\n".join(kept).rstrip() + "\n"
    subprocess.run(
        ["crontab", "-"],
        cwd=root,
        input=content,
        text=True,
        check=True,
    )


def _confirm_full_run(
    *, assume_yes: bool, experiment: str = DEFAULT_EXPERIMENT
) -> None:
    if assume_yes:
        return
    profile = get_experiment(experiment)
    print(
        f"This will run {TOTAL_CASES:,} paid {profile.model} cases for "
        f"{profile.attack} ({METHODS} methods; 97 Clean + 949 Attack per method; "
        f"{DEFAULT_WORKERS} case workers)."
    )
    answer = input('Type "RUN 11506" to start the paid full experiment: ').strip()
    if answer != "RUN 11506":
        raise BootstrapError("Full experiment was not confirmed; nothing was started")


def _remove_watchdog(root: Path, experiment: str = DEFAULT_EXPERIMENT) -> None:
    listed = _run(["crontab", "-l"], cwd=root, check=False, capture_output=True)
    if listed.returncode == 1:
        return
    if listed.returncode:
        raise BootstrapError("Cannot read crontab for watchdog retirement")
    lines = listed.stdout.splitlines()
    kept = []
    index = 0
    while index < len(lines):
        if lines[index] == f"# {_cron_marker(root, experiment)}":
            index += 2
        else:
            kept.append(lines[index])
            index += 1
    if kept != lines:
        subprocess.run(["crontab", "-"], cwd=root, input="\n".join(kept) + "\n", text=True, check=True)


def start(
    root: Path,
    *,
    experiment: str = DEFAULT_EXPERIMENT,
    assume_yes: bool = False,
    non_interactive: bool = False,
    acceptance: bool = False,
) -> Path:
    profile = get_experiment(experiment)
    if not os.environ.get("AS_ALL_PYTHON"):
        _require_program("uv", "See https://docs.astral.sh/uv/getting-started/installation/")
    _require_program("tmux", "Install it with your Linux package manager.")
    _require_program("crontab", "Install your distribution's cron package.")
    configure_secrets(
        root, experiment=profile.id, non_interactive=non_interactive
    )
    _sync(root)

    session = _session_name(root, profile.id)
    active = _read_active(root, profile.id)
    requested_mode = "acceptance" if acceptance else "full"
    is_new = active is None
    if active is not None:
        active_experiment = active.get("experiment")
        if active_experiment not in (None, profile.id):
            raise BootstrapError(
                f"Active-run state belongs to {active_experiment}, not {profile.id}"
            )
        run_dir = Path(active["run_dir"])
        if _tmux_running(root, session):
            active_mode = active.get("mode", "full")
            if active_mode != requested_mode:
                raise BootstrapError(
                    f"A {active_mode} run is already active in tmux session {session}"
                )
            _install_crontab(root, run_dir, profile.id)
            print(f"Experiment is already running in tmux session: {session}")
            print(f"Results: {run_dir.resolve()}")
            return run_dir.resolve()
        if active.get("mode", "full") != requested_mode:
            run_dir = _new_run_dir(
                root, mode=requested_mode, experiment=profile.id
            )
            is_new = True
        elif not run_dir.is_dir():
            raise BootstrapError(f"Active result directory does not exist: {run_dir}")
    else:
        run_dir = _new_run_dir(root, mode=requested_mode, experiment=profile.id)

    if is_new:
        env = runtime_env(root, experiment=profile.id)
        _run(
            _cli_args(
                "preflight", run_dir, acceptance=acceptance, experiment=profile.id
            ),
            cwd=root,
            env=env,
        )
    if not acceptance:
        _confirm_full_run(assume_yes=assume_yes, experiment=profile.id)

    launcher = [
        "tmux",
        "new-session",
        "-d",
        "-s",
        session,
        "-c",
        str(root.resolve()),
        _tmux_shell_command(
            run_dir, acceptance=acceptance, experiment=profile.id
        ),
    ]
    _run(launcher, cwd=root)
    _write_active(
        root,
        run_dir=run_dir,
        session=session,
        mode=requested_mode,
        experiment=profile.id,
    )
    _install_crontab(root, run_dir, profile.id)

    print(f"Started tmux session: {session}")
    print(f"Experiment: {profile.id} ({profile.model}; {profile.attack})")
    print(f"Workers: {DEFAULT_WORKERS}")
    print(f"Results: {run_dir.resolve()}")
    print("Status: bash run.sh status")
    print(f"Attach: tmux attach -t {session}")
    return run_dir.resolve()


def show_status(root: Path, experiment: str = DEFAULT_EXPERIMENT) -> int:
    profile = get_experiment(experiment)
    active = _read_active(root, profile.id, include_legacy=True)
    if active is None:
        print("No AS-all run has been started from this checkout.")
        return 1
    run_dir = Path(active["run_dir"]).resolve()
    print(f"Results: {run_dir}")
    result = _run(
        _cli_args("status", run_dir, experiment=profile.id),
        cwd=root,
        env=runtime_env(root, experiment=profile.id),
        check=False,
    )
    return result.returncode


def _run_cli(
    root: Path,
    run_dir: Path,
    *,
    acceptance: bool,
    experiment: str = DEFAULT_EXPERIMENT,
) -> int:
    profile = get_experiment(experiment)
    env = runtime_env(root, experiment=profile.id)
    result = _run(
        _cli_args(
            "run", run_dir, acceptance=acceptance, experiment=profile.id
        ),
        cwd=root,
        env=env,
        check=False,
    )
    completion = run_dir / "completion.json"
    if completion.exists() and json.loads(completion.read_text()).get("all_terminal"):
        _remove_watchdog(root, profile.id)
    return result.returncode


def _choose_experiment() -> str:
    print("Choose an experiment:")
    print("  1. Gemini + important_instructions (default)")
    print("  2. Qwen + tool_knowledge")
    answer = input("Selection [1]: ").strip()
    if answer in ("", "1"):
        return DEFAULT_EXPERIMENT
    if answer == "2":
        return "qwen-tool-knowledge"
    raise BootstrapError("Experiment selection must be 1 or 2")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    start_parser = subparsers.add_parser("start", help="configure and start the experiment")
    start_parser.add_argument("--yes", action="store_true", help="accept the full-run charge warning")
    start_parser.add_argument("--non-interactive", action="store_true")
    start_parser.add_argument("--acceptance", action="store_true", help="run the 22-case acceptance set")
    start_parser.add_argument("--experiment", choices=("gemini-important", "qwen-tool-knowledge"))
    status_parser = subparsers.add_parser("status", help="show the active run status")
    status_parser.add_argument(
        "--experiment", choices=("gemini-important", "qwen-tool-knowledge"),
        default=DEFAULT_EXPERIMENT,
    )
    internal = subparsers.add_parser("_run-cli", help=argparse.SUPPRESS)
    internal.add_argument("--run-dir", type=Path, required=True)
    internal.add_argument("--acceptance", action="store_true")
    internal.add_argument(
        "--experiment", choices=("gemini-important", "qwen-tool-knowledge"),
        default=DEFAULT_EXPERIMENT,
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = repo_root()
    try:
        if args.command == "start":
            experiment = args.experiment
            if experiment is None:
                experiment = (
                    DEFAULT_EXPERIMENT
                    if args.non_interactive
                    else _choose_experiment()
                )
            start(
                root,
                experiment=experiment,
                assume_yes=args.yes,
                non_interactive=args.non_interactive,
                acceptance=args.acceptance,
            )
            return 0
        if args.command == "status":
            return show_status(root, experiment=args.experiment)
        if args.command == "_run-cli":
            return _run_cli(
                root,
                args.run_dir,
                acceptance=args.acceptance,
                experiment=args.experiment,
            )
    except (BootstrapError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    raise AssertionError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
