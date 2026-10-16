"""Maintainer-only deterministic input generation; no model API calls.

GroundTruth executes simulated benchmark tools to identify original injection vectors.
This is input preparation, not a formal Agent trajectory or a performance result.
"""
import json
from types import SimpleNamespace
from as_all.cli import registry
from as_all.methods import ROOT
from agentdojo.task_suite.load_suites import get_suite
from agentdojo.attacks.important_instructions_attacks import ImportantInstructionsAttack

tasks, attacks, builders = {}, {}, {}
for case in registry():
    if case["method"] != "no_defense":
        continue
    suite = get_suite("v1.2.2", case["domain"])
    task = suite.get_user_task_by_id(case["task"])
    tasks[f"{case['domain']}/{case['task']}"] = task.PROMPT
    if case["injection"]:
        if case["domain"] not in builders:
            builders[case["domain"]] = ImportantInstructionsAttack(suite, SimpleNamespace(name="gemini-2.5-flash"))
        attacks[case["case_id"]] = builders[case["domain"]].attack(
            task, suite.get_injection_task_by_id(case["injection"]))
assert len(tasks) == 97 and len(attacks) == 949
for name, value in (("task_texts97.json", tasks), ("attacks949.json", attacks)):
    path = ROOT / "data" / name
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if path.exists() and path.read_text() != text:
        raise RuntimeError(f"Refusing to replace frozen input: {name}")
    path.write_text(text)
print("Frozen97 tasks and949 attack inputs; model requests0; preparation used simulated GroundTruth tools")
