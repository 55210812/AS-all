# Quick start

Choose Gemini important_instructions or Qwen tool_knowledge. Each experiment runs
eleven methods:97 Clean and949 Attack cases per method, or11,506 paid cases. Benchmark
tools operate only on AgentDojo's simulated environments.

## Requirements

- Linux
- Python 3.12 (managed by `uv`)
- [`uv`](https://docs.astral.sh/uv/getting-started/installation/)
- `tmux` and `cron`
- A Gemini API key for `gemini-2.5-flash`, or a Qwen key and compatible API base for `qwen3.5-flash`
- Enough disk space for the pinned injection-detector weights

If uv is missing, run.sh installs uv0.9.18 into a project-private bootstrap
environment using Python3's venv and pip. It does not alter system Python or pipe a remote script into a shell.

## Run

```bash
git clone https://github.com/55210812/AS-all.git
cd AS-all
bash run.sh
```

On the first run, choose1(default) for Gemini or2 for Qwen. The script asks for
the selected provider's API key(hidden), API base and optional Hugging Face token.
Gemini uses native generateContent; Qwen uses its original Chat Completions protocol.
Both models are preset. Credentials are stored separately in
`.secrets.env` with mode `0600`; that file is ignored by Git and is not placed
in process arguments or experiment logs.

The script then:

1. creates the locked project environment with `uv sync --frozen`;
2. runs the offline/readiness preflight and downloads the pinned detector once;
3. displays the exact 11,506-case paid-run warning;
4. starts8 independent case workers in an experiment-specific tmux session after explicit confirmation;
5. installs one experiment-specific, read-only watchdog cron entry every10 minutes.

The watchdog never restarts the manager. Existing unrelated cron entries are
preserved and backed up under `.state/`.

## Progress and results

The launcher prints the absolute result directory, always under:

```text
results/<experiment_id>/<run_id>/
```

Check progress without finding the run ID manually:

```bash
bash run.sh status
bash run.sh status --experiment qwen-tool-knowledge
```

Running `bash run.sh` again while its tmux session exists does not launch a
duplicate. If the session stopped, it reuses the active run directory so the
experiment CLI can continue only work that was not already completed. Partial
requests are retained for review rather than blindly resent.

For the isolated 22-case live acceptance set, use:

```bash
bash run.sh start --experiment qwen-tool-knowledge --acceptance
```

Acceptance output uses the same result structure but is not mixed into the
11,506-case formal run.

After completion, package and return the selected reports with:

```bash
bash feedback.sh
bash feedback.sh --experiment qwen-tool-knowledge
```

That command performs a credential scan before preparing any public GitHub
feedback. See the repository README for the report layout and feedback flow.

To reuse an existing Python3.12 environment without installing dependencies again:

```bash
AS_ALL_PYTHON=/absolute/path/to/python bash run.sh start --experiment qwen-tool-knowledge --acceptance
```

Old frozen runs are not rewritten to8 workers. No other experiment is started automatically.
