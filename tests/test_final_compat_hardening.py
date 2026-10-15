"""Final hardening: persisted identity continuity, fail-closed SCOPED and
canonical CONDITIONAL governance, nested checklist hierarchy.
Disposable synthetic fixtures only; no real project files."""
import json
import re

import pytest

from speckitext.cli import main
from speckitext.compiler import CompileError, compile_context, package_staleness
from speckitext.graph import Graph
from speckitext.migration import Migration
from speckitext.parsing import parse_text
from speckitext.validate import validate_graph


def _con(rules):
    out = ["# Constitution\n"]
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


def _project(root, con=GLOBAL_CON, feats=("001-alpha",), comp=False):
    (root / ".specify/memory").mkdir(parents=True, exist_ok=True)
    (root / ".specify/memory/constitution.md").write_text(con, encoding="utf-8")
    for f in feats:
        _feature(root, f, comp=comp, task_extra="affects_component: COMP-001\n" if comp else "")
    return root


def _errors(root):
    return [d for d in validate_graph(Graph.build(root)) if d.severity == "error"]


def _codes(root):
    return [d.code for d in _errors(root)]


def _write_map(root, data):
    p = root / ".speckitext/identity.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def _valid_map(root):
    g = Graph.build(root)
    feats = sorted({s.feature_id for s in g.nodes.values() if s.feature_id})
    return {"version": 1, "features": {f: f for f in feats},
            "entities": [{"canonical_id": s.node_id, "local_id": s.local_id, "legacy_alias": s.legacy_alias,
                          "feature": s.feature_id, "kind": s.kind, "source_path": s.path}
                         for s in g.nodes.values()]}


def _remove_t001(root):
    tasks = root / "specs/001-alpha/tasks.md"
    text = re.sub(r"- \[x\] T001.*?-->\n", "", tasks.read_text(encoding="utf-8"), flags=re.S)
    tasks.write_text(text, encoding="utf-8")


# ---- 1. persisted identity continuity ------------------------------------

def test_identity_rename_without_reconciliation_fails(tmp_path):
    root = _project(tmp_path / "p")
    _write_map(root, _valid_map(root))
    tasks = root / "specs/001-alpha/tasks.md"
    tasks.write_text(tasks.read_text(encoding="utf-8").replace("T001", "T999"), encoding="utf-8")
    assert "IDENTITY_DISAPPEARED" in _codes(root)
    assert main(["validate", "--project", str(root)]) == 1
    out = tmp_path / "ctx.md"
    assert main(["compile", "--project", str(root), "--tasks", "001-alpha::T002", "--output", str(out)]) == 1
    assert not out.exists()


def test_identity_removal_without_reconciliation_fails(tmp_path):
    root = _project(tmp_path / "p")
    _write_map(root, _valid_map(root))
    _remove_t001(root)
    assert "IDENTITY_DISAPPEARED" in _codes(root)
    with pytest.raises(CompileError):
        compile_context(Graph.build(root), root, ["001-alpha::T002"])


def test_identity_new_task_and_completion_pass(tmp_path):
    root = _project(tmp_path / "p")
    _write_map(root, _valid_map(root))
    tasks = root / "specs/001-alpha/tasks.md"
    text = tasks.read_text(encoding="utf-8").replace("- [ ] T002", "- [x] T002")
    tasks.write_text(text, encoding="utf-8")
    assert not [c for c in _codes(root) if c.startswith("IDENTITY")]
    tasks.write_text(text + "- [ ] T003 New for FR-001\n<!-- speckitext\nid: T003\nkind: task\ncanonical_id: 001-alpha::T003\nsatisfies: FR-001\nverified_by: VER-001\nfeature: 001-alpha\n-->\n  Objective: New work completes requirement one\n  Scope: src/z.py\n  Accept: requirement one is observable\n", encoding="utf-8")
    assert not _errors(root), _errors(root)


def test_identity_explicit_removal_and_reassignment_pass(tmp_path):
    root = _project(tmp_path / "p")
    m = _valid_map(root)
    _remove_t001(root)
    m["reconciliations"] = [{"canonical_id": "001-alpha::T001", "action": "removed",
                             "reason": "task withdrawn by spec change 2026-10-15"}]
    _write_map(root, m)
    assert not _errors(root), _errors(root)

    root2 = _project(tmp_path / "q")
    m2 = _valid_map(root2)
    tasks = root2 / "specs/001-alpha/tasks.md"
    tasks.write_text(tasks.read_text(encoding="utf-8").replace("T001", "T999"), encoding="utf-8")
    m2["reconciliations"] = [{"canonical_id": "001-alpha::T001", "action": "reassigned",
                              "replacement": "001-alpha::T999", "reason": "renumbered to reserve T001 range"}]
    _write_map(root2, m2)
    assert not _errors(root2), _errors(root2)


