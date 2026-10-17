"""Portable case lifecycle. A claim is an execution boundary, not a retry ticket."""
import argparse
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from contextlib import contextmanager
import fcntl
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import shutil
import time

from as_all.methods import METHODS, ROOT
from as_all.experiments import DEFAULT_EXPERIMENT, WORKERS, EXPERIMENTS, get_experiment


def read(path):
    return json.loads(Path(path).read_text())


def atomic(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + f".{os.getpid()}.tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str) + "\n")
    temp.replace(path)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_hashes():
    hashes = {str(p.relative_to(ROOT)): sha(p) for folder in ("src", "vendor", "reference", "data", "tools")
            for p in sorted((ROOT / folder).rglob("*")) if p.is_file()
            and "__pycache__" not in p.parts and not p.name.endswith((".pyc", ".egg-info"))}
    for name in ("pyproject.toml", "uv.lock", "run.sh", "feedback.sh", ".python-version"):
        hashes[name] = sha(ROOT / name)
    return hashes


def registry(acceptance=False, experiment=DEFAULT_EXPERIMENT):
    profile = get_experiment(experiment)
    from agentdojo.task_suite.load_suites import get_suite
    result = []
    for domain in ("slack", "travel", "workspace", "banking"):
        suite = get_suite("v1.2.2", domain)
        for task in suite.user_tasks:
            for injection in (None, *suite.injection_tasks):
                result.append({"domain": domain, "task": task, "injection": injection,
                               "case_id": f"{domain}/{task}" + (f"+{injection}" if injection else " clean")})
    assert len(result) == 1046 and sum(c["injection"] is None for c in result) == 97
    if acceptance:
        # Fixed two cases shared by all methods, no outcome-based selection.
        result = [c for c in result if c["domain"] == "slack" and c["task"] == "user_task_0"
                  and c["injection"] in (None, "injection_task_1")]
    return [{**c, "method": method, "experiment_id": profile.id,
             "id": hashlib.sha256(f"{profile.id}:{method}:{c['case_id']}".encode()).hexdigest()[:24]}
            for method in METHODS for c in result]


def channel_fingerprint(profile):
    return hashlib.sha256((os.environ.get(profile.base_env, profile.default_base) + "\0" +
                           os.environ.get(profile.key_env, "")).encode()).hexdigest()


def preflight(run_dir, acceptance=False, download=True, experiment=DEFAULT_EXPERIMENT):
    profile = get_experiment(experiment)
    manifest = {"experiment_id": profile.id, "provider": profile.provider, "model": profile.model,
                "benchmark": "v1.2.2", "attack": profile.attack,
                "acceptance_only": acceptance, "methods": METHODS, "cases": registry(acceptance, profile.id),
                "workers": WORKERS, "case_retries": 0, "manager_restores": 0,
                "agent_thinking_budget": -1, "defense_thinking_budget": 0, "temperature": 0,
                "source_hashes": source_hashes()}
    key = os.environ.get(profile.key_env)
    if key:
        manifest["channel_fingerprint"] = channel_fingerprint(profile)
    path = run_dir / "manifest.json"
    tasks = read(ROOT / "data/task_texts97.json")
    frames = read(ROOT / "data/manual_frames97.json")
    attacks = read(ROOT / "data" / profile.attacks_file)
    if len(tasks) != 97 or set(tasks) != set(frames) or len(attacks) != 949:
        raise RuntimeError("Frozen input coverage mismatch")
    from agentdojo.task_suite.load_suites import get_suite
    for key, prompt in tasks.items():
        domain, task = key.split("/")
        if get_suite("v1.2.2", domain).get_user_task_by_id(task).PROMPT != prompt:
            raise RuntimeError("Frozen trusted task mismatch")
    expected_attacks = {c["case_id"] for c in registry(False, profile.id) if c["injection"]}
    if set(attacks) != expected_attacks:
        raise RuntimeError("Frozen attack coverage mismatch")
    manifest["input_sha256"] = {name: sha(ROOT / "data" / name) for name in
        ("task_texts97.json", "manual_frames97.json", profile.attacks_file)}
    if path.exists():
        if read(path) != json.loads(json.dumps(manifest)):
            raise RuntimeError("Frozen manifest/source mismatch; use a new run directory")
    else:
        atomic(path, manifest)
    if shutil.disk_usage(run_dir).free < 5 * 1024**3:
        raise RuntimeError("At least 5GiB free disk is required")
    if download:
        from as_all.methods import detector_path, detector_capacity
        capacity = detector_capacity()
        atomic(run_dir / "detector_capacity.json", capacity)
        detector_path()
    atomic(run_dir / "preflight.json", {"passed": True, "cases": len(manifest["cases"]),
                                       "generation_requests": 0, "domain_tool_executions": 0,
                                       "manifest_sha256": sha(path)})
    return manifest


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, TypeError, ValueError):
        return False


