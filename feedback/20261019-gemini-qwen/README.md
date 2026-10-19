# Gemini and Qwen experiment results — 2026-10-19

Gemini `gemini-2.5-flash` uses `important_instructions`; Qwen `qwen3.5-flash` uses `tool_knowledge`.
Each profile covers 11 methods × 1046 cases = 11,506 cases. Model/attack profiles are reported separately.

| Model | First-pass errors | Supplemental attempts | Recovered | Remaining errors |
|---|---:|---:|---:|---:|
| Gemini | 430 | 430 | 353 | 77 |
| Qwen | 280 | 280 | 259 | 21 |
| Total | 710 | 710 | 612 | 98 |

`first_pass/` preserves the original reports. `final/` combines first-pass successes with one additional
attempt for each first-pass runtime error. No case was selected by utility or attack outcome. Runtime
errors remain errors. The recovery did not change experiment source, models, attacks, prompts, or validators.

The report CSV/JSON/Markdown files contain per-method Clean/Attack metrics. `paired1046.json.gz`
contains all per-case records grouped across methods; `actual_costs.json.gz` contains selected-case usage.
Large source reports use lossless gzip encoding. FILES.json records hashes of encoded and original bytes.

`recovery/comparison.csv` and `.json` record every first-pass error and its single supplemental result.
`recovery/all_attempt_costs.json` includes actual usage of BOTH models and BOTH attempts, including failed
attempts. Do not add this total to the selected-case usage in individual reports. Unknown usage/cache
fields retain the original report semantics. `experiment.json` records frozen configuration, input/source
hashes, and execution topology for each supplemental stage.

This package contains structured results and audit records. Native request/response/semantic traces
remain on the experiment server. The original trace-feedback scan flagged credential-shaped strings
and path-shaped text; those raw files were neither modified nor included here. All uncompressed source
reports in this package passed the repository's original secret/privacy scanner.

This result package was prepared locally; preparation did not publish to GitHub or make API requests.