def test_identity_conflicting_reconciliation_fails(tmp_path):
    root = _project(tmp_path / "p")
    m = _valid_map(root)
    # reconciliation claims a still-present entity was removed
    m["reconciliations"] = [{"canonical_id": "001-alpha::T001", "action": "removed", "reason": "bogus"}]
    _write_map(root, m)
    assert any(c.startswith("IDENTITY_RECONCILIATION") for c in _codes(root))

    root2 = _project(tmp_path / "q")
    m2 = _valid_map(root2)
    _remove_t001(root2)
    # reassignment target does not exist and no reason recorded
    m2["reconciliations"] = [{"canonical_id": "001-alpha::T001", "action": "reassigned",
                              "replacement": "001-alpha::T555"}]
    _write_map(root2, m2)
    codes = _codes(root2)
    assert any(c.startswith("IDENTITY_RECONCILIATION") for c in codes) or "IDENTITY_DISAPPEARED" in codes


def test_migration_plan_preserves_reconciliation_provenance(tmp_path):
    root = _project(tmp_path / "p")
    m = _valid_map(root)
    _remove_t001(root)
    m["reconciliations"] = [{"canonical_id": "001-alpha::T001", "action": "removed",
                             "reason": "withdrawn"}]
    _write_map(root, m)
    plan = Migration(root).plan()
    assert not plan["findings"], plan["findings"]
    carried = plan["identity_mapping"]
    assert carried.get("reconciliations") == m["reconciliations"]
    assert any(e["canonical_id"] == "001-alpha::T001" for e in carried["entities"])


# ---- 2. SCOPED governance fail-closed -------------------------------------

def test_scoped_missing_bare_is_error(tmp_path):
    con = _con([("CON-001", "GLOBAL", "", "Global quality"),
                ("CON-010", "SCOPED", "scope: COMP-999\n", "Missing bare")])
    root = _project(tmp_path / "p", con=con, comp=True)
    diags = [d for d in validate_graph(Graph.build(root)) if d.code == "UNRESOLVED_SCOPE"]
    assert diags and all(d.severity == "error" for d in diags)
    assert main(["validate", "--project", str(root)]) == 1
    with pytest.raises(CompileError):
        compile_context(Graph.build(root), root, ["001-alpha::T002"])


def test_scoped_non_component_target_is_error(tmp_path):
    con = _con([("CON-001", "GLOBAL", "", "Global quality"),
                ("CON-010", "SCOPED", "scope: 001-alpha::FR-001\n", "Wrong kind qualified"),
                ("CON-011", "SCOPED", "scope: FR-001\n", "Wrong kind bare")])
    root = _project(tmp_path / "p", con=con, comp=True)
    codes = _codes(root)
    assert codes.count("UNRESOLVED_SCOPE") >= 2, _errors(root)


def test_scoped_valid_unambiguous_local_passes(tmp_path):
    con = _con([("CON-001", "GLOBAL", "", "Global quality"),
                ("CON-010", "SCOPED", "scope: COMP-001\n", "Local scoped")])
    root = _project(tmp_path / "p", con=con, comp=True)
    assert not _errors(root), _errors(root)
    pkg = compile_context(Graph.build(root), root, ["001-alpha::T002"])
    assert "CON-010" in pkg["meta"]["included_ids"]


# ---- 3. CONDITIONAL canonical resolution ----------------------------------

COND_CON = None  # built per-test below


def _cond_project(root, extra_rules):
    con = _con([("CON-001", "GLOBAL", "", "Global quality")] + extra_rules)
    return _project(root, con=con, feats=("001-alpha", "002-beta"), comp=True)


def test_conditional_qualified_alpha_beta_exact(tmp_path):
    root = _cond_project(tmp_path / "p", [
        ("CON-010", "CONDITIONAL", "condition: component == 001-alpha::COMP-001\n", "Alpha cond"),
        ("CON-011", "CONDITIONAL", "condition: has_component(002-beta::COMP-001)\n", "Beta cond"),
        ("CON-012", "CONDITIONAL", "condition: component == 001-alpha::COMP-001 and feature == 001-alpha\n", "Alpha combo"),
    ])
    assert not _errors(root), _errors(root)
    a = compile_context(Graph.build(root), root, ["001-alpha::T002"])
    assert "CON-010" in a["meta"]["included_ids"] and "CON-012" in a["meta"]["included_ids"]
    assert "CON-011" not in a["meta"]["included_ids"]
    b = compile_context(Graph.build(root), root, ["002-beta::T002"])
    assert "CON-011" in b["meta"]["included_ids"]
    assert "CON-010" not in b["meta"]["included_ids"] and "CON-012" not in b["meta"]["included_ids"]
    both = compile_context(Graph.build(root), root, ["001-alpha::T002", "002-beta::T002"])
    gov = [x["id"] for x in both["meta"]["governance_included"]]
    assert gov.count("CON-010") == 1 and gov.count("CON-011") == 1


