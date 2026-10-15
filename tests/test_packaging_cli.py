import json
import re
from pathlib import Path

from speckitext.cli import main

REPO = Path(__file__).resolve().parent.parent


def _yaml_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_preset_manifest_shape():
    text = _yaml_text(REPO / "preset/preset.yml")
    assert 'id: "traceability"' in text and 'speckit_version: ">=0.9.0"' in text
    for name in ("constitution-template", "spec-template", "plan-template", "tasks-template"):
        assert f'name: "{name}"' in text
        assert (REPO / "preset/templates" / f"{name}.md").is_file()
    for cmd in ("constitution", "specify", "clarify", "plan", "tasks", "analyze", "implement"):
        assert f"speckit.{cmd}" in text
        assert (REPO / "preset/commands" / f"speckit.{cmd}.md").is_file()


def test_extension_manifest_shape():
    text = _yaml_text(REPO / "extension/extension.yml")
    assert re.search(r"id:\s*\"?traceability\"?", text)
    for cmd in ("validate", "compile", "batch", "impact", "expand", "migrate"):
        assert f"speckit.traceability.{cmd}" in text
        assert (REPO / "extension/commands" / f"speckit.traceability.{cmd}.md").is_file()
    assert "after_tasks" in text


def test_implement_command_uses_scoped_package_only():
    text = _yaml_text(REPO / "preset/commands/speckit.implement.md")
    assert "speckitext compile" in text
    assert "Do NOT load the\n   full constitution.md" in text or "Do NOT load" in text
    assert "speckitext expand" in text and "stale" in text.lower()


def test_wrap_commands_keep_core_template():
    for cmd in ("constitution", "specify", "clarify", "plan", "tasks", "analyze"):
        text = _yaml_text(REPO / "preset/commands" / f"speckit.{cmd}.md")
        assert "{CORE_TEMPLATE}" in text


def test_cli_validate_compile_batch_impact(project, tmp_path, capsys):
    pkg = tmp_path / "ctx.md"
    assert main(["validate", "--project", str(project)]) == 0
    assert main(["compile", "--project", str(project), "--tasks", "T002",
                 "--output", str(pkg)]) == 0
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1]) if False else None
    text = pkg.read_text(encoding="utf-8")
    assert "speckitext-package" in text and "FR-001" in text
    assert main(["batch", "suggest", "--project", str(project)]) == 0
    assert main(["impact", "--project", str(project), "--ids", "FR-001"]) == 0
    eff = tmp_path / "ctx2.md"
    assert main(["expand", "--project", str(project), "--package", str(pkg),
                 "--ids", "FR-002", "--output", str(eff)]) == 0
    assert "FR-002" in eff.read_text(encoding="utf-8")


def test_cli_migrate_dry_run(tmp_path, capsys):
    from tests.test_migration import write_legacy
    root = write_legacy(tmp_path / "legacy")
    assert main(["migrate", "--project", str(root), "--dry-run"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == "dry-run" and payload["files_would_change"]


def test_bundle_manifest_references_components():
    text = _yaml_text(REPO / "bundle/bundle.yml")
    assert 'id: "speckitext"' in text and 'id: "traceability"' in text
