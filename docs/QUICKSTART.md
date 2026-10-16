# Quick start

The package runs eight defenses on the fixed Gemini full benchmark: 97 Clean
and 949 Attack cases per method, or 8,368 paid model cases in total. Benchmark
tools operate only on AgentDojo's simulated environments.

## Requirements

- Linux
- Python 3.12 (managed by `uv`)
- [`uv`](https://docs.astral.sh/uv/getting-started/installation/)
- `tmux` and `cron`
- A Gemini API key with access to `gemini-2.5-flash`
- Enough disk space for the pinned injection-detector weights

Install `uv` with one of its documented package-manager or standalone methods.
`run.sh` intentionally does not pipe a remote installer into a shell.

## Run

```bash
git clone https://github.com/55210812/AS-all.git
cd AS-all
bash run.sh
```

On the first run, the script asks for the Gemini API key using hidden input, an
optional native Gemini API base URL (`GEMINI_BASE_URL`), and an optional Hugging Face token. The
fixed model is `gemini-2.5-flash`. Credentials are stored only in
`.secrets.env` with mode `0600`; that file is ignored by Git and is not placed
in process arguments or experiment logs.

The script then:

1. creates the locked project environment with `uv sync --frozen`;
2. runs the offline/readiness preflight and downloads the pinned detector once;
3. displays the exact 8,368-case paid-run warning;
4. starts the run in a repository-specific tmux session after explicit confirmation;
5. installs one repository-specific, read-only watchdog cron entry every 10 minutes.

The watchdog never restarts the manager. Existing unrelated cron entries are
preserved and backed up under `.state/`.

## Progress and results

The launcher prints the absolute result directory, always under:

```text
results/<run_id>/
```

Check progress without finding the run ID manually:

```bash
bash run.sh status
```

Running `bash run.sh` again while its tmux session exists does not launch a
duplicate. If the session stopped, it reuses the active run directory so the
experiment CLI can continue only work that was not already completed. Partial
requests are retained for review rather than blindly resent.

For the isolated 16-case live acceptance set, use:

```bash
bash run.sh start --acceptance
```

Acceptance output uses the same result structure but is not mixed into the
8,368-case formal run.

After completion, package and return the selected reports with:

```bash
bash feedback.sh
```

That command performs a credential scan before preparing any public GitHub
feedback. See the repository README for the report layout and feedback flow.