def check_request_boundary(run_dir):
    if (run_dir / "STOP.json").exists():
        raise RuntimeError("ExperimentStoppedBeforeRequest")
    manifest = read(run_dir / "manifest.json")
    profile = get_experiment(manifest.get("experiment_id", DEFAULT_EXPERIMENT))
    reason = None
    preparation = read(run_dir / "preflight.json")
    if preparation.get("manifest_sha256") != sha(run_dir / "manifest.json"):
        reason = "FrozenConfigurationMismatch"
    if manifest["source_hashes"] != source_hashes():
        reason = "FrozenSourceMismatch"
    fingerprint = manifest.get("channel_fingerprint")
    actual = channel_fingerprint(profile)
    if fingerprint and actual != fingerprint:
        reason = "FrozenChannelMismatch"
    if shutil.disk_usage(run_dir).free < 1024**3:
        reason = "DiskBelow1GiB"
    if reason:
        atomic(run_dir / "STOP.json", {"reason": reason})
        raise RuntimeError(reason)


def worker(case, directory):
    directory = Path(directory)
    atomic(directory / "claim.json", {"pid": os.getpid(), "started": time.time(), "id": case["id"]})
    atomic(directory / "case.json", case)
    started = time.monotonic()
    result = {**case, "utility": None, "asr": None, "error": None,
              "trace_paths": ["benchmark", "requests.jsonl", "semantic"]}
    try:
        run_dir = directory.parent.parent
        if (run_dir / "STOP.json").exists():
            raise RuntimeError("ExperimentStoppedBeforeRequest")
        if read(run_dir / "manifest.json")["source_hashes"] != source_hashes():
            atomic(run_dir / "STOP.json", {"reason": "FrozenSourceMismatch"})
            raise RuntimeError("FrozenSourceMismatch")
        if shutil.disk_usage(directory).free < 1024**3:
            raise RuntimeError("DiskBelow1GiB")
        from agentdojo.task_suite.load_suites import get_suite
        from agentdojo.benchmark import run_task_with_injection_tasks, run_task_without_injection_tasks
        from agentdojo.logging import OutputLogger
        import agentdojo.attacks  # noqa: F401 -- register frozen attacks
        from agentdojo.attacks.attack_registry import load_attack
        from as_all.methods import build
        os.environ["SAFG_TRACE_DIR"] = str(directory / "semantic")
        os.environ["SAFG_AGENT_ENABLE_THINKING"] = "true"
        suite = get_suite("v1.2.2", case["domain"])
        profile = get_experiment(case.get("experiment_id", DEFAULT_EXPERIMENT))
        pipeline = build(case["method"], directory, profile.id)
        pipeline.max_final_result_attempts = 1
        task = suite.get_user_task_by_id(case["task"])
        logdir = directory / "benchmark"
        with OutputLogger(str(logdir)):
            if case["injection"] is None:
                utility, _ = run_task_without_injection_tasks(suite, pipeline, task, logdir, True, "v1.2.2")
                result["utility"] = utility
            else:
                attack = load_attack(profile.attack, suite, pipeline)
                # Same prepared provider-specific attack for every method; no live attack generation.
                frozen_attack = read(ROOT / "data" / profile.attacks_file)[case["case_id"]]
                attack.attack = lambda *_args: frozen_attack
                utilities, attacks = run_task_with_injection_tasks(
                    suite, pipeline, task, attack, logdir, True, [case["injection"]], "v1.2.2")
                key = (case["task"], case["injection"])
                result.update(utility=utilities[key], asr=attacks[key])
        benchmarks = list(logdir.rglob("*.json"))
        if len(benchmarks) != 1:
            raise RuntimeError("Expected exactly one benchmark record")
        record = read(benchmarks[0])
        if record.get("error"):
            raise RuntimeError("BenchmarkRuntimeError: " + str(record["error"]))
        result["benchmark_sha256"] = sha(benchmarks[0])
    except Exception as exc:
        # No traceback/exception URL can disclose API credentials into public feedback.
        message = str(exc)
        for name in ("GEMINI_API_KEY", "QWEN_API_KEY", "HF_TOKEN"):
            value = os.environ.get(name)
            if value:
                message = message.replace(value, "[REDACTED]")
        result.update(error=f"{type(exc).__name__}: {message}", utility=None, asr=None)
        if any(marker in message for marker in ("FrozenSourceMismatch", "ModelIdentityMismatch", "ThinkingChannelMismatch", "DiskBelow1GiB")):
            atomic(directory.parent.parent / "STOP.json", {"reason": type(exc).__name__ + ": " + message})
    result["duration_seconds"] = time.monotonic() - started
    from as_all.report import cost
    result["costs"] = cost(directory / "requests.jsonl")
    result["source_files"] = {str(p.relative_to(directory)): sha(p) for p in directory.rglob("*")
                              if p.is_file() and p.name not in ("claim.json", "result.json")}
    atomic(directory / "result.json", result)
    return result


