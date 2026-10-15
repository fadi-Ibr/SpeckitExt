"""End-to-end identity lifecycle: migration enrollment, normal development,
explicit identity change, structural failures, multi-feature, integration,
recovery. Disposable synthetic projects driven through real CLI entry
points only."""
import hashlib
import json
import re
import shutil
from pathlib import Path

import pytest

from speckitext.cli import main
from speckitext.compiler import package_staleness
from speckitext.graph import Graph
from speckitext.validate import validate_graph
from tests.test_migration import write_legacy

REPO = Path(__file__).resolve().parent.parent


def _map_path(root):
    return root / ".speckitext/identity.json"


def _map(root):
    return json.loads(_map_path(root).read_text(encoding="utf-8"))


def _save_map(root, data):
    _map_path(root).write_text(json.dumps(data), encoding="utf-8")


def _hash(root):
    return hashlib.sha256(_map_path(root).read_bytes()).hexdigest()


def _migrated(root):
    write_legacy(root)
    assert main(["migrate", "--project", str(root), "--apply"]) == 0
    assert _map_path(root).is_file()
    return root


def _canons(root):
    return sorted(e["canonical_id"] for e in _map(root)["entities"])


def _task(tid, feat="001-legacy", status=" "):
    return (f"- [{status}] {tid} Extra work for FR-001\n<!-- speckitext\nid: {tid}\nkind: task\n"
            f"canonical_id: {feat}::{tid}\nsatisfies: FR-001\nverified_by: VER-001\nfeature: {feat}\n-->\n"
            "  Objective: Extra work completes requirement one observably\n"
            "  Scope: src/extra.py\n  Accept: requirement one behaviour is observable\n")


def _append(root, text, feat="001-legacy"):
    p = root / f"specs/{feat}/tasks.md"
    p.write_text(p.read_text(encoding="utf-8") + text, encoding="utf-8")


def _remove_block(root, tid, feat="001-legacy"):
    p = root / f"specs/{feat}/tasks.md"
    text = re.sub(rf"- \[[ xX]\] {tid}.*?(?=\n- \[|\Z)", "", p.read_text(encoding="utf-8"), flags=re.S)
    p.write_text(text, encoding="utf-8")


def _diags(root):
    return validate_graph(Graph.build(root))


def _codes(root, severity="error"):
    return [d.code for d in _diags(root) if d.severity == severity]


def _enrolled_t004(root):
    _migrated(root)
    _append(root, _task("T004"))
    assert main(["identity", "sync", "--project", str(root)]) == 0
    assert "001-legacy::T004" in _canons(root)
    return root


# ---- A. initial lifecycle ---------------------------------------------------

def test_initial_lifecycle_sync_idempotent(tmp_path):
    root = _migrated(tmp_path / "p")
    assert main(["validate", "--project", str(root)]) == 0
    before = _hash(root)
    assert main(["identity", "sync", "--project", str(root), "--dry-run"]) == 0
    assert _hash(root) == before
    assert main(["identity", "sync", "--project", str(root)]) == 0
    assert main(["identity", "sync", "--project", str(root)]) == 0
    assert _hash(root) == before  # migration output already canonical; sync is a no-op


def test_fresh_structured_project_initial_enrollment(tmp_path, project):
    root = project
    assert not _map_path(root).exists()
    assert main(["identity", "sync", "--project", str(root)]) == 0
    assert _map_path(root).is_file() and _canons(root)
    assert main(["validate", "--project", str(root)]) == 0
    _remove_block(root, "T001", feat="001-demo")
    assert main(["validate", "--project", str(root)]) == 1
    assert "IDENTITY_DISAPPEARED" in _codes(root)


# ---- B. normal development --------------------------------------------------

def test_normal_development_lifecycle(tmp_path):
    root = _migrated(tmp_path / "p")
    _append(root, _task("T004"))
    # Visible but non-blocking until the enrollment checkpoint runs.
    assert "IDENTITY_UNENROLLED" in _codes(root, "warning")
    assert main(["validate", "--project", str(root)]) == 0
    assert main(["identity", "sync", "--project", str(root)]) == 0
    assert "001-legacy::T004" in _canons(root)
    assert "IDENTITY_UNENROLLED" not in _codes(root, "warning")
    h = _hash(root)
    assert main(["identity", "sync", "--project", str(root)]) == 0
    assert _hash(root) == h
    # Complete, edit wording, reorder: identity survives all three.
    tasks = root / "specs/001-legacy/tasks.md"
    text = tasks.read_text(encoding="utf-8").replace("- [ ] T004 Extra work", "- [x] T004 Finished extra work")
    block = re.search(r"- \[[ xX]\] T004.*?(?=\n- \[|\Z)", text, flags=re.S).group(0)
    text = text.replace(block, "").replace("- [x] T001", block + "- [x] T001", 1)
    tasks.write_text(text, encoding="utf-8")
    assert main(["validate", "--project", str(root)]) == 0
    assert main(["identity", "sync", "--project", str(root)]) == 0
    assert "001-legacy::T004" in _canons(root)
    ent = [e for e in _map(root)["entities"] if e["canonical_id"] == "001-legacy::T004"][0]
    assert ent["status"] == "done"


