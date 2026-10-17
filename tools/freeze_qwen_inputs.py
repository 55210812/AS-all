"""Freeze the native Qwen tool_knowledge inputs; no model API calls."""
import json
from types import SimpleNamespace
from as_all.cli import registry
from as_all.methods import ROOT
from agentdojo.task_suite.load_suites import get_suite
from agentdojo.attacks.important_instructions_attacks import ToolKnowledgeAttack


def main():
    attacks, builders = {}, {}
    for case in registry(experiment="qwen-tool-knowledge"):
        if case["method"] != "no_defense" or not case["injection"]:
            continue
        domain = case["domain"]
        suite = get_suite("v1.2.2", domain)
        if domain not in builders:
            builders[domain] = ToolKnowledgeAttack(suite, SimpleNamespace(name="qwen3.5-flash"))
        attacks[case["case_id"]] = builders[domain].attack(
            suite.get_user_task_by_id(case["task"]), suite.get_injection_task_by_id(case["injection"]))
    assert len(attacks) == 949 and all(attacks.values())
    path = ROOT / "data/qwen_tool_knowledge949.json"
    content = json.dumps(attacks, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if path.exists() and path.read_text() != content:
        raise RuntimeError("Refusing to replace frozen Qwen attack inputs")
    path.write_text(content)
    print("Frozen949 Qwen tool_knowledge combinations; model requests0; preparation used simulated GroundTruth tools")


if __name__ == "__main__":
    main()
