"""Corrective-pass regressions: freshness, expansion, CLI exits, migration
recovery, bootstrap/doctor/registration/install safety. Synthetic only."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from speckitext.cli import main
from speckitext.compiler import CompileError, compile_context, expand_context, package_staleness
from speckitext.graph import Graph
from speckitext.migration import Migration, MigrationCrash, incomplete_migrations
from tests.test_migration import write_legacy

REPO = Path(__file__).resolve().parent.parent


def _compile(project, tmp_path, tasks=("T002",)):
    pkg = tmp_path / "pkg.md"
    pkg.write_text(compile_context(Graph.build(project), project, list(tasks))["text"],
                   encoding="utf-8")
    return pkg


# ---- context freshness (§2) ------------------------------------------------

def test_new_global_rule_invalidates_old_package(project, tmp_path):
    pkg = _compile(project, tmp_path)
    assert package_staleness(Graph.build(project), pkg) == []
    const = project / ".specify/memory/constitution.md"
    const.write_text(const.read_text(encoding="utf-8") +
                     "\n### CON-099: New mandatory rule\n<!-- speckitext\nid: CON-099\n"
                     "kind: constitution\napplicability: GLOBAL\n-->\nAlways do the new thing.\n",
                     encoding="utf-8")
    stale = package_staleness(Graph.build(project), pkg)
    assert "CON-099" in [s["id"] for s in stale]


def test_newly_applicable_scoped_rule_invalidates(project, tmp_path):
    pkg = _compile(project, tmp_path)
    const = project / ".specify/memory/constitution.md"
    const.write_text(const.read_text(encoding="utf-8") +
                     "\n### CON-098: Scoped auth rule\n<!-- speckitext\nid: CON-098\n"
                     "kind: constitution\napplicability: SCOPED\nscope: COMP-001\n-->\n"
                     "Auth must do the scoped thing.\n", encoding="utf-8")
    assert "CON-098" in [s["id"] for s in package_staleness(Graph.build(project), pkg)]


def test_relationship_change_invalidates(project, tmp_path):
    pkg = _compile(project, tmp_path)
    plan = project / "specs/001-demo/plan.md"
    plan.write_text(plan.read_text(encoding="utf-8").replace(
        "satisfies: FR-001", "satisfies: FR-001, FR-002"), encoding="utf-8")
    # DEC-001 now pulls FR-002 into the closure; the old package omits it.
    assert "FR-002" in [s["id"] for s in package_staleness(Graph.build(project), pkg)]


def test_tampered_package_detected(project, tmp_path):
    pkg = _compile(project, tmp_path)
    pkg.write_text(pkg.read_text(encoding="utf-8") + "\nInjected instructions.\n",
                   encoding="utf-8")
    stale = package_staleness(Graph.build(project), pkg)
    assert stale and any(s["kind"] == "package-integrity" for s in stale)


# ---- expansion consistency (§3) ---------------------------------------------

def test_expansion_round_trip_and_dedup(project, tmp_path):
    pkg = _compile(project, tmp_path)
    out = tmp_path / "expanded.md"
    result = expand_context(Graph.build(project), project, pkg, ["FR-002"],
                            "needed for redirect target")
    out.write_text(result["text"], encoding="utf-8")
    assert "FR-002" in result["meta"]["included_ids"]
    assert package_staleness(Graph.build(project), out) == []
    again = expand_context(Graph.build(project), project, out, ["FR-002"], "again")
    assert [e["id"] for e in again["meta"]["expansions"]].count("FR-002") == 1
    assert set(again["meta"]["selected_tasks"]) == {"T002"}  # scope unchanged


def test_expanded_source_change_invalidates(project, tmp_path):
    pkg = _compile(project, tmp_path)
    out = tmp_path / "expanded.md"
    out.write_text(expand_context(Graph.build(project), project, pkg, ["FR-002"],
                                  "needed")["text"], encoding="utf-8")
    spec = project / "specs/001-demo/spec.md"
    spec.write_text(spec.read_text(encoding="utf-8").replace(
        "see a dashboard", "see a metrics dashboard"), encoding="utf-8")
    assert "FR-002" in [s["id"] for s in package_staleness(Graph.build(project), out)]


def test_expand_task_and_stale_package_rejected(project, tmp_path):
    pkg = _compile(project, tmp_path)
    with pytest.raises(CompileError, match="must not silently expand"):
        expand_context(Graph.build(project), project, pkg, ["T004"], "sneak in work")
    spec = project / "specs/001-demo/spec.md"
    spec.write_text(spec.read_text(encoding="utf-8").replace(
        "email and password", "email, password and MFA"), encoding="utf-8")
    with pytest.raises(CompileError, match="stale"):
        expand_context(Graph.build(project), project, pkg, ["FR-002"], "too late")


# ---- validate CLI exit codes (§4) -------------------------------------------

def test_validate_cli_package_failures_exit_nonzero(project, tmp_path, capsys):
    pkg = _compile(project, tmp_path)
    assert main(["validate", "--project", str(project), "--package", str(pkg)]) == 0
    capsys.readouterr()
    assert main(["validate", "--project", str(project),
                 "--package", str(tmp_path / "missing.md")]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["package_error"] and payload["package_fresh"] is False

    bad = tmp_path / "bad.md"
    bad.write_text("<!-- speckitext-package\n{not json}\n-->\n# x\n", encoding="utf-8")
    assert main(["validate", "--project", str(project), "--package", str(bad)]) == 1
    assert "package_error" in json.loads(capsys.readouterr().out)

    tampered = tmp_path / "tampered.md"
    body = pkg.read_text(encoding="utf-8").replace('"schema_version":"1.0"',
                                                   '"schema_version":"9.9"')
    tampered.write_text(body, encoding="utf-8")
    assert main(["validate", "--project", str(project), "--package", str(tampered)]) == 1
    assert "incompatible package schema" in json.loads(
        capsys.readouterr().out)["package_error"]


# ---- migration recovery (§5) -------------------------------------------------

def test_crash_recovery_in_new_process_state(tmp_path):
    root = write_legacy(tmp_path / "legacy")
    originals = {p: p.read_bytes() for p in root.rglob("*.md")}
    with pytest.raises(MigrationCrash):
        Migration(root).apply(crash_after=1)
    assert incomplete_migrations(root), "interruption must be detectable"
    assert main(["validate", "--project", str(root)]) == 1  # blocked from use
    result = Migration(root).recover()
    assert result["status"] == "recovered"
    for p, data in originals.items():
        assert p.read_bytes() == data  # byte-exact restoration
    assert Migration(root).recover()["status"] == "nothing-to-recover"  # idempotent
    assert Migration(root).apply()["status"] == "activated"  # usable after recovery


def test_subprocess_interruption_then_recovery(tmp_path):
    root = write_legacy(tmp_path / "legacy")
    originals = {p: p.read_bytes() for p in root.rglob("*.md")}
    crash = subprocess.run(
        [sys.executable, "-c",
         "from pathlib import Path; from speckitext.migration import Migration; "
         f"Migration(Path({str(root)!r})).apply(crash_after=1)"],
        capture_output=True, text=True)
    assert crash.returncode != 0
    assert incomplete_migrations(root)
    rec = subprocess.run([sys.executable, "-m", "speckitext", "migrate",
                          "--project", str(root), "--recover"],
                         capture_output=True, text=True)
    assert rec.returncode == 0, rec.stdout + rec.stderr
    assert json.loads(rec.stdout)["status"] == "recovered"
    for p, data in originals.items():
        assert p.read_bytes() == data


def test_recovery_with_missing_backup_refuses(tmp_path):
    root = write_legacy(tmp_path / "legacy")
    with pytest.raises(MigrationCrash):
        Migration(root).apply(crash_after=1)
    txn = sorted((root / ".speckitext/migrations").glob("*"))[-1]
    backup = next((txn / "backup").rglob("*.md"))
    backup.unlink()
    result = Migration(root).recover()
    assert result["status"] == "recovery-required"
    assert incomplete_migrations(root)  # still blocked, not silently usable


def test_corrupt_journal_detected(tmp_path):
    root = write_legacy(tmp_path / "legacy")
    txn = root / ".speckitext/migrations/broken"
    txn.mkdir(parents=True)
    (txn / "journal.json").write_text("{oops", encoding="utf-8")
    assert incomplete_migrations(root)
    assert Migration(root).recover()["status"] == "recovery-required"


def test_rollback_conflict_preserves_user_edits(tmp_path):
    root = write_legacy(tmp_path / "legacy")
    assert Migration(root).apply()["status"] == "activated"
    spec = root / "specs/001-legacy/spec.md"
    edited = spec.read_bytes() + b"\nUser work after migration.\n"
    spec.write_bytes(edited)
    result = Migration(root).rollback()
    assert result["status"] == "rollback-conflict"
    assert spec.read_bytes() == edited  # never silently overwritten
    assert Migration(root).rollback(force=True)["status"] == "rolled-back"


# ---- migration completeness (§6) ----------------------------------------------

IDLESS_CONSTITUTION = """# Project Constitution