# ---- C. identity change ------------------------------------------------------

def test_enrolled_rename_and_remove_fail_then_reconcile(tmp_path):
    root = _enrolled_t004(tmp_path / "a")
    tasks = root / "specs/001-legacy/tasks.md"
    tasks.write_text(tasks.read_text(encoding="utf-8").replace("T004", "T777"), encoding="utf-8")
    assert main(["validate", "--project", str(root)]) == 1
    assert "IDENTITY_DISAPPEARED" in _codes(root)
    out = tmp_path / "ctx.md"
    assert main(["compile", "--project", str(root), "--tasks", "001-legacy::T002", "--output", str(out)]) == 1
    assert not out.exists()
    m = _map(root)
    m["reconciliations"] = [{"canonical_id": "001-legacy::T004", "action": "reassigned",
                             "replacement": "001-legacy::T777", "reason": "renumbered into the T7xx range"}]
    _save_map(root, m)
    assert main(["validate", "--project", str(root)]) == 0
    assert main(["identity", "sync", "--project", str(root)]) == 0
    canons = _canons(root)
    assert "001-legacy::T004" in canons and "001-legacy::T777" in canons  # history + new identity
    assert _map(root)["reconciliations"] == m["reconciliations"]

    root2 = _enrolled_t004(tmp_path / "b")
    _remove_block(root2, "T004")
    assert main(["validate", "--project", str(root2)]) == 1
    assert "IDENTITY_DISAPPEARED" in _codes(root2)
    m2 = _map(root2)
    m2["reconciliations"] = [{"canonical_id": "001-legacy::T004", "action": "removed",
                              "reason": "work descoped by FR-001 revision"}]
    _save_map(root2, m2)
    assert main(["validate", "--project", str(root2)]) == 0
    assert main(["identity", "sync", "--project", str(root2)]) == 0
    assert "001-legacy::T004" in _canons(root2)  # retired record retained


# ---- D. structural failures ---------------------------------------------------

def test_empty_graph_and_feature_disappearance_fail(tmp_path):
    fresh = tmp_path / "fresh"
    (fresh / ".specify/memory").mkdir(parents=True)
    assert main(["validate", "--project", str(fresh)]) == 0  # genuinely new: nothing expected

    root = _migrated(tmp_path / "p")
    shutil.rmtree(root / "specs")
    (root / ".specify/memory/constitution.md").unlink()
    assert main(["validate", "--project", str(root)]) == 1
    assert "IDENTITY_DISAPPEARED" in _codes(root)

    root2 = tmp_path / "q"
    write_legacy(root2)
    shutil.copytree(root2 / "specs/001-legacy", root2 / "specs/002-beta")
    assert main(["migrate", "--project", str(root2), "--apply"]) == 0
    shutil.rmtree(root2 / "specs/002-beta")
    assert main(["validate", "--project", str(root2)]) == 1
    gone = [d.node_id for d in _diags(root2) if d.code == "IDENTITY_DISAPPEARED"]
    assert gone and all(x.startswith("002-beta::") for x in gone)


def test_missing_identity_map_after_migration_fails(tmp_path):
    root = _migrated(tmp_path / "p")
    _map_path(root).unlink()
    assert "IDENTITY_MAP_MISSING" in _codes(root)
    assert main(["validate", "--project", str(root)]) == 1
    assert main(["identity", "sync", "--project", str(root)]) == 1
    assert not _map_path(root).exists()  # sync must not silently re-create provenance


