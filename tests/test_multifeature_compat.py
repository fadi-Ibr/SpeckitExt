"""Synthetic multi-feature compatibility: duplicate locals, legacy IDs,
ID-less tasks, ambiguity, migration inventory/mapping/transactions.
Disposable fixtures only; no real project files."""
import json
from pathlib import Path

import pytest

from speckitext.batch import suggest_batches
from speckitext.cli import main
from speckitext.compiler import CompileError, compile_context, package_staleness, read_package_meta
from speckitext.graph import Graph
from speckitext.identity import load_identity_map
from speckitext.impact import impact_for_ids
from speckitext.migration import Migration, MigrationCrash, incomplete_migrations
from speckitext.parsing import parse_text
from speckitext.validate import validate_all, validate_graph

CON = """# Constitution
### CON-001: Global quality
<!-- speckitext
id: CON-001
kind: constitution
applicability: GLOBAL
-->
All work is tested.
### CON-002: Alpha component rule
<!-- speckitext
id: CON-002
kind: constitution
applicability: SCOPED
scope: COMP-001
-->
Alpha component rule.
"""


def _spec(feat, extra=""):
    return f"""# Spec {feat}
- **FR-001**: Requirement one for {feat}
<!-- speckitext
id: FR-001
kind: requirement
governed_by: CON-001
feature: {feat}
-->
- **FR-002**: Requirement two for {feat}
<!-- speckitext
id: FR-002
kind: requirement
governed_by: CON-001
feature: {feat}
-->
{extra}"""


def _tasks(feat, ver="VER-001"):
    return f"""# Tasks {feat}
### {ver}: Checks
<!-- speckitext
id: {ver}
kind: verification
feature: {feat}
-->
Run: pytest tests/ -q
- [x] T001 Done task for FR-001
<!-- speckitext
id: T001
kind: task
satisfies: FR-001
verified_by: {ver}
feature: {feat}
-->
- [ ] T002 Pending task for FR-001
<!-- speckitext
id: T002
kind: task
satisfies: FR-001, FR-002
verified_by: {ver}
feature: {feat}
-->
  Objective: Pending work completes requirement one fully
  Scope: src/{feat}.py
  Accept: requirement one behaviour is observable and tested
"""


def write_structured(root: Path) -> Path:
    (root / ".specify/memory").mkdir(parents=True, exist_ok=True)
    (root / ".specify/memory/constitution.md").write_text(CON, encoding="utf-8")
    for feat in ("001-alpha", "002-beta"):
        d = root / "specs" / feat
        d.mkdir(parents=True, exist_ok=True)
        (d / "spec.md").write_text(_spec(feat), encoding="utf-8")
        (d / "tasks.md").write_text(_tasks(feat), encoding="utf-8")
    # alpha plan with component for scoped governance
    (root / "specs/001-alpha/plan.md").write_text(
        "# Plan\n### COMP-001: Alpha component\n<!-- speckitext\nid: COMP-001\n"
        "kind: component\ngoverned_by: CON-001\nfeature: 001-alpha\n-->\nOwns src/001-alpha.py\n",
        encoding="utf-8")
    # gamma: legacy task IDs
    d = root / "specs/003-gamma"; d.mkdir(parents=True, exist_ok=True)
    (d / "spec.md").write_text(_spec("003-gamma"), encoding="utf-8")
    (d / "tasks.md").write_text("""# Tasks 003-gamma
### VER-001: Checks
<!-- speckitext
id: VER-001
kind: verification
feature: 003-gamma
-->
Run: pytest tests/ -q
- [x] T070E Legacy done for FR-001
<!-- speckitext
id: T070E
kind: task
satisfies: FR-001
verified_by: VER-001
feature: 003-gamma
-->
- [ ] G5-T1 Legacy pending for FR-001
<!-- speckitext
id: G5-T1
kind: task
satisfies: FR-001
verified_by: VER-001
feature: 003-gamma
-->
  Objective: Legacy pending work completes requirement one
  Scope: src/gamma.py
  Accept: requirement one behaviour is observable and tested
- [ ] TR-A Another legacy pending for FR-002
<!-- speckitext
id: TR-A
kind: task
satisfies: FR-002
verified_by: VER-001
feature: 003-gamma
-->
  Objective: Second legacy task completes requirement two
  Scope: src/gamma2.py
  Accept: requirement two behaviour is observable and tested
""", encoding="utf-8")
    # delta: custom structured ID + pending
    d = root / "specs/004-delta"; d.mkdir(parents=True, exist_ok=True)
    (d / "spec.md").write_text(_spec("004-delta"), encoding="utf-8")
    (d / "tasks.md").write_text("""# Tasks 004-delta
### VER-001: Checks
<!-- speckitext
id: VER-001
kind: verification
feature: 004-delta
-->
Run: pytest tests/ -q
- [x] T001 Delta done for FR-001
<!-- speckitext
id: T001
kind: task
satisfies: FR-001
verified_by: VER-001
feature: 004-delta
-->
- [ ] DELTA-SETUP Custom pending for FR-001
<!-- speckitext
id: DELTA-SETUP
kind: task
satisfies: FR-001, FR-002
verified_by: VER-001
feature: 004-delta
-->
  Objective: Custom-id pending work completes requirement one
  Scope: src/delta.py
  Accept: requirement one behaviour is observable and tested
""", encoding="utf-8")
    # omega: unrelated feature
    d = root / "specs/005-omega"; d.mkdir(parents=True, exist_ok=True)
    (d / "spec.md").write_text(_spec("005-omega"), encoding="utf-8")
    (d / "tasks.md").write_text(_tasks("005-omega"), encoding="utf-8")
    # explicit cross-feature dependency: beta T002 depends on alpha T001
    beta = root / "specs/002-beta/tasks.md"
    beta.write_text(beta.read_text(encoding="utf-8").replace(
        "verified_by: VER-001\nfeature: 002-beta\n-->\n  Objective: Pending",
        "verified_by: VER-001\ndepends_on: 001-alpha::T001\nfeature: 002-beta\n-->\n  Objective: Pending"),
        encoding="utf-8")
    return root


