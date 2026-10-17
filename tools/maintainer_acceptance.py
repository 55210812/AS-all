"""Run exactly the approved22-case acceptance with an existing local channel file.

This helper never copies the channel file or prints its contents. Not the end-user launcher.
"""
import argparse
from pathlib import Path
from dotenv import load_dotenv
from as_all.bootstrap import _write_secrets, repo_root
from as_all.experiments import DEFAULT_EXPERIMENT, EXPERIMENTS, get_experiment
import os
import subprocess

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--channel-file", required=True, type=Path)
    parser.add_argument("--experiment", choices=EXPERIMENTS, default=DEFAULT_EXPERIMENT)
    args = parser.parse_args()
    load_dotenv(args.channel_file, override=True)
    profile = get_experiment(args.experiment)
    path = repo_root() / ".secrets.env"
    from as_all.bootstrap import _parse_env_file
    existing = _parse_env_file(path)
    existing.update({profile.key_env: os.environ[profile.key_env],
                     profile.base_env: os.environ.get(profile.base_env, profile.default_base)})
    _write_secrets(path, existing)
    subprocess.run(["bash", "run.sh", "start", "--experiment", profile.id, "--non-interactive", "--acceptance"],
                   cwd=repo_root(), check=True)

if __name__ == "__main__":
    main()