def test_retirement_bypasses_rejected(tmp_path):
    # Entity-level marker alone carries no authority.
    root = _enrolled_t004(tmp_path / "a")
    _remove_block(root, "T004")
    m = _map(root)
    for e in m["entities"]:
        if e["canonical_id"] == "001-legacy::T004":
            e["retired"] = True
    _save_map(root, m)
    assert main(["validate", "--project", str(root)]) == 1
    assert "IDENTITY_DISAPPEARED" in _codes(root)

    # Alias keys and missing reason are rejected at full strength.
    root2 = _enrolled_t004(tmp_path / "b")
    _remove_block(root2, "T004")
    m2 = _map(root2)
    m2["reconciliations"] = [{"from": "001-legacy::T004", "action": "removed", "reason": "alias form"}]
    _save_map(root2, m2)
    assert main(["validate", "--project", str(root2)]) == 1

    root3 = _enrolled_t004(tmp_path / "c")
    _remove_block(root3, "T004")
    m3 = _map(root3)
    m3["reconciliations"] = [{"canonical_id": "001-legacy::T004", "action": "removed", "replacement": "001-legacy::T002", "reason": "x"}]
    _save_map(root3, m3)
    assert main(["validate", "--project", str(root3)]) == 1  # replacement forbidden for removed


def test_reconciliation_conflicts_chains_cycles_reuse(tmp_path):
    # Dangling chain: T004 -> T777 -> T888 leaves T004 pointing at a retired ID.
    root = _enrolled_t004(tmp_path / "a")
    tasks = root / "specs/001-legacy/tasks.md"
    tasks.write_text(tasks.read_text(encoding="utf-8").replace("T004", "T777"), encoding="utf-8")
    m = _map(root)
    m["reconciliations"] = [{"canonical_id": "001-legacy::T004", "action": "reassigned",
                             "replacement": "001-legacy::T777", "reason": "first rename"}]
    _save_map(root, m)
    assert main(["identity", "sync", "--project", str(root)]) == 0
    tasks.write_text(tasks.read_text(encoding="utf-8").replace("T777", "T888"), encoding="utf-8")
    m = _map(root)
    m["reconciliations"].append({"canonical_id": "001-legacy::T777", "action": "reassigned",
                                 "replacement": "001-legacy::T888", "reason": "second rename"})
    _save_map(root, m)
    assert main(["validate", "--project", str(root)]) == 1
    codes = _codes(root)
    assert any(c.startswith("IDENTITY_RECONCILIATION") for c in codes), codes

    # Cycle: both retired, each naming the other.
    m = _map(root)
    m["reconciliations"] = [
        {"canonical_id": "001-legacy::T004", "action": "reassigned", "replacement": "001-legacy::T777", "reason": "cycle a"},
        {"canonical_id": "001-legacy::T777", "action": "reassigned", "replacement": "001-legacy::T004", "reason": "cycle b"}]
    _save_map(root, m)
    assert main(["validate", "--project", str(root)]) == 1
    assert any(c.startswith("IDENTITY_RECONCILIATION") for c in _codes(root))

    # Reuse of a retired identity while its reconciliation stands.
    root2 = _enrolled_t004(tmp_path / "b")
    _remove_block(root2, "T004")
    m2 = _map(root2)
    m2["reconciliations"] = [{"canonical_id": "001-legacy::T004", "action": "removed", "reason": "descoped"}]
    _save_map(root2, m2)
    assert main(["validate", "--project", str(root2)]) == 0
    _append(root2, _task("T004"))
    assert main(["validate", "--project", str(root2)]) == 1
    assert "IDENTITY_RECONCILIATION_CONFLICT" in _codes(root2)


def test_sync_refuses_corrupt_and_disappearance(tmp_path):
    root = _enrolled_t004(tmp_path / "a")
    _map_path(root).write_text("{corrupt", encoding="utf-8")
    assert main(["identity", "sync", "--project", str(root)]) == 1
    assert _map_path(root).read_text(encoding="utf-8") == "{corrupt"

    root2 = _enrolled_t004(tmp_path / "b")
    before = _hash(root2)
    _remove_block(root2, "T004")
    assert main(["identity", "sync", "--project", str(root2)]) == 1
    assert _hash(root2) == before  # deletion never laundered into a removal


# ---- E. multi-feature ----------------------------------------------------------

def test_multi_feature_enrollment_rename_and_no_inference(tmp_path):
    root = tmp_path / "p"
    write_legacy(root)
    shutil.copytree(root / "specs/001-legacy", root / "specs/002-beta")
    assert main(["migrate", "--project", str(root), "--apply"]) == 0
    _append(root, _task("T050", "001-legacy"), "001-legacy")
    _append(root, _task("T050", "002-beta"), "002-beta")
    assert main(["identity", "sync", "--project", str(root)]) == 0
    canons = _canons(root)
    assert "001-legacy::T050" in canons and "002-beta::T050" in canons
    assert "001-legacy::T001" in canons and "002-beta::T001" in canons
    # Removing one feature's T050 is never explained by the other's existence.
    _remove_block(root, "T050", "001-legacy")
    assert main(["validate", "--project", str(root)]) == 1
    assert "001-legacy::T050" in [d.node_id for d in _diags(root) if d.code == "IDENTITY_DISAPPEARED"]
    # Restore, then rename the other feature directory with preserved identity.
    _append(root, _task("T050", "001-legacy"), "001-legacy")
    assert main(["validate", "--project", str(root)]) == 0
    shutil.move(str(root / "specs/002-beta"), str(root / "specs/009-renamed"))
    m = _map(root)
    m["features"]["009-renamed"] = "002-beta"
    _save_map(root, m)
    # Authored metadata still declares feature 002-beta under the new directory.
    assert main(["validate", "--project", str(root)]) == 0
    assert main(["identity", "sync", "--project", str(root)]) == 0
    assert "002-beta::T050" in _canons(root)


