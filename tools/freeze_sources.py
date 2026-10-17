"""Freeze public source provenance and hashes; never includes runtime results."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    roots = [ROOT / name for name in ("src", "vendor", "reference", "data", "tests", "tools", "docs", ".github")]
    files = sorted(p for root in roots for p in root.rglob("*")
                   if p.is_file() and not {"__pycache__", ".pytest_cache", ".ruff_cache"}.intersection(p.parts)
                   and p.suffix != ".pyc")
    files += [ROOT / name for name in ("README.md", "LICENSE", "THIRD_PARTY_NOTICES.md",
                                      "pyproject.toml", "uv.lock", "run.sh", "feedback.sh", ".python-version")]
    data = {
        "format": 1,
        "origins": {
            "agentdojo": {"repository": "https://github.com/ethz-spylab/agentdojo", "distribution": "0.1.35", "benchmark": "v1.2.2"},
            "ipiguard": {"repository": "https://github.com/Greysahy/ipiguard", "commit": "4e686ed2f62c135cb12564a4466daa95f3ace878"},
            "native_a": {"session": "01a1433f-c9ea-7bc2-b774-1525f9d3a27a", "variant_reference": "reference/native_a/ablation_variants.py", "paired_pilot_noninferiority": "failed"},
            "qwen_via": {"variant_reference": "reference/qwen_via/ablation_variants.py",
                         "source_sha256": "86a41c9b8ce4469b31ed301a280c38d832a42d87454fb56fd32c17ddb19b218f",
                         "user_confirmed": "2026-10-17", "interface": "original_proxy_and_system_domain_registry"},
            "frames": {"tasks": 97, "native_a_overlap_exact": 61, "existing_frozen_supplement": 36, "generation_requests": 0},
            "detector": {"repository": "protectai/deberta-v3-base-prompt-injection-v2", "revision": "90c9989b1a342275dd0d1a95aad283c04e075671"},
        },
        "files": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
    }
    (ROOT / "source_manifest.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
