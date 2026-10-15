"""Repairs: checklist/task separation, governance scoping, identity-map
integrity, canonical ownership. Disposable synthetic fixtures only."""
import json
from pathlib import Path

import pytest

from speckitext.batch import suggest_batches
from speckitext.cli import main
from speckitext.compiler import CompileError, compile_context, package_staleness
from speckitext.graph import Graph
from speckitext.migration import Migration
from speckitext.parsing import parse_text
from speckitext.validate import validate_all, validate_graph

CON_HEAD = "# Constitution\n"
def _con(rules):
    out = [CON_HEAD]
    for cid, app, extra, body in rules:
        out.append(f"### {cid}: {body}\n<!-- speckitext\nid: {cid}\nkind: constitution\napplicability: {app}\n{extra}-->\n{body}.\n")
    return "".join(out)

GLOBAL_CON = _con([("CON-001", "GLOBAL", "", "Global quality")])

def _feature(root, feat, comp=False, task_extra=""):
    d = root / "specs" / feat
    d.mkdir(parents=True, exist_ok=True)
    (d / "spec.md").write_text(
        f"# Spec\n- **FR-001**: Req one\n<!-- speckitext\nid: FR-001\nkind: requirement\ngoverned_by: CON-001\nfeature: {feat}\n-->\n", encoding="utf-8")
    (d / "tasks.md").write_text(
        f"# Tasks\n### VER-001: Checks\n<!-- speckitext\nid: VER-001\nkind: verification\nfeature: {feat}\n-->\nRun: pytest -q\n"
        f"- [x] T001 Done for FR-001\n<!-- speckitext\nid: T001\nkind: task\ncanonical_id: {feat}::T001\nsatisfies: FR-001\nverified_by: VER-001\nfeature: {feat}\n{task_extra}-->\n"
        f"- [ ] T002 Pending for FR-001\n<!-- speckitext\nid: T002\nkind: task\ncanonical_id: {feat}::T002\nsatisfies: FR-001\nverified_by: VER-001\nfeature: {feat}\n{task_extra}-->\n"
        "  Objective: Pending work completes requirement one fully\n  Scope: src/x.py\n  Accept: requirement one is observable\n", encoding="utf-8")
    if comp:
        (d / "plan.md").write_text(
            f"# Plan\n### COMP-001: Component\n<!-- speckitext\nid: COMP-001\nkind: component\ngoverned_by: CON-001\nfeature: {feat}\n-->\nOwns src/x.py\n", encoding="utf-8")
    return d

def _valid_project(root, con=GLOBAL_CON):
    (root / ".specify/memory").mkdir(parents=True, exist_ok=True)
    (root / ".specify/memory/constitution.md").write_text(con, encoding="utf-8")
    _feature(root, "001-alpha")
    return root

def _codes(root):
    return [d.code for d in validate_graph(Graph.build(root))]

# ---- 1. checklist separation ----
def test_checklist_items_never_become_tasks(tmp_path):
    root = _valid_project(tmp_path / "p")
    # add a third task (pending, legacy id) -> total 3 tasks: T001 done, T002 + G5-T1 pending
    tasks = root / "specs/001-alpha/tasks.md"
    tasks.write_text(tasks.read_text(encoding="utf-8") +
        "- [ ] G5-T1 Legacy pending for FR-001\n<!-- speckitext\nid: G5-T1\nkind: task\ncanonical_id: 001-alpha::G5-T1\nsatisfies: FR-001\nverified_by: VER-001\nfeature: 001-alpha\n-->\n  Objective: Legacy work completes requirement one\n  Scope: src/y.py\n  Accept: requirement one is observable\n", encoding="utf-8")
    chk = root / "specs/001-alpha/checklists"
    chk.mkdir()
    chk_text = "# Checklist\n- [x] CHK001 Are acceptance criteria measurable?\n- [x] CHK002 Are requirements unambiguous?\n- [ ] CHK003 Are edge cases documented?\n- [ ] CHK004 Are dependencies identified?\n"
    (chk / "requirements.md").write_text(chk_text, encoding="utf-8")
    g = Graph.build(root)
    tasks_found = sorted(n for n, s in g.nodes.items() if s.kind == "task")
    assert tasks_found == ["001-alpha::G5-T1", "001-alpha::T001", "001-alpha::T002"]
    assert not any("CHK" in n for n in g.nodes)
    doc = parse_text(chk_text, "specs/001-alpha/checklists/requirements.md")
    assert doc.task_occurrences == 0 and doc.checklist_occurrences == 4
    assert doc.checklist_completed == 2 and doc.checklist_pending == 2
    task_doc = parse_text(tasks.read_text(encoding="utf-8"), "specs/001-alpha/tasks.md")
    assert task_doc.task_occurrences == 3
    assert sum(1 for s in g.nodes.values() if s.kind == "task" and s.status == "done") == 1
    assert sum(1 for s in g.nodes.values() if s.kind == "task" and s.status != "done") == 2
    batches = suggest_batches(g)
    assert {t for b in batches for t in b["tasks"]} == {"001-alpha::T002", "001-alpha::G5-T1"}
    assert (chk / "requirements.md").read_text(encoding="utf-8") == chk_text

