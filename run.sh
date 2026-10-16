#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
cd "$ROOT_DIR"

if [ -n "${AS_ALL_PYTHON:-}" ]; then
  export PYTHONPATH="$ROOT_DIR/src:$ROOT_DIR/vendor/agentdojo/src:$ROOT_DIR/vendor/core/src${PYTHONPATH:+:$PYTHONPATH}"
  if [ "$#" -eq 0 ]; then set -- start; fi
  exec "$AS_ALL_PYTHON" -m as_all.bootstrap "$@"
fi

if ! command -v uv >/dev/null 2>&1; then
  command -v python3 >/dev/null 2>&1 || { echo "Python3 is required to bootstrap uv." >&2; exit 2; }
  python3 -m venv .state/bootstrap-env
  .state/bootstrap-env/bin/python -m pip install --disable-pip-version-check 'uv==0.9.18'
  export PATH="$ROOT_DIR/.state/bootstrap-env/bin:$PATH"
fi

if [ "$#" -eq 0 ]; then
  set -- start
fi

exec uv run --frozen --python 3.12 python -m as_all.bootstrap "$@"
