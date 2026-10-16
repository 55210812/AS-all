"""Freeze public source provenance and hashes; never includes runtime results."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    roots = [ROOT / name for name in ("src", "vendor", "reference", "data", "tests", "tools", "docs", ".github")]
    files = sorted(p for root in roots for p in root.rglob("*")
                   if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc")
    files += [ROOT / name for name in ("README.md", "LICENSE", "THIRD_PARTY_NOTICES.md",
                                      "pyproject.toml", "uv.lock", "run.sh", "feedback.sh", ".python-version")]
    data = {
        "format": 1,
        "origins": {
            "agentdojo": {"repository": "https://github.com/ethz-spylab/agentdojo", "distribution": "0.1.35", "benchmark": "v1.2.2"},
            "ipiguard": {"repository": "https://github.com/Greysahy/ipiguard", "commit": "4e686ed2f62c135cb12564a4466daa95f3ace878"},
            "native_a": {"session": "01a1433f-c9ea-7bc2-b774-1525f9d3a27a", "variant_reference": "reference/native_a/ablation_variants.py", "paired_pilot_noninferiority": "failed"},
            "frames": {"tasks": 97, "native_a_overlap_exact": 61, "existing_frozen_supplement": 36, "generation_requests": 0},
            "detector": {"repository": "protectai/deberta-v3-base-prompt-injection-v2", "revision": "90c9989b1a342275dd0d1a95aad283c04e075671"},
        },
        "files": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
    }
    (ROOT / "source_manifest.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