def test_checklist_section_inside_tasks_is_not_a_task():
    doc = parse_text("# Tasks\n- [ ] T001 Real task\n## Checklist\n- [ ] CHK001 Check something\n", "specs/001-a/tasks.md")
    assert [s.local_id for s in doc.sections] == ["T001"]
    assert doc.task_occurrences == 1 and doc.checklist_occurrences == 1

def test_legacy_migration_excludes_checklists_and_preserves_bytes(tmp_path):
    root = tmp_path / "legacy"
    (root / ".specify/memory").mkdir(parents=True)
    (root / ".specify/memory/constitution.md").write_text("# Constitution\n\n### CON-001: Quality\nAll work is tested.\n", encoding="utf-8")
    d = root / "specs/001-alpha"; d.mkdir(parents=True)
    (d / "spec.md").write_text("# Spec\n\n- **FR-001**: Requirement one\n- **FR-002**: Requirement two\n", encoding="utf-8")
    (d / "tasks.md").write_text("# Tasks\n\n### VER-001: Checks\nRun: pytest -q\n\n- [x] T070E Done for FR-001 verified by VER-001\n- [ ] G5-T1 Pending for FR-001 verified by VER-001\n  Objective: Pending work completes requirement one\n  Scope: src/a.py\n  Accept: requirement one is observable\n- [ ] Plain idless task for FR-002 verified by VER-001\n  Objective: Idless work completes requirement two\n  Scope: src/b.py\n  Accept: requirement two is observable\n", encoding="utf-8")
    chk = d / "checklists"; chk.mkdir()
    chk_text = "# Checklist\n- [x] CHK001 Measurable?\n- [ ] CHK002 Edge cases?\n"
    (chk / "requirements.md").write_text(chk_text, encoding="utf-8")
    plan = Migration(root).plan()
    assert plan["task_occurrences"] == 3 and plan["canonical_task_count"] == 3, plan["findings"]
    assert not plan["findings"], plan["findings"]
    entry = [e for e in plan["inventory"] if e["path"].endswith("checklists/requirements.md")][0]
    assert entry["task_count"] == 0 and entry["checklist_count"] == 2
    assert Migration(root).apply()["status"] == "activated"
    assert (chk / "requirements.md").read_text(encoding="utf-8") == chk_text
    mapping = json.loads((root / ".speckitext/identity.json").read_text(encoding="utf-8"))
    task_entities = [e for e in mapping["entities"] if e["kind"] == "task"]
    assert len(task_entities) == 3 and not any("CHK" in e["canonical_id"] for e in task_entities)
    assert any(e["canonical_id"].endswith("::T070E") for e in task_entities)
    assert any(e["local_id"].startswith("T-AUTO-") and e["legacy_alias"] == "" for e in task_entities)

# ---- 2. governance scoping ----
def _gov_project(root):
    con = _con([("CON-001", "GLOBAL", "", "Global quality"),
                ("CON-010", "SCOPED", "scope: 001-alpha::COMP-001\n", "Alpha rule"),
                ("CON-011", "SCOPED", "scope: 002-beta::COMP-001\n", "Beta rule")])
    (root / ".specify/memory").mkdir(parents=True, exist_ok=True)
    (root / ".specify/memory/constitution.md").write_text(con, encoding="utf-8")
    _feature(root, "001-alpha", comp=True, task_extra="affects_component: COMP-001\n")
    _feature(root, "002-beta", comp=True, task_extra="affects_component: COMP-001\n")
    return root

def test_governance_qualified_scope_no_leakage(tmp_path):
    root = _gov_project(tmp_path / "p")
    g = Graph.build(root)
    assert not [d for d in validate_graph(g) if d.severity == "error"], validate_graph(g)
    a = compile_context(g, root, ["001-alpha::T002"])
    assert "CON-001" in a["meta"]["included_ids"] and "CON-010" in a["meta"]["included_ids"]
    assert "CON-011" not in a["meta"]["included_ids"]
    b = compile_context(g, root, ["002-beta::T002"])
    assert "CON-011" in b["meta"]["included_ids"] and "CON-010" not in b["meta"]["included_ids"]
    both = compile_context(g, root, ["001-alpha::T002", "002-beta::T002"])
    gov = [x["id"] for x in both["meta"]["governance_included"]]
    assert gov.count("CON-010") == 1 and gov.count("CON-011") == 1 and gov.count("CON-001") == 1

