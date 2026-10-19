"""Freeze model-specific tool_knowledge inputs; no model API calls."""
import argparse
import json
from types import SimpleNamespace
from as_all.cli import registry
from as_all.experiments import EXPERIMENTS, get_experiment
from as_all.methods import ROOT
from agentdojo.task_suite.load_suites import get_suite
from agentdojo.attacks.important_instructions_attacks import ToolKnowledgeAttack


def main(experiment="qwen-tool-knowledge"):
    profile = get_experiment(experiment)
    if profile.attack != "tool_knowledge":
        raise ValueError("Only tool_knowledge inputs can be frozen by this script")
    attacks, builders = {}, {}
    for case in registry(experiment=experiment):
        if case["method"] != "no_defense" or not case["injection"]:
            continue
        domain = case["domain"]
        suite = get_suite("v1.2.2", domain)
        if domain not in builders:
            builders[domain] = ToolKnowledgeAttack(suite, SimpleNamespace(name=profile.model))
        attacks[case["case_id"]] = builders[domain].attack(
            suite.get_user_task_by_id(case["task"]), suite.get_injection_task_by_id(case["injection"]))
    assert len(attacks) == 949 and all(attacks.values())
    path = ROOT / "data" / profile.attacks_file
    content = json.dumps(attacks, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if path.exists() and path.read_text() != content:
        raise RuntimeError("Refusing to replace frozen attack inputs")
    path.write_text(content)
    print(f"Frozen949 {profile.model} tool_knowledge combinations; model requests0; preparation used simulated GroundTruth tools")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", default="qwen-tool-knowledge",
                        choices=[key for key, value in EXPERIMENTS.items() if value.attack == "tool_knowledge"])
    main(parser.parse_args().experiment)
