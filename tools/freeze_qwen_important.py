"""Freeze the four-method Qwen important_instructions inputs without model requests."""
import json
from types import SimpleNamespace

from agentdojo.attacks.important_instructions_attacks import ImportantInstructionsAttack
from agentdojo.task_suite.load_suites import get_suite
from as_all.cli import registry
from as_all.experiments import get_experiment
from as_all.methods import ROOT


def main():
    profile = get_experiment("qwen-important")
    attacks, builders = {}, {}
    for case in registry(experiment=profile.id):
        if case["method"] != profile.methods[0] or not case["injection"]:
            continue
        domain = case["domain"]
        suite = get_suite("v1.2.2", domain)
        if domain not in builders:
            builders[domain] = ImportantInstructionsAttack(suite, SimpleNamespace(name=profile.model))
        attacks[case["case_id"]] = builders[domain].attack(
            suite.get_user_task_by_id(case["task"]), suite.get_injection_task_by_id(case["injection"]))
    assert len(attacks) == 949 and all(attacks.values())
    path = ROOT / "data" / profile.attacks_file
    content = json.dumps(attacks, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if path.exists() and path.read_text() != content:
        raise RuntimeError("Refusing to replace frozen attack inputs")
    path.write_text(content)
    print("Frozen949 Qwen important_instructions inputs; model requests0; simulated GroundTruth preparation only")


if __name__ == "__main__":
    main()
