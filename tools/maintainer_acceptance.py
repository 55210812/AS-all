"""Run exactly the approved22-case acceptance with an existing local channel file.

This helper never copies the channel file or prints its contents. Not the end-user launcher.
"""
import argparse
from pathlib import Path
from dotenv import load_dotenv
from as_all.bootstrap import _write_secrets, repo_root, start
import os

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--channel-file", required=True, type=Path)
    args = parser.parse_args()
    load_dotenv(args.channel_file, override=True)
    _write_secrets(repo_root() / ".secrets.env", {
        "GEMINI_API_KEY": os.environ["GEMINI_API_KEY"],
        "GEMINI_BASE_URL": os.environ.get("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta"),
    })
    start(repo_root(), non_interactive=True, acceptance=True)

if __name__ == "__main__":
    main()
