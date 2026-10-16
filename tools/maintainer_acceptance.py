"""Run exactly the approved22-case acceptance with an existing local channel file.

This helper never copies the channel file or prints its contents. Not the end-user launcher.
"""
import argparse
from pathlib import Path
from dotenv import load_dotenv
from as_all.cli import preflight, run

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--channel-file", required=True, type=Path)
    parser.add_argument("--run-dir", required=True, type=Path)
    args = parser.parse_args()
    load_dotenv(args.channel_file, override=True)
    args.run_dir.mkdir(parents=True, exist_ok=True)
    preflight(args.run_dir.resolve(), acceptance=True)
    run(args.run_dir.resolve(), acceptance=True)

if __name__ == "__main__":
    main()
