import importlib.util
import json
from pathlib import Path


def test_freeze_sources_excludes_generated_caches(tmp_path, monkeypatch):
    script = Path(__file__).resolve().parents[1] / "tools/freeze_sources.py"
    spec = importlib.util.spec_from_file_location("freeze_sources", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    for name in ("README.md", "LICENSE", "THIRD_PARTY_NOTICES.md", "pyproject.toml",
                 "uv.lock", "run.sh", "feedback.sh", ".python-version", "src/public.py",
                 "reference/tests/.pytest_cache/v/cache/nodeids", "vendor/core/.ruff_cache/cache",
                 "tools/__pycache__/generated.pyc"):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture")
    module.main()
    files = json.loads((tmp_path / "source_manifest.json").read_text())["files"]
    assert "src/public.py" in files
    assert all(not {".pytest_cache", ".ruff_cache", "__pycache__"}.intersection(Path(p).parts)
               for p in files)
    from as_all import cli
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    runtime_files = cli.source_hashes()
    assert "src/public.py" in runtime_files
    assert all(not {".pytest_cache", ".ruff_cache", "__pycache__"}.intersection(Path(p).parts)
               for p in runtime_files)