@pytest.mark.parametrize("cond", [
    "component == COMP-001",            # ambiguous across the project
    "component == COMP-999",            # missing
    "component == 001-alpha::COMP-999",  # missing qualified
    "component == FR-001",              # non-component bare
    "component == 001-alpha::FR-001",   # non-component qualified
    "has_component(COMP-001)",          # ambiguous via has_component
])
def test_conditional_invalid_component_refs_fail(tmp_path, cond):
    root = _cond_project(tmp_path / "p", [
        ("CON-010", "CONDITIONAL", f"condition: {cond}\n", "Bad cond")])
    assert "UNRESOLVED_CONDITION" in _codes(root), _errors(root)
    assert main(["validate", "--project", str(root)]) == 1
    with pytest.raises(CompileError):
        compile_context(Graph.build(root), root, ["001-alpha::T002"])


def test_conditional_unambiguous_local_and_staleness(tmp_path):
    con = _con([("CON-001", "GLOBAL", "", "Global quality"),
                ("CON-010", "CONDITIONAL", "condition: component == COMP-001\n", "Local cond")])
    root = _project(tmp_path / "p", con=con, comp=True)
    assert not _errors(root), _errors(root)
    pkg = tmp_path / "pkg.md"
    pkg.write_text(compile_context(Graph.build(root), root, ["001-alpha::T002"])["text"], encoding="utf-8")
    assert package_staleness(Graph.build(root), pkg) == []
    con_path = root / ".specify/memory/constitution.md"
    con_path.write_text(con_path.read_text(encoding="utf-8") +
        "### CON-011: New cond\n<!-- speckitext\nid: CON-011\nkind: constitution\napplicability: CONDITIONAL\ncondition: component == 001-alpha::COMP-001\n-->\nNew.\n", encoding="utf-8")
    stale = package_staleness(Graph.build(root), pkg)
    assert any(s["id"] == "CON-011" for s in stale)


# ---- 4. nested checklist hierarchy -----------------------------------------

def test_nested_checklist_headings_stay_checklist():
    doc = parse_text(
        "# Tasks\n- [ ] T001 Real task\n## Checklist\n### Validation\n- [ ] CHK001 Verify acceptance\n"
        "#### Deep checks\n- [x] CHK002 Review references\n### Documentation\n- [ ] CHK003 Check links\n"
        "## Implementation\n- [ ] T002 Second real task\n", "specs/001-a/tasks.md")
    assert [s.local_id for s in doc.sections] == ["T001", "T002"]
    assert doc.task_occurrences == 2 and doc.checklist_occurrences == 3
    assert doc.checklist_completed == 1 and doc.checklist_pending == 2


def test_multiple_checklist_sections_and_exit_by_higher_heading():
    doc = parse_text(
        "# Checklist\n## Quality\n- [ ] CHK001 First check\n# Tasks\n- [ ] T001 Real task\n"
        "## Review Checklist\n### Sub checks\n- [ ] Plainless checklist item\n", "specs/001-a/tasks.md")
    assert [s.local_id for s in doc.sections] == ["T001"]
    assert doc.task_occurrences == 1 and doc.checklist_occurrences == 2
    assert not any(s.local_id.startswith("T-AUTO-") for s in doc.sections)


def test_nested_checklist_migration_no_t_auto(tmp_path):
    root = tmp_path / "legacy"
    (root / ".specify/memory").mkdir(parents=True)
    (root / ".specify/memory/constitution.md").write_text("# Constitution\n\n### CON-001: Quality\nAll work is tested.\n", encoding="utf-8")
    d = root / "specs/001-alpha"; d.mkdir(parents=True)
    (d / "spec.md").write_text("# Spec\n\n- **FR-001**: Requirement one\n", encoding="utf-8")
    (d / "tasks.md").write_text(
        "# Tasks\n\n### VER-001: Checks\nRun: pytest -q\n\n"
        "- [x] T001 Done for FR-001 verified by VER-001\n"
        "## Checklist\n### Validation\n- [ ] CHK001 Verify FR-001 acceptance verified by VER-001\n- [ ] Idless checklist item for FR-001\n"
        "## More work\n- [ ] T002 Pending for FR-001 verified by VER-001\n"
        "  Objective: Pending work completes requirement one\n  Scope: src/a.py\n  Accept: requirement one is observable\n", encoding="utf-8")
    plan = Migration(root).plan()
    assert plan["task_occurrences"] == 2 and plan["canonical_task_count"] == 2, plan["findings"]
    assert not plan["findings"], plan["findings"]
    assert Migration(root).apply()["status"] == "activated"
    mapping = json.loads((root / ".speckitext/identity.json").read_text(encoding="utf-8"))
    tasks = [e for e in mapping["entities"] if e["kind"] == "task"]
    assert sorted(e["local_id"] for e in tasks) == ["T001", "T002"]
    assert not any(e["local_id"].startswith("T-AUTO-") for e in tasks)
    text = (d / "tasks.md").read_text(encoding="utf-8")
    chk_block = text.split("CHK001")[1].split("\n## ")[0]
    assert "speckitext" not in chk_block.split("- [ ] Idless")[0]
