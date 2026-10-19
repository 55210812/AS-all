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
            "holistic": {"implementation": "src/as_all/holistic.py", "authority": "original_user_task",
                         "witness": ["contribute_to_score", "reason"], "guard": False, "frame": False,
                         "gemini_interface": "native_domain_tools_A", "qwen_interface": "original_proxy"},
            "qwen_via": {"variant_reference": "reference/qwen_via/ablation_variants.py",
                         "source_sha256": "86a41c9b8ce4469b31ed301a280c38d832a42d87454fb56fd32c17ddb19b218f",
                         "user_confirmed": "2026-10-17", "interface": "original_proxy_and_system_domain_registry"},
            "frames": {"tasks": 97, "native_a_overlap_exact": 61, "existing_frozen_supplement": 36, "generation_requests": 0},
            "gemini_tool_knowledge": {"model": "gemini-2.5-flash", "benchmark": "v1.2.2",
                                      "builder": "agentdojo.attacks.important_instructions_attacks.ToolKnowledgeAttack",
                                      "inputs": "data/gemini_tool_knowledge949.json", "combinations": 949,
                                      "model_requests": 0, "preparation": "simulated GroundTruth tools"},
            "qwen_witness_forms": {"model": "qwen3.5-flash", "attack": "important_instructions",
                                   "implementation": "src/as_all/witness_forms.py",
                                   "inputs": "data/qwen_important949.json", "task_frames": 97,
                                   "methods": ["no_witness_guard", "reasoning_context_guard", "as_pg", "as_pg_guard"],
                                   "cases_per_method": 1046, "formal_cases": 4184,
                                   "history_boundary": "before the proposing Assistant response",
                                   "reasoning_source": "current proposing response reasoning_content; no synthesis",
                                   "pg_source": "vendor/core/src/semantic_action_frame_guard/joint_witness_runtime_guard.py",
                                   "components": "reference/witness_forms/component_sources.json",
                                   "history_prompt_sha256": "f244cd51e0f4e1b16efd9435af8daf1aa50a8168ab737abfbf325842290ba84d",
                                   "reasoning_prompt_sha256": "fd75d107a941611cd67d94baf38d07e396df19325bd344bd7aa30d839447af28",
                                   "history_serializer": {"implementation": "vendor/agentdojo/src/agentdojo/agent_pipeline/task_shield_defense.py",
                                       "original_source_sha256": "2162ef56fe9703f20e2a12533477a3e831a32c8bc6a2b4b8381033b253196097",
                                       "bind_sha256": "587b3c8916c93fe33031f0762ab43f46051300cfdd3a61a4a3db4737ea09f815",
                                       "message_text_sha256": "b3e5537e438f13eadcc8bd2f6fedca8cabfc11b64f2d5c916c44530ca0d07e7c"},
                                   "guard_policy": "original frozen prompts; history root/via/decision/reason; reasoning decision/reason; joint PG four-field verdict"},
            "detector": {"repository": "protectai/deberta-v3-base-prompt-injection-v2", "revision": "90c9989b1a342275dd0d1a95aad283c04e075671"},
        },
        "files": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
    }
    (ROOT / "source_manifest.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