# ---------- parsing / identity ----------
def test_parse_legacy_and_idless():
    doc = parse_text("- [ ] T070E Do x\n- [x] G5-T1 Do y\n- [ ] TR-A Do z\n"
                     "- [ ] Plain task with no identifier at all\n", "specs/009-x/tasks.md")
    locals_ = [s.local_id for s in doc.sections]
    assert locals_[:3] == ["T070E", "G5-T1", "TR-A"]
    assert doc.sections[3].id_missing and doc.sections[3].local_id.startswith("T-AUTO-")
    assert len({s.node_id for s in doc.sections}) == 4
    assert doc.task_occurrences == 4


def test_structured_multifeature_graph(tmp_path):
    root = write_structured(tmp_path / "p")
    g = Graph.build(root)
    assert "001-alpha::T001" in g.nodes and "002-beta::T001" in g.nodes
    assert g.nodes["001-alpha::T001"] is not g.nodes["002-beta::T001"]
    assert g.nodes["001-alpha::FR-001"].local_id == "FR-001"
    assert g.nodes["003-gamma::G5-T1"].legacy_alias == "G5-T1"
    assert not [d for d in validate_graph(g) if d.severity == "error"], validate_graph(g)


def test_same_feature_resolution_and_cross_feature(tmp_path):
    root = write_structured(tmp_path / "p")
    g = Graph.build(root)
    # alpha T002 satisfies alpha FR-001, not beta's
    assert "001-alpha::FR-001" in g.targets("001-alpha::T002", "satisfies") and "002-beta::FR-001" not in g.targets("001-alpha::T002", "satisfies")
    assert "002-beta::FR-001" in g.targets("002-beta::T002", "satisfies")
    # explicit qualified cross-feature dependency resolves
    assert "001-alpha::T001" in g.targets("002-beta::T002", "depends_on")


def test_compile_scoped_no_leakage_and_governance(tmp_path):
    root = write_structured(tmp_path / "p")
    g = Graph.build(root)
    r = compile_context(g, root, ["T002"], feature="001-alpha")
    ids = r["meta"]["included_ids"]
    assert "001-alpha::T002" in ids and "CON-001" in ids
    assert not any(x.startswith(("002-beta::", "005-omega::", "003-gamma::")) for x in ids)
    assert r["meta"]["selected_tasks"] == ["001-alpha::T002"]
    ident = {i["canonical_id"]: i for i in r["meta"]["identity"]}
    assert ident["001-alpha::T002"]["local_id"] == "T002"
    # batch compilation
    r2 = compile_context(g, root, ["001-alpha::T002", "002-beta::T002"])
    assert set(r2["meta"]["selected_tasks"]) == {"001-alpha::T002", "002-beta::T002"}