## Quality gates
All work must be tested before it ships.

## Security baseline
Secrets must never be committed.
"""

IDLESS_PLAN = """# Implementation Plan

## Token sessions
Use opaque session tokens stored server-side for FR-001.
"""

LEGACY2_TASKS = """# Tasks

### VER-001: Project checks
Run: pytest tests/ -q

- [x] T001 Login form for FR-001 verified by VER-001
- [ ] T002 Login endpoint for FR-001 verified by VER-001 (depends on T001)
  Objective: Login endpoint returns a session for valid credentials
  Scope: src/auth.py
  Accept: valid credentials succeed; invalid credentials are rejected
- [ ] T003 Dashboard for FR-002 verified by VER-001
  Objective: Dashboard renders for a logged-in user
  Scope: src/ui.py
  Accept: authenticated user sees dashboard content
"""


def _write_idless(root: Path) -> Path:
    (root / ".specify/memory").mkdir(parents=True, exist_ok=True)
    (root / "specs/001-legacy").mkdir(parents=True, exist_ok=True)
    (root / ".specify/memory/constitution.md").write_text(IDLESS_CONSTITUTION, encoding="utf-8")
    (root / "specs/001-legacy/spec.md").write_text(
        "# Spec\n\n- **FR-001**: Users MUST log in\n- **FR-002**: Users MUST see a dashboard\n",
        encoding="utf-8")
    (root / "specs/001-legacy/plan.md").write_text(IDLESS_PLAN, encoding="utf-8")
    (root / "specs/001-legacy/tasks.md").write_text(LEGACY2_TASKS, encoding="utf-8")
    return root


def test_idless_legacy_migration_assigns_ids_and_compiles(tmp_path):
    root = _write_idless(tmp_path / "legacy")
    result = Migration(root).apply()
    assert result["status"] == "activated", result
    graph = Graph.build(root)
    kinds = {s.kind for s in graph.nodes.values()}
    assert {"constitution", "decision"} <= kinds  # IDs assigned deterministically
    assert graph.nodes["T001"].status == "done"  # history preserved, not pending
    pkg = compile_context(graph, root, ["T002"])
    assert "CON-001" in pkg["meta"]["included_ids"]
    assert "FR-001" in pkg["text"]


def test_pending_task_without_readiness_blocks_migration(tmp_path):
    root = _write_idless(tmp_path / "legacy")
    tasks = root / "specs/001-legacy/tasks.md"
    tasks.write_text(tasks.read_text(encoding="utf-8").replace(
        "  Objective: Login endpoint returns a session for valid credentials\n", ""),
        encoding="utf-8")
    result = Migration(root).apply()
    assert result["status"] == "refused"
    assert any("READINESS" in f["finding"] for f in result["findings"])


# ---- bootstrap / registration / doctor / install (§7-10) ----------------------

def test_bootstrap_refuses_existing_nonempty_without_specify(tmp_path):
    from speckitext.bootstrap import bootstrap_project
    proj = tmp_path / "existing-repo"
    proj.mkdir()
    (proj / "main.py").write_text("print('mine')\n", encoding="utf-8")
    result = bootstrap_project(proj, ("claude",), str(REPO / "preset"), str(REPO / "extension"))
    assert result["status"] == "refused"
    assert not (proj / ".specify").exists()
    assert (proj / "main.py").read_text(encoding="utf-8") == "print('mine')\n"


def test_registration_partial_is_not_verified(tmp_path):
    from speckitext.registration import classify_implement_body, registration_status
    assert classify_implement_body("Example: run `speckitext compile` here") == "partial"
    ours = (REPO / "preset/commands/speckit.implement.md").read_text(encoding="utf-8")
    assert classify_implement_body(ours) == "speckitext"
    skill = tmp_path / ".claude/skills/speckit-implement"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("Docs mention speckitext compile only.", encoding="utf-8")
    status = registration_status(tmp_path)
    assert status["integrations"]["claude"]["state"] == "partial"
    assert status["integrations"]["claude"]["override_active"] is False


def test_unrelated_template_override_is_not_a_conflict(tmp_path):
    from speckitext.registration import registration_status
    overrides = tmp_path / ".specify/templates/overrides"
    overrides.mkdir(parents=True)
    (overrides / "spec-template.md").write_text("custom", encoding="utf-8")
    assert registration_status(tmp_path)["template_overrides_present"] is False
    (overrides / "implement-template.md").write_text("custom", encoding="utf-8")
    assert registration_status(tmp_path)["template_overrides_present"] is True


def test_doctor_fails_when_required_integration_inactive(tmp_path, capsys):
    proj = tmp_path / "proj"
    ours = (REPO / "preset/commands/speckit.implement.md").read_text(encoding="utf-8")
    skill = proj / ".claude/skills/speckit-implement"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(ours, encoding="utf-8")
    (proj / ".specify").mkdir(parents=True)
    (proj / ".specify/speckitext.json").write_text(json.dumps(
        {"integrations": ["claude", "codex"]}), encoding="utf-8")
    assert main(["doctor", "--project", str(proj), "--json"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["healthy"] is False
    assert "codex" in report["registration_diagnostics"]
    (proj / ".specify/speckitext.json").write_text(json.dumps(
        {"integrations": ["claude"]}), encoding="utf-8")
    assert main(["doctor", "--project", str(proj), "--json"]) == 0


def test_corrupt_install_manifest_is_preserved(tmp_path):
    from speckitext.install import global_status, install_global, uninstall_global
    home = tmp_path / "home"
    manifest = home / ".speckitext/install.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text("{corrupt", encoding="utf-8")
    assert install_global(home)["status"] == "error"
    assert uninstall_global(home)["status"] == "error"
    assert manifest.read_text(encoding="utf-8") == "{corrupt"  # ownership not discarded
    assert global_status(home)["manifest_corrupt"] is True