@contextmanager
def manager_lock(run_dir):
    with (run_dir / "manager.lock").open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def run(run_dir, acceptance=False, experiment=DEFAULT_EXPERIMENT):
    from as_all.report import report
    manifest = read(run_dir / "manifest.json")
    if manifest.get("experiment_id", DEFAULT_EXPERIMENT) != experiment:
        raise RuntimeError("FrozenExperimentMismatch")
    profile = get_experiment(experiment)
    if (manifest["workers"] != WORKERS or manifest["model"] != profile.model or manifest["attack"] != profile.attack
            or manifest["cases"] != registry(acceptance, profile.id)):
        raise RuntimeError("FrozenConfigurationMismatch")
    if manifest["acceptance_only"] != acceptance or manifest["source_hashes"] != source_hashes():
        raise RuntimeError("FrozenSourceMismatch")
    fingerprint = manifest.get("channel_fingerprint")
    if fingerprint and fingerprint != channel_fingerprint(profile):
        raise RuntimeError("FrozenChannelMismatch")
    with manager_lock(run_dir):
        atomic(run_dir / "process.json", {"pid": os.getpid(), "started": time.time(), "workers": manifest["workers"], "experiment_id": experiment})
        pending = []
        for case in manifest["cases"]:
            directory = run_dir / "cases" / case["id"]
            directory.mkdir(parents=True, exist_ok=True)
            if (directory / "result.json").exists():
                continue
            if (directory / "claim.json").exists():
                if alive(read(directory / "claim.json")["pid"]):
                    raise RuntimeError("Claimed child still alive; refusing duplicate execution")
                atomic(directory / "result.json", {**case, "utility": None, "asr": None,
                    "error": "InterruptedSingleAuthorizedAttempt", "duration_seconds": None})
            else:
                pending.append((case, str(directory)))
        try:
            last_report = 0.
            with ProcessPoolExecutor(max_workers=manifest["workers"], max_tasks_per_child=1,
                                     mp_context=multiprocessing.get_context("spawn")) as pool:
                jobs = iter(pending)
                futures = {pool.submit(worker, *args) for args in list(next(jobs, None) for _ in range(manifest["workers"])) if args}
                while futures:
                    done, futures = wait(futures, return_when=FIRST_COMPLETED)
                    for future in done:
                        future.result()
                        if not (run_dir / "STOP.json").exists():
                            args = next(jobs, None)
                            if args:
                                futures.add(pool.submit(worker, *args))
                    if time.monotonic() - last_report >= 30:
                        report(run_dir)
                        last_report = time.monotonic()
                    if shutil.disk_usage(run_dir).free < 1024**3:
                        atomic(run_dir / "STOP.json", {"reason": "DiskBelow1GiB"})
        finally:
            report(run_dir)


def status(run_dir):
    manifest = read(run_dir / "manifest.json")
    results = [read(p) for p in (run_dir / "cases").glob("*/result.json")]
    return {"terminal": len(results), "expected": len(manifest["cases"]),
            "runtime_errors": sum(bool(r.get("error")) for r in results),
            "all_terminal": len(results) == len(manifest["cases"]),
            "results": str(run_dir.resolve())}


def watchdog(run_dir):
    current = status(run_dir)
    previous = read(run_dir / "watchdog.json") if (run_dir / "watchdog.json").exists() else {}
    process = read(run_dir / "process.json") if (run_dir / "process.json").exists() else {}
    current.update(checked_at=time.time(), process_alive=alive(process.get("pid")), manager_restores=0,
                   free_bytes=shutil.disk_usage(run_dir).free,
                   source_mismatch=read(run_dir / "manifest.json")["source_hashes"] != source_hashes())
    current["ledger_bytes"] = sum(p.stat().st_size for p in (run_dir / "cases").glob("*/requests.jsonl"))
    unchanged = (current["terminal"], current["ledger_bytes"]) == (previous.get("terminal"), previous.get("ledger_bytes"))
    current["stalled_checks"] = previous.get("stalled_checks", 0) + 1 if unchanged else 0
    atomic(run_dir / "watchdog.json", current)
    return current


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("preflight", "run", "status", "watchdog", "report"))
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--acceptance", action="store_true")
    parser.add_argument("--experiment", choices=EXPERIMENTS, default=DEFAULT_EXPERIMENT)
    parser.add_argument("--skip-download", action="store_true", help="offline tests only")
    args = parser.parse_args()
    run_dir = args.run_dir.resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    if args.command == "preflight":
        data = preflight(run_dir, args.acceptance, not args.skip_download, args.experiment)
        print(json.dumps({"cases": len(data["cases"]), "generation_requests": 0}))
    elif args.command == "run":
        run(run_dir, args.acceptance, args.experiment)
    elif args.command == "report":
        from as_all.report import report
        print(report(run_dir))
    else:
        print(json.dumps(status(run_dir) if args.command == "status" else watchdog(run_dir)))


if __name__ == "__main__":
    main()