def test_ambiguous_selection_and_batch_impact(tmp_path):
    root = write_structured(tmp_path / "p")
    g = Graph.build(root)
    with pytest.raises(CompileError, match="ambiguous"):
        compile_context(g, root, ["T001"])
    batches = suggest_batches(g)
    all_tasks = [t for b in batches for t in b["tasks"]]
    assert "001-alpha::T002" in all_tasks and "002-beta::T002" in all_tasks
    assert all(b["task_details"] for b in batches)
    imp = impact_for_ids(g, ["001-alpha::FR-001"])
    assert "001-alpha::T002" in imp["affected"] and "002-beta::T001" not in imp["affected"]  # beta T002 is affected only via its explicit alpha dependency
    assert imp["affected_details"]


def test_stable_ids_after_completion_and_edit(tmp_path):
    root = write_structured(tmp_path / "p")
    before = Graph.build(root).nodes["001-alpha::T002"].node_id
    tasks = root / "specs/001-alpha/tasks.md"
    txt = tasks.read_text(encoding="utf-8").replace("- [ ] T002", "- [x] T002")
    tasks.write_text("\n" + txt, encoding="utf-8")  # reorder/whitespace edit
    g2 = Graph.build(root)
    assert g2.nodes["001-alpha::T002"].node_id == before
    assert g2.nodes["001-alpha::T002"].status == "done"


# ---------- negative graph cases ----------
def _mini(tmp_path, tasks_a, spec_a="- **FR-001**: Req\n<!-- speckitext\nid: FR-001\nkind: requirement\ngoverned_by: CON-001\nfeature: 001-a\n-->\n"):
    root = tmp_path / "p"
    (root / ".specify/memory").mkdir(parents=True, exist_ok=True)
    (root / ".specify/memory/constitution.md").write_text(CON, encoding="utf-8")
    d = root / "specs/001-a"; d.mkdir(parents=True, exist_ok=True)
    (d / "spec.md").write_text(spec_a, encoding="utf-8")
    (d / "tasks.md").write_text(tasks_a, encoding="utf-8")
    return root


def test_duplicate_within_feature_rejected(tmp_path):
    root = _mini(tmp_path, "# T\n### VER-001: C\n<!-- speckitext\nid: VER-001\nkind: verification\nfeature: 001-a\n-->\nRun: pytest -q\n"
                           "- [ ] T001 One for FR-001\n<!-- speckitext\nid: T001\nkind: task\nsatisfies: FR-001\nverified_by: VER-001\nfeature: 001-a\n-->\n"
                           "- [ ] T001 Two for FR-001\n<!-- speckitext\nid: T001\nkind: task\nsatisfies: FR-001\nverified_by: VER-001\nfeature: 001-a\n-->\n")
    codes = [d.code for d in validate_graph(Graph.build(root))]
    assert "DUPLICATE_ID" in codes


def test_conflicting_canonical_and_dangling_and_direction(tmp_path):
    root = _mini(tmp_path, "# T\n### VER-001: C\n<!-- speckitext\nid: VER-001\nkind: verification\nfeature: 001-a\n-->\nRun: pytest -q\n"
                           "- [ ] T001 One for FR-001 depends on 009-nope::T001\n<!-- speckitext\nid: T001\nkind: task\nsatisfies: FR-001\nverified_by: VER-001\ngoverned_by: FR-001\ndepends_on: 009-nope::T001\nfeature: 001-a\n-->\n  Objective: Direction test task does the thing\n  Scope: src/a.py\n  Accept: thing is done and verified\n")
    codes = [d.code for d in validate_all(Graph.build(root))]
    assert "UNRESOLVED_REFERENCE" in codes and "INVALID_RELATION_DIRECTION" in codes


