"""Build and optionally publish a privacy-checked experiment feedback bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable, Sequence


UPSTREAM_REPOSITORY = "55210812/AS-all"
MAX_RELEASE_PART_BYTES = 45 * 1024 * 1024
MAX_BRANCH_ARCHIVE_BYTES = 10 * 1024 * 1024
REPORT_PREFIXES = ("summary", "source_hash", "runtime_error")


class FeedbackError(RuntimeError):
    """A safe, user-facing feedback export failure."""


@dataclass(frozen=True)
class CaseResult:
    path: Path
    payload: dict[str, object]

    @property
    def selected(self) -> bool:
        return self.payload.get("utility") is False or self.payload.get("asr") is True


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_case_results(run_dir: Path) -> list[CaseResult]:
    cases_dir = run_dir / "cases"
    if not cases_dir.is_dir():
        raise FeedbackError(f"Missing cases directory: {cases_dir}")
    results: list[CaseResult] = []
    for path in sorted(cases_dir.glob("*/result.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise FeedbackError(f"Invalid case result {path}: {exc}") from exc
        if not isinstance(payload, dict):
            raise FeedbackError(f"Case result must be a JSON object: {path}")
        results.append(CaseResult(path=path, payload=payload))
    if not results:
        raise FeedbackError(f"No case results found below {cases_dir}")
    return results


def _safe_relative_path(value: object, case_dir: Path) -> Path | None:
    if not isinstance(value, str) or not value:
        return None
    candidate = (case_dir / value).resolve()
    try:
        candidate.relative_to(case_dir.resolve())
    except ValueError as exc:
        raise FeedbackError(f"Trace path escapes its case directory: {value}") from exc
    return candidate


def selected_case_files(case: CaseResult) -> list[Path]:
    case_dir = case.path.parent
    files: set[Path] = {case.path}
    for path in case_dir.rglob("*"):
        relative_parts = path.relative_to(case_dir).parts
        if path.is_file() and (
            path.name.startswith("trace")
            or path.name.startswith("ledger")
            or any(part.startswith(("trace", "ledger")) for part in relative_parts)
        ):
            files.add(path)
    for key in ("trace_path", "trace_paths"):
        value = case.payload.get(key)
        values = value if isinstance(value, list) else [value]
        for item in values:
            path = _safe_relative_path(item, case_dir)
            if path is not None:
                if path.is_dir():
                    files.update(child for child in path.rglob("*") if child.is_file())
                elif path.is_file():
                    files.add(path)
                else:
                    raise FeedbackError(f"Declared trace file does not exist: {path}")
    return sorted(files)


def report_files(run_dir: Path) -> list[Path]:
    report_dir = run_dir / "report"
    if not report_dir.is_dir():
        raise FeedbackError(f"Missing report directory: {report_dir}")
    matches = [
        path
        for path in report_dir.rglob("*")
        if path.is_file() and path.name.lower().startswith(REPORT_PREFIXES)
    ]
    if not matches:
        raise FeedbackError(
            "No summary, source-hash, or runtime-error report files were found"
        )
    return sorted(matches)


def load_configured_secrets(paths: Iterable[Path]) -> list[str]:
    secrets: list[str] = []
    for path in paths:
        if not path.is_file():
            continue
        for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, value = line.split("=", 1)
            if not re.search(r"(?i)(?:key|token|password|secret)", name):
                continue
            value = value.strip().strip("'\"")
            if len(value) >= 8 and value.lower() not in {
                "changeme",
                "replace_me",
                "your_api_key",
            }:
                secrets.append(value)
    return secrets


_CREDENTIAL_PATTERNS = (
    re.compile(r"(?i)authorization\s*[:=]\s*bearer\s+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"(?i)(?:api[_-]?key|access[_-]?token)\s*['\"]?\s*[:=]\s*['\"][A-Za-z0-9._~+/=-]{20,}['\"]"),
    re.compile(r"sk-(?:proj-)?[A-Za-z0-9_-]{24,}"),
    re.compile(r"AIza[0-9A-Za-z_-]{20,}"),
    re.compile(r"gh[opsu]_[A-Za-z0-9]{20,}"),
)
_PRIVATE_PATH_PATTERN = re.compile(
    r"(?:/Users/[^/\s]+|/home/[^/\s]+|/mnt/(?:data\d*|home)/[^\s'\"]+)"
)


def scan_for_leaks(paths: Iterable[Path], configured_secrets: Sequence[str]) -> list[str]:
    findings: list[str] = []
    for path in sorted(set(paths)):
        data = path.read_bytes()
        text = data.decode("utf-8", errors="ignore")
        for secret in configured_secrets:
            if secret.encode() in data:
                findings.append(f"{path}: contains a configured secret value")
                break
        for pattern in _CREDENTIAL_PATTERNS:
            if pattern.search(text):
                findings.append(f"{path}: matches credential pattern {pattern.pattern}")
                break
        private_path = _PRIVATE_PATH_PATTERN.search(text)
        if private_path:
            findings.append(f"{path}: contains private path {private_path.group(0)}")
    return findings


def _copy_with_relative_base(path: Path, base: Path, destination: Path) -> Path:
    relative = path.resolve().relative_to(base.resolve())
    target = destination / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, target)
    return target


def build_bundle(run_dir: Path, destination: Path) -> dict[str, object]:
    run_dir = run_dir.resolve()
    all_results = load_case_results(run_dir)
    selected = [case for case in all_results if case.selected]
    source_files = report_files(run_dir)
    for case in selected:
        source_files.extend(selected_case_files(case))
    source_files = sorted(set(source_files))

    if destination.exists():
        raise FeedbackError(f"Feedback destination already exists: {destination}")
    destination.mkdir(parents=True)
    copied = [_copy_with_relative_base(path, run_dir, destination) for path in source_files]

    manifest: dict[str, object] = {
        "schema_version": 1,
        "run_id": run_dir.name,
        "generated_at": datetime.now(UTC).isoformat(),
        "case_results_total": len(all_results),
        "case_traces_included": len(selected),
        "selection_rule": "utility is false OR asr is true",
        "files": [
            {
                "path": str(path.relative_to(destination)),
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
            }
            for path in sorted(copied)
        ],
    }
    (destination / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return manifest


def make_archive(bundle_dir: Path, archive_path: Path) -> None:
    with tarfile.open(archive_path, "w:gz") as archive:
        archive.add(bundle_dir, arcname=bundle_dir.name)


def shard_file(path: Path, output_dir: Path, limit: int = MAX_RELEASE_PART_BYTES) -> list[Path]:
    if limit <= 0:
        raise ValueError("Shard limit must be positive")
    output_dir.mkdir(parents=True, exist_ok=True)
    parts: list[Path] = []
    with path.open("rb") as source:
        index = 0
        while True:
            block = source.read(limit)
            if not block:
                break
            part = output_dir / f"{path.name}.part-{index:04d}"
            part.write_bytes(block)
            parts.append(part)
            index += 1
    return parts


def run_command(args: Sequence[str], cwd: Path | None = None, capture: bool = False) -> str:
    result = subprocess.run(
        list(args),
        cwd=cwd,
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )
    return result.stdout.strip() if capture else ""


def _git_has_upstream_write() -> bool:
    value = run_command(
        ["gh", "api", f"repos/{UPSTREAM_REPOSITORY}", "--jq", ".permissions.push"],
        capture=True,
    )
    return value == "true"


def _ensure_gh_auth() -> None:
    try:
        run_command(["gh", "auth", "status"])
    except (FileNotFoundError, subprocess.CalledProcessError):
        if shutil.which("gh") is None:
            raise FeedbackError("GitHub CLI (gh) is required for upload")
        run_command(["gh", "auth", "login", "--web"])


def publish_bundle(repo_root: Path, run_dir: Path, bundle_dir: Path, archive: Path) -> str:
    _ensure_gh_auth()
    run_command(["gh", "auth", "setup-git"])
    can_push_upstream = _git_has_upstream_write()
    login = run_command(["gh", "api", "user", "--jq", ".login"], capture=True)
    publish_repo = UPSTREAM_REPOSITORY if can_push_upstream else f"{login}/AS-all"
    if not can_push_upstream:
        try:
            run_command(["gh", "repo", "view", publish_repo])
        except subprocess.CalledProcessError:
            run_command(["gh", "repo", "fork", UPSTREAM_REPOSITORY, "--clone=false"])

    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    branch = f"feedback/{run_dir.name}-{stamp}"
    tag = f"feedback-{run_dir.name}-{stamp}"
    try:
        base_revision = run_command(
            ["git", "rev-parse", "--verify", "refs/remotes/origin/main"],
            cwd=repo_root,
            capture=True,
        )
    except subprocess.CalledProcessError:
        base_revision = run_command(
            ["git", "rev-parse", "--verify", "refs/heads/main"],
            cwd=repo_root,
            capture=True,
        )
    with tempfile.TemporaryDirectory(prefix="as-all-feedback-worktree-") as temp:
        worktree = Path(temp) / "repo"
        run_command(
            ["git", "worktree", "add", "-b", branch, str(worktree), base_revision],
            cwd=repo_root,
        )
        try:
            pr_dir = worktree / "feedback" / run_dir.name
            pr_dir.mkdir(parents=True)
            shutil.copy2(bundle_dir / "manifest.json", pr_dir / "manifest.json")
            for report in (bundle_dir / "report").rglob("*"):
                if report.is_file():
                    target = pr_dir / "report" / report.relative_to(bundle_dir / "report")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(report, target)

            release_url = ""
            if archive.stat().st_size <= MAX_BRANCH_ARCHIVE_BYTES:
                shutil.copy2(archive, pr_dir / archive.name)
            else:
                shard_dir = Path(temp) / "shards"
                parts = shard_file(archive, shard_dir)
                checksum_lines = [f"{sha256_file(part)}  {part.name}" for part in parts]
                checksum_path = shard_dir / "SHA256SUMS"
                checksum_path.write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")
                (pr_dir / "release-assets.json").write_text(
                    json.dumps(
                        {
                            "tag": tag,
                            "parts": [
                                {"name": part.name, "sha256": sha256_file(part), "bytes": part.stat().st_size}
                                for part in parts
                            ],
                            "reassemble": f"cat {archive.name}.part-* > {archive.name}",
                        },
                        indent=2,
                    )
                    + "\n",
                    encoding="utf-8",
                )

            run_command(["git", "add", "feedback"], cwd=worktree)
            run_command(["git", "-c", f"user.name={login}", "-c", f"user.email={login}@users.noreply.github.com",
                         "commit", "-m", f"Add feedback for {run_dir.name}"], cwd=worktree)
            push_url = f"https://github.com/{publish_repo}.git"
            run_command(["git", "push", push_url, f"HEAD:refs/heads/{branch}"], cwd=worktree)

            if archive.stat().st_size > MAX_BRANCH_ARCHIVE_BYTES:
                assets = sorted((Path(temp) / "shards").iterdir())
                run_command(
                    [
                        "gh",
                        "release",
                        "create",
                        tag,
                        *[str(path) for path in assets],
                        "--repo",
                        publish_repo,
                        "--target",
                        branch,
                        "--title",
                        f"Feedback traces: {run_dir.name}",
                        "--notes",
                        "Public feedback trace archive. Verify SHA256SUMS before use.",
                    ]
                )
                release_url = run_command(
                    ["gh", "release", "view", tag, "--repo", publish_repo, "--json", "url", "--jq", ".url"],
                    capture=True,
                )

            head = branch if can_push_upstream else f"{login}:{branch}"
            body = (
                f"Automated public feedback for `{run_dir.name}`.\n\n"
                "Includes summary/source hashes/runtime errors and complete traces only for "
                "Utility=false or ASR=true cases.\n"
            )
            if release_url:
                body += f"\nLarge trace shards: {release_url}\n"
            return run_command(
                [
                    "gh",
                    "pr",
                    "create",
                    "--repo",
                    UPSTREAM_REPOSITORY,
                    "--base",
                    "main",
                    "--head",
                    head,
                    "--title",
                    f"Feedback: {run_dir.name}",
                    "--body",
                    body,
                ],
                cwd=worktree,
                capture=True,
            )
        finally:
            run_command(["git", "worktree", "remove", "--force", str(worktree)], cwd=repo_root)


def newest_run(results_dir: Path) -> Path:
    candidates = [path for path in results_dir.iterdir() if path.is_dir()]
    if not candidates:
        raise FeedbackError(f"No run directories found below {results_dir}")
    return max(candidates, key=lambda path: path.stat().st_mtime)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, help="results/<run_id>; defaults to newest run")
    parser.add_argument(
        "--confirm-public-upload",
        action="store_true",
        help="required acknowledgement that the generated PR and release assets are public",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = Path(__file__).resolve().parents[2]
    run_dir = args.run_dir.resolve() if args.run_dir else newest_run(repo_root / "results").resolve()
    try:
        run_dir.relative_to((repo_root / "results").resolve())
    except ValueError as exc:
        raise FeedbackError("Run directory must be inside this repository's results directory") from exc
    if not args.confirm_public_upload:
        raise FeedbackError("Public upload was not confirmed; nothing was uploaded")

    with tempfile.TemporaryDirectory(prefix="as-all-feedback-") as temp:
        temp_dir = Path(temp)
        bundle_dir = temp_dir / f"feedback-{run_dir.name}"
        manifest = build_bundle(run_dir, bundle_dir)
        configured_secrets = load_configured_secrets(
            [repo_root / ".secrets.env", run_dir / ".secrets.env"]
        )
        bundle_files = [path for path in bundle_dir.rglob("*") if path.is_file()]
        findings = scan_for_leaks(bundle_files, configured_secrets)
        if findings:
            details = "\n".join(f"- {finding}" for finding in findings)
            raise FeedbackError(f"Suspected private data found; upload stopped:\n{details}")
        archive = temp_dir / f"feedback-{run_dir.name}.tar.gz"
        make_archive(bundle_dir, archive)
        pr_url = publish_bundle(repo_root, run_dir, bundle_dir, archive)
        print(
            f"Published {manifest['case_traces_included']} selected case traces.\n"
            f"Pull request: {pr_url}"
        )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FeedbackError, subprocess.CalledProcessError) as exc:
        print(f"feedback: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