def test_governance_new_rule_invalidates_package(tmp_path):
    root = _gov_project(tmp_path / "p")
    g = Graph.build(root)
    pkg = tmp_path / "pkg.md"
    pkg.write_text(compile_context(g, root, ["001-alpha::T002"])["text"], encoding="utf-8")
    assert package_staleness(Graph.build(root), pkg) == []
    con = root / ".specify/memory/constitution.md"
    con.write_text(con.read_text(encoding="utf-8") + "### CON-012: New alpha rule\n<!-- speckitext\nid: CON-012\nkind: constitution\napplicability: SCOPED\nscope: 001-alpha::COMP-001\n-->\nNew.\n", encoding="utf-8")
    stale = package_staleness(Graph.build(root), pkg)
    assert any(s["id"] == "CON-012" for s in stale)

def test_governance_ambiguous_and_missing_scope_diagnosed(tmp_path):
    root = _gov_project(tmp_path / "p")
    con = root / ".specify/memory/constitution.md"
    con.write_text(con.read_text(encoding="utf-8") + "### CON-020: Ambiguous\n<!-- speckitext\nid: CON-020\nkind: constitution\napplicability: SCOPED\nscope: COMP-001\n-->\nAmbiguous.\n### CON-021: Missing\n<!-- speckitext\nid: CON-021\nkind: constitution\napplicability: SCOPED\nscope: 001-alpha::COMP-999\n-->\nMissing.\n", encoding="utf-8")
    codes = _codes(root)
    assert "AMBIGUOUS_SCOPE" in codes and "UNRESOLVED_SCOPE" in codes
    with pytest.raises(CompileError):
        compile_context(Graph.build(root), root, ["001-alpha::T002"])

# ---- 3. identity map integrity ----
def _write_map(root, data):
    p = root / ".speckitext/identity.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")
    return p

def _valid_map(root):
    g = Graph.build(root)
    return {"version": 1, "features": {"001-alpha": "001-alpha"},
            "entities": [{"canonical_id": s.node_id, "local_id": s.local_id, "legacy_alias": s.legacy_alias,
                          "feature": s.feature_id, "kind": s.kind, "source_path": s.path} for s in g.nodes.values()]}

def test_identity_map_missing_and_valid(tmp_path):
    root = _valid_project(tmp_path / "p")
    assert not [d for d in validate_graph(Graph.build(root)) if d.severity == "error"]
    _write_map(root, _valid_map(root))
    assert not [d for d in validate_graph(Graph.build(root)) if d.severity == "error"], validate_graph(Graph.build(root))

@pytest.mark.parametrize("raw,code", [
    ("{corrupt", "IDENTITY_MAP_CORRUPT"),
    ("[]", "IDENTITY_MAP_CORRUPT"),
    (json.dumps({"version": 99, "features": {}, "entities": []}), "IDENTITY_MAP_UNSUPPORTED_VERSION"),
    (json.dumps({"version": 1, "features": [], "entities": []}), "IDENTITY_MAP_CORRUPT"),
    (json.dumps({"version": 1, "features": {}, "entities": {}}), "IDENTITY_MAP_CORRUPT"),
    (json.dumps({"version": 1, "features": {}, "entities": ["nope"]}), "IDENTITY_MAP_INVALID"),
])
def test_identity_map_corrupt_variants_fail_closed(tmp_path, raw, code):
    root = _valid_project(tmp_path / "p")
    _write_map(root, raw)
    g = Graph.build(root)  # must not raise on malformed structures
    assert code in [d.code for d in validate_graph(g)]
    out = tmp_path / "ctx.md"
    assert main(["validate", "--project", str(root)]) == 1
    assert main(["compile", "--project", str(root), "--tasks", "001-alpha::T002", "--output", str(out)]) == 1
    assert not out.exists()
    assert main(["batch", "suggest", "--project", str(root)]) == 1
    assert main(["impact", "--project", str(root), "--ids", "001-alpha::FR-001"]) == 1