def test_ambiguous_cross_feature_reference(tmp_path):
    root = write_structured(tmp_path / "p")
    # gamma task referencing FR-001 unqualified is fine (same feature), so
    # craft: remove gamma FR-001 by pointing its task at a feature-less ref
    # after deleting gamma spec FR-001 -> two other features provide it.
    spec = root / "specs/003-gamma/spec.md"
    spec.write_text("# Spec\n- **FR-002**: Only two\n<!-- speckitext\nid: FR-002\nkind: requirement\ngoverned_by: CON-001\nfeature: 003-gamma\n-->\n", encoding="utf-8")
    codes = [(d.code, d.node_id) for d in validate_graph(Graph.build(root))]
    assert any(c in ("AMBIGUOUS_REFERENCE", "UNRESOLVED_REFERENCE", "CROSS_FEATURE_REFERENCE") for c, _ in codes), codes


def test_unsupported_package_schema(tmp_path):
    root = write_structured(tmp_path / "p")
    g = Graph.build(root)
    pkg = tmp_path / "pkg.md"
    pkg.write_text(compile_context(g, root, ["001-alpha::T002"])["text"], encoding="utf-8")
    pkg.write_text(pkg.read_text(encoding="utf-8").replace('"schema_version":"2.0"', '"schema_version":"1.0"'), encoding="utf-8")
    with pytest.raises(CompileError, match="incompatible package schema"):
        read_package_meta(pkg)
    with pytest.raises(CompileError):
        package_staleness(Graph.build(root), pkg)


def test_corrupt_identity_map_is_error(tmp_path):
    root = write_structured(tmp_path / "p")
    (root / ".speckitext").mkdir(exist_ok=True)
    (root / ".speckitext/identity.json").write_text("{corrupt", encoding="utf-8")
    assert load_identity_map(root).get("corrupt")


# ---------- legacy migration ----------
LEGACY_CON = "# Constitution\n\n### CON-001: Quality\nAll work is tested.\n"


def _legacy_feature(root, feat, tasks, two=False):
    d = root / "specs" / feat; d.mkdir(parents=True, exist_ok=True)
    spec = "# Spec\n\n- **FR-001**: Requirement one\n" + ("- **FR-002**: Requirement two\n" if two else "")
    (d / "spec.md").write_text(spec, encoding="utf-8")
    (d / "tasks.md").write_text(tasks, encoding="utf-8")


def write_legacy(root: Path) -> Path:
    (root / ".specify/memory").mkdir(parents=True, exist_ok=True)
    (root / ".specify/memory/constitution.md").write_text(LEGACY_CON, encoding="utf-8")
    head = "### VER-001: Checks\nRun: pytest tests/ -q\n\n"
    _legacy_feature(root, "001-alpha", "# Tasks\n\n" + head +
                    "- [x] T001 Alpha done for FR-001 verified by VER-001\n"
                    "- [ ] T002 Alpha pending for FR-001 verified by VER-001 (depends on T001)\n  Objective: Alpha pending completes requirement one\n  Scope: src/alpha.py\n  Accept: requirement one is observable\n")
    _legacy_feature(root, "002-beta", "# Tasks\n\n" + head +
                    "- [x] T001 Beta done for FR-001 verified by VER-001\n"
                    "- [ ] T002 Beta pending for FR-001 verified by VER-001 (depends on T001)\n  Objective: Beta pending completes requirement one\n  Scope: src/beta.py\n  Accept: requirement one is observable\n")
    _legacy_feature(root, "003-gamma", "# Tasks\n\n" + head +
                    "- [x] T070E Gamma legacy done for FR-001 verified by VER-001\n"
                    "- [ ] G5-T1 Gamma legacy pending for FR-001 verified by VER-001\n  Objective: Gamma legacy pending completes requirement one\n  Scope: src/gamma.py\n  Accept: requirement one is observable\n"
                    "- [ ] PL-C Gamma second legacy for FR-002 verified by VER-001\n  Objective: Gamma second legacy completes requirement two\n  Scope: src/gamma2.py\n  Accept: requirement two is observable\n", two=True)
    _legacy_feature(root, "004-delta", "# Tasks\n\n" + head +
                    "- [x] Delta setup done for FR-001 verified by VER-001\n"
                    "- [ ] Delta export pending for FR-001 verified by VER-001\n  Objective: Delta export completes requirement one\n  Scope: src/delta.py\n  Accept: requirement one is observable\n")
    return root


