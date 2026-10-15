"""Synthetic legacy fixtures only — never a real project."""
from pathlib import Path

from speckitext.graph import Graph
from speckitext.migration import Migration
from speckitext.validate import is_valid, validate_graph

LEGACY_CONSTITUTION = """# Legacy Constitution

### CON-001: Quality gates
All work must be tested.
"""

LEGACY_SPEC = """# Feature Specification: Legacy Demo

- **FR-001**: Users MUST log in
- **FR-002**: Users MUST see a dashboard
"""

LEGACY_TASKS = """# Tasks: Legacy Demo

### VER-001: Legacy checks
Run: pytest tests/ -q

- [x] T001 Login form for FR-001 verified by VER-001
- [ ] T002 Login endpoint for FR-001 verified by VER-001 (depends on T001)
  Objective: Login endpoint accepts valid credentials and returns a session
  Scope: specs/001-legacy/tasks.md implementation in src/auth.py
  Accept: valid login succeeds and invalid login is rejected
- [ ] T003 Dashboard for FR-002 verified by VER-001
  Objective: Dashboard page renders for a logged-in user
  Scope: src/ui.py
  Accept: authenticated user sees the dashboard content
"""


def write_legacy(root: Path) -> Path:
    (root / ".specify/memory").mkdir(parents=True, exist_ok=True)
    (root / "specs/001-legacy").mkdir(parents=True, exist_ok=True)
    (root / ".specify/memory/constitution.md").write_text(LEGACY_CONSTITUTION, encoding="utf-8")
    (root / "specs/001-legacy/spec.md").write_text(LEGACY_SPEC, encoding="utf-8")
    (root / "specs/001-legacy/tasks.md").write_text(LEGACY_TASKS, encoding="utf-8")
    return root


def test_dry_run_is_non_destructive(tmp_path):
    root = write_legacy(tmp_path / "legacy")
    before = (root / "specs/001-legacy/tasks.md").read_text(encoding="utf-8")
    plan = Migration(root).plan()
    assert plan["transforms"] and not plan["findings"]
    assert (root / "specs/001-legacy/tasks.md").read_text(encoding="utf-8") == before
    assert not (root / ".speckitext").exists()


def test_full_migration_activates_and_validates(tmp_path):
    root = write_legacy(tmp_path / "legacy")
    result = Migration(root).apply()
    assert result["status"] == "activated"
    assert is_valid(validate_graph(Graph.build(root)))
    tasks = (root / "specs/001-legacy/tasks.md").read_text(encoding="utf-8")
    assert "satisfies: FR-001" in tasks  # evidence-based link preserved in text
    # Idempotent rerun.
    assert Migration(root).apply()["status"] == "noop"


def test_incomplete_migration_refused(tmp_path):
    root = write_legacy(tmp_path / "legacy")
    tasks = root / "specs/001-legacy/tasks.md"
    tasks.write_text(tasks.read_text(encoding="utf-8") +
                     "\n- [ ] T009 Mystery task with no requirement evidence\n", encoding="utf-8")
    plan = Migration(root).plan()
    assert any(f["id"] == "001-legacy::T009" for f in plan["findings"])
    result = Migration(root).apply()
    assert result["status"] == "refused"
    assert "speckitext" not in tasks.read_text(encoding="utf-8")  # nothing activated


def test_failure_injection_restores_originals(tmp_path):
    root = write_legacy(tmp_path / "legacy")
    originals = {p: p.read_bytes() for p in root.rglob("*.md")}
    result = Migration(root).apply(fail_after=1)
    assert result["status"] == "failed-restored"
    for p, data in originals.items():
        assert p.read_bytes() == data


def test_rollback_restores_originals(tmp_path):
    root = write_legacy(tmp_path / "legacy")
    original = (root / "specs/001-legacy/spec.md").read_bytes()
    assert Migration(root).apply()["status"] == "activated"
    assert Migration(root).rollback()["status"] == "rolled-back"
    assert (root / "specs/001-legacy/spec.md").read_bytes() == original