def test_identity_map_duplicate_conflicting_and_disagreement(tmp_path):
    root = _valid_project(tmp_path / "p")
    m = _valid_map(root)
    m["entities"].append(dict(m["entities"][0]))
    _write_map(root, m)
    assert "IDENTITY_MAP_DUPLICATE" in _codes(root)

    root2 = _valid_project(tmp_path / "q")
    m2 = _valid_map(root2)
    task = [e for e in m2["entities"] if e["kind"] == "task"][0]
    task["feature"] = "002-beta"
    _write_map(root2, m2)
    assert "IDENTITY_MAP_INCONSISTENT" in _codes(root2)

    root3 = _valid_project(tmp_path / "r")
    m3 = _valid_map(root3)
    m3["features"] = {"001-alpha": 123}
    _write_map(root3, m3)
    # non-string feature value is hardened to a corrupt map by the loader
    assert "IDENTITY_MAP_CORRUPT" in _codes(root3) or "IDENTITY_MAP_INVALID" in _codes(root3)

def test_identity_map_corrupt_after_migration_blocks_activation(tmp_path):
    root = tmp_path / "legacy"
    (root / ".specify/memory").mkdir(parents=True)
    (root / ".specify/memory/constitution.md").write_text("# Constitution\n\n### CON-001: Quality\nAll work is tested.\n", encoding="utf-8")
    d = root / "specs/001-alpha"; d.mkdir(parents=True)
    (d / "spec.md").write_text("# Spec\n\n- **FR-001**: Requirement one\n", encoding="utf-8")
    (d / "tasks.md").write_text("# Tasks\n\n### VER-001: Checks\nRun: pytest -q\n\n- [x] T001 Done for FR-001 verified by VER-001\n- [ ] T002 Pending for FR-001 verified by VER-001\n  Objective: Pending work completes requirement one\n  Scope: src/a.py\n  Accept: requirement one is observable\n", encoding="utf-8")
    assert Migration(root).apply()["status"] == "activated"
    p = root / ".speckitext/identity.json"
    p.write_text("{corrupt", encoding="utf-8")
    before = p.read_bytes()
    plan = Migration(root).plan()
    assert plan["findings"] and any("IDENTITY_MAP" in f["finding"] for f in plan["findings"])
    assert Migration(root).apply()["status"] == "refused"
    assert p.read_bytes() == before
    assert main(["migrate", "--project", str(root), "--dry-run"]) == 1

# ---- 4. canonical ownership ----
def test_canonical_feature_mismatch_and_local_mismatch(tmp_path):
    root = _valid_project(tmp_path / "p")
    tasks = root / "specs/001-alpha/tasks.md"
    tasks.write_text(tasks.read_text(encoding="utf-8").replace("canonical_id: 001-alpha::T001", "canonical_id: 002-beta::T001"), encoding="utf-8")
    assert "CANONICAL_FEATURE_MISMATCH" in _codes(root)

    root2 = _valid_project(tmp_path / "q")
    tasks2 = root2 / "specs/001-alpha/tasks.md"
    tasks2.write_text(tasks2.read_text(encoding="utf-8").replace("canonical_id: 001-alpha::T001", "canonical_id: 001-alpha::T999"), encoding="utf-8")
    assert "CANONICAL_LOCAL_MISMATCH" in _codes(root2)

def test_global_namespace_and_duplicate_locals_across_features(tmp_path):
    root = _gov_project(tmp_path / "p")
    assert not [d for d in validate_graph(Graph.build(root)) if d.severity == "error"]
    con = root / ".specify/memory/constitution.md"
    con.write_text(con.read_text(encoding="utf-8").replace("id: CON-001\nkind: constitution", "id: CON-001\ncanonical_id: 001-alpha::CON-001\nkind: constitution"), encoding="utf-8")
    assert "INVALID_GLOBAL_NAMESPACE" in _codes(root)

def test_feature_rename_with_and_without_identity_evidence(tmp_path):
    root = _valid_project(tmp_path / "p")
    mapping = _valid_map(root)
    import shutil
    shutil.move(str(root / "specs/001-alpha"), str(root / "specs/009-renamed"))
    mapping["features"] = {"009-renamed": "001-alpha"}
    _write_map(root, mapping)
    assert not [d for d in validate_graph(Graph.build(root)) if d.severity == "error"], validate_graph(Graph.build(root))
    # without sufficient evidence: strip declared feature, no map
    root2 = _valid_project(tmp_path / "q")
    shutil.move(str(root2 / "specs/001-alpha"), str(root2 / "specs/009-renamed"))
    for f in (root2 / "specs/009-renamed").glob("*.md"):
        f.write_text(f.read_text(encoding="utf-8").replace("feature: 001-alpha\n", ""), encoding="utf-8")
    assert "CANONICAL_FEATURE_MISMATCH" in _codes(root2)