def test_legacy_migration_inventory_and_mapping(tmp_path):
    root = write_legacy(tmp_path / "legacy")
    plan = Migration(root).plan()
    assert plan["task_occurrences"] == 9 and plan["canonical_task_count"] == 9, plan["findings"]
    assert not plan["findings"], plan["findings"]
    feats = {e["feature"] for e in plan["inventory"]}
    assert {"001-alpha", "002-beta", "003-gamma", "004-delta"} <= feats
    result = Migration(root).apply()
    assert result["status"] == "activated", result
    mapping = json.loads((root / ".speckitext/identity.json").read_text(encoding="utf-8"))
    tasks = [e for e in mapping["entities"] if e["kind"] == "task"]
    assert len(tasks) == 9 and len({e["canonical_id"] for e in tasks}) == 9
    assert {e["legacy_alias"] for e in tasks} >= {"T001", "T070E", "G5-T1", "PL-C"}
    g = Graph.build(root)
    assert g.nodes["001-alpha::T001"].status == "done"
    assert g.nodes["002-beta::T002"].status == "pending"
    assert not [d for d in validate_graph(g) if d.severity == "error"], validate_graph(g)
    # scoped compile after migration, no leakage
    r = compile_context(g, root, ["T002"], feature="002-beta")
    assert r["meta"]["selected_tasks"] == ["002-beta::T002"]
    assert not any(x.startswith("001-alpha::T") for x in r["meta"]["included_ids"] if x.endswith("T002"))
    assert Migration(root).apply()["status"] == "noop"  # idempotent


def test_migration_rollback_and_recovery_remove_sidecar(tmp_path):
    root = write_legacy(tmp_path / "legacy")
    originals = {p: p.read_bytes() for p in root.rglob("*.md")}
    assert Migration(root).apply()["status"] == "activated"
    assert (root / ".speckitext/identity.json").is_file()
    assert Migration(root).rollback()["status"] == "rolled-back"
    assert not (root / ".speckitext/identity.json").exists()
    for p, data in originals.items():
        assert p.read_bytes() == data


def test_migration_crash_recovery(tmp_path):
    root = write_legacy(tmp_path / "legacy")
    originals = {p: p.read_bytes() for p in root.rglob("*.md")}
    with pytest.raises(MigrationCrash):
        Migration(root).apply(crash_after=1)
    assert incomplete_migrations(root)
    assert Migration(root).recover()["status"] == "recovered"
    assert not (root / ".speckitext/identity.json").exists()
    for p, data in originals.items():
        assert p.read_bytes() == data


def test_migration_failed_activation_restores(tmp_path):
    root = write_legacy(tmp_path / "legacy")
    originals = {p: p.read_bytes() for p in root.rglob("*.md")}
    result = Migration(root).apply(fail_after=1)
    assert result["status"] == "failed-restored"
    assert not (root / ".speckitext/identity.json").exists()
    for p, data in originals.items():
        assert p.read_bytes() == data


def test_migration_duplicate_within_feature_blocks(tmp_path):
    root = write_legacy(tmp_path / "legacy")
    tasks = root / "specs/001-alpha/tasks.md"
    tasks.write_text(tasks.read_text(encoding="utf-8") +
                     "- [ ] T002 Duplicate pending for FR-001 verified by VER-001\n  Objective: Duplicate task completes requirement one\n  Scope: src/dup.py\n  Accept: requirement one is observable\n",
                     encoding="utf-8")
    plan = Migration(root).plan()
    assert plan["findings"]  # duplicate / coverage mismatch must block
    assert Migration(root).apply()["status"] == "refused"


def test_cli_compile_feature_and_ambiguous(tmp_path, capsys):
    root = write_structured(tmp_path / "p")
    out = tmp_path / "ctx.md"
    assert main(["compile", "--project", str(root), "--feature", "001-alpha",
                 "--tasks", "T002", "--output", str(out)]) == 0
    assert "001-alpha::T002" in out.read_text(encoding="utf-8")
    assert main(["compile", "--project", str(root), "--tasks", "T001",
                 "--output", str(out)]) == 1  # ambiguous, never arbitrary
