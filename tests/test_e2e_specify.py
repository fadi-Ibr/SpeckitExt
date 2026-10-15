"""Disposable-project E2E through the real upstream `specify` CLI.

Skipped (not failed) when no `specify` executable is available. Only ever
creates projects inside pytest tmp directories.
"""
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.conftest import write_project

REPO = Path(__file__).resolve().parent.parent
pytestmark = pytest.mark.skipif(shutil.which("specify") is None,
                                reason="specify CLI not installed")


def _run(args, cwd):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=300)


def test_fresh_project_install_compile_uninstall(tmp_path):
    init = _run(["specify", "init", "e2e-proj", "--integration", "claude",
                 "--non-interactive"], tmp_path)
    assert init.returncode == 0, init.stdout + init.stderr
    proj = tmp_path / "e2e-proj"
    assert _run(["specify", "preset", "add", "--dev", str(REPO / "preset")], proj).returncode == 0
    assert _run(["specify", "extension", "add", "--dev", str(REPO / "extension")], proj).returncode == 0

    resolved = _run(["specify", "preset", "resolve", "spec-template"], proj)
    assert "presets" in resolved.stdout and "traceability" in resolved.stdout
    skills = {p.name for p in (proj / ".claude/skills").iterdir()} if (proj / ".claude/skills").is_dir() else set()
    assert "speckit-traceability-validate" in skills and "speckit-implement" in skills
    implement = next((proj / ".claude/skills/speckit-implement").rglob("SKILL.md"))
    assert "speckitext compile" in implement.read_text(encoding="utf-8")

    # Seed traceability artifacts (synthetic fixture) and compile via the real CLI.
    fixture = write_project(tmp_path / "fixture")
    for name in ("spec.md", "plan.md", "tasks.md"):
        dest = proj / "specs/001-demo"; dest.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(fixture / "specs/001-demo" / name, dest / name)
    shutil.copyfile(fixture / ".specify/memory/constitution.md",
                    proj / ".specify/memory/constitution.md")
    validate = _run(["speckitext", "validate", "--project", "."], proj)
    assert validate.returncode == 0, validate.stdout + validate.stderr
    pkg = proj / ".specify/context/T002.md"
    compile_run = _run(["speckitext", "compile", "--project", ".", "--tasks", "T002",
                        "--output", str(pkg)], proj)
    assert compile_run.returncode == 0, compile_run.stdout + compile_run.stderr
    text = pkg.read_text(encoding="utf-8")
    assert "FR-001" in text and "FR-003" not in text  # unrelated sections excluded

    # Safe uninstall / reinstall.
    assert _run(["specify", "preset", "remove", "traceability"], proj).returncode == 0
    assert _run(["specify", "extension", "remove", "traceability", "--force"], proj).returncode == 0
    assert _run(["specify", "preset", "add", "--dev", str(REPO / "preset")], proj).returncode == 0
    assert _run(["specify", "extension", "add", "--dev", str(REPO / "extension")], proj).returncode == 0
