"""Frozen experiment identities; model, attack and tool interface move together."""
from dataclasses import dataclass

DEFAULT_EXPERIMENT = "gemini-important"
WORKERS = 8
WITNESS_FORM_METHODS = ("no_witness_guard", "reasoning_context_guard", "as_pg", "as_pg_guard")


@dataclass(frozen=True)
class Experiment:
    id: str
    model: str
    attack: str
    provider: str
    key_env: str
    base_env: str
    default_base: str
    attacks_file: str
    methods: tuple[str, ...] | None = None


EXPERIMENTS = {
    "gemini-important": Experiment("gemini-important", "gemini-2.5-flash", "important_instructions", "gemini",
        "GEMINI_API_KEY", "GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta", "attacks949.json"),
    "qwen-tool-knowledge": Experiment("qwen-tool-knowledge", "qwen3.5-flash", "tool_knowledge", "qwen",
        "QWEN_API_KEY", "QWEN_BASE_URL", "", "qwen_tool_knowledge949.json"),
    "gemini-tool-knowledge": Experiment("gemini-tool-knowledge", "gemini-2.5-flash", "tool_knowledge", "gemini",
        "GEMINI_API_KEY", "GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta", "gemini_tool_knowledge949.json"),
    "qwen-important": Experiment("qwen-important", "qwen3.5-flash", "important_instructions", "qwen",
        "QWEN_API_KEY", "QWEN_BASE_URL", "", "qwen_important949.json", WITNESS_FORM_METHODS),
}


def get_experiment(experiment=DEFAULT_EXPERIMENT):
    try:
        return EXPERIMENTS[experiment]
    except KeyError:
        raise ValueError(f"Unknown experiment: {experiment}") from None