# ---- F. integration ---------------------------------------------------------------

def test_compile_staleness_batch_impact_after_identity_change(tmp_path):
    root = _enrolled_t004(tmp_path / "p")
    pkg = tmp_path / "pkg.md"
    assert main(["compile", "--project", str(root), "--tasks", "001-legacy::T004", "--output", str(pkg)]) == 0
    assert "001-legacy::T004" in pkg.read_text(encoding="utf-8")
    assert package_staleness(Graph.build(root), pkg) == []
    assert main(["batch", "suggest", "--project", str(root)]) == 0
    assert main(["impact", "--project", str(root), "--ids", "001-legacy::FR-001"]) == 0
    tasks = root / "specs/001-legacy/tasks.md"
    tasks.write_text(tasks.read_text(encoding="utf-8").replace("T004", "T777"), encoding="utf-8")
    m = _map(root)
    m["reconciliations"] = [{"canonical_id": "001-legacy::T004", "action": "reassigned",
                             "replacement": "001-legacy::T777", "reason": "renumbered"}]
    _save_map(root, m)
    assert main(["identity", "sync", "--project", str(root)]) == 0
    stale = package_staleness(Graph.build(root), pkg)
    assert any(s["id"] == "001-legacy::T004" for s in stale)


def test_read_only_commands_never_mutate_identity_map(tmp_path):
    root = _enrolled_t004(tmp_path / "p")
    _append(root, _task("T005"))  # unenrolled: read-only ops must not enroll it
    before = _hash(root)
    pkg = tmp_path / "pkg.md"
    assert main(["validate", "--project", str(root)]) == 0
    assert main(["compile", "--project", str(root), "--tasks", "001-legacy::T002", "--output", str(pkg)]) == 0
    assert main(["batch", "suggest", "--project", str(root)]) == 0
    assert main(["impact", "--project", str(root), "--ids", "001-legacy::FR-001"]) == 0
    main(["doctor", "--json"])
    assert main(["identity", "sync", "--project", str(root), "--dry-run"]) == 0
    assert main(["migrate", "--project", str(root), "--dry-run"]) in (0, 1)
    assert _hash(root) == before
    assert not (root / ".speckitext/identity.json.tmp").exists()
    assert "001-legacy::T005" not in _canons(root)


def test_authoring_checkpoint_integration():
    tasks_cmd = (REPO / "preset/commands/speckit.tasks.md").read_text(encoding="utf-8")
    assert "speckitext identity sync" in tasks_cmd
    assert tasks_cmd.index("speckitext identity sync") < tasks_cmd.index("speckitext validate")
    yml = (REPO / "extension/extension.yml").read_text(encoding="utf-8")
    assert "speckit.traceability.identity" in yml
    cmd = REPO / "extension/commands/speckit.traceability.identity.md"
    assert cmd.is_file() and "speckitext identity sync" in cmd.read_text(encoding="utf-8")


# ---- G. recovery ---------------------------------------------------------------------

def test_failed_enrollment_is_atomic_and_retryable(tmp_path, monkeypatch):
    import speckitext.identity as identity
    root = _enrolled_t004(tmp_path / "p")
    _append(root, _task("T005"))
    before = _map_path(root).read_bytes()

    def _boom(src, dst):
        raise OSError("simulated crash during replace")

    monkeypatch.setattr(identity.os, "replace", _boom)
    assert main(["identity", "sync", "--project", str(root)]) == 1
    assert _map_path(root).read_bytes() == before
    assert not (root / ".speckitext/identity.json.tmp").exists()
    monkeypatch.undo()
    assert main(["identity", "sync", "--project", str(root)]) == 0
    assert "001-legacy::T005" in _canons(root)
    h = _hash(root)
    assert main(["identity", "sync", "--project", str(root)]) == 0
    assert _hash(root) == h
