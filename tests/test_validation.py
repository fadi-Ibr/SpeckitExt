from speckitext.graph import Graph
from speckitext.validate import is_valid, validate_graph


def codes(project) -> set[str]:
    return {d.code for d in validate_graph(Graph.build(project))}


def test_valid_fixture_passes(project):
    assert validate_graph(Graph.build(project)) == []


def test_duplicate_id(project):
    p = project / "specs/001-demo/spec.md"
    p.write_text(p.read_text(encoding="utf-8") +
                 "\n- **FR-001**: duplicate\n<!-- speckitext\nid: FR-001\n"
                 "kind: requirement\ngoverned_by: CON-001\n-->\n", encoding="utf-8")
    assert "DUPLICATE_ID" in codes(project)


def test_unresolved_reference(project):
    p = project / "specs/001-demo/tasks.md"
    t = p.read_text(encoding="utf-8").replace("satisfies: FR-002", "satisfies: FR-099")
    p.write_text(t, encoding="utf-8")
    assert "UNRESOLVED_REFERENCE" in codes(project)


def test_missing_required_relation(project):
    p = project / "specs/001-demo/tasks.md"
    p.write_text(p.read_text(encoding="utf-8").replace("satisfies: FR-003\n", ""), encoding="utf-8")
    assert "MISSING_REQUIRED_RELATION" in codes(project)


def test_dependency_cycle(project):
    p = project / "specs/001-demo/tasks.md"
    t = p.read_text(encoding="utf-8").replace("depends_on: T001", "depends_on: T003")
    p.write_text(t, encoding="utf-8")
    assert "DEPENDENCY_CYCLE" in codes(project)


def test_orphan_requirement(project):
    p = project / "specs/001-demo/spec.md"
    p.write_text(p.read_text(encoding="utf-8") +
                 "\n- **FR-009**: Orphan requirement\n<!-- speckitext\nid: FR-009\n"
                 "kind: requirement\ngoverned_by: CON-001\n-->\n", encoding="utf-8")
    assert "ORPHAN_REQUIREMENT" in codes(project)


def test_invalid_relation_direction(project):
    p = project / "specs/001-demo/tasks.md"
    t = p.read_text(encoding="utf-8").replace("satisfies: FR-001\nimplements: DEC-001, CTR-001",
                                              "satisfies: COMP-001\nimplements: DEC-001, CTR-001")
    p.write_text(t, encoding="utf-8")
    assert "INVALID_RELATION_DIRECTION" in codes(project)


def test_unresolved_condition_fails(project):
    p = project / ".specify/memory/constitution.md"
    t = p.read_text(encoding="utf-8").replace("condition: component == COMP-001",
                                              "condition: frobnicate ~= COMP-001")
    p.write_text(t, encoding="utf-8")
    assert "UNRESOLVED_CONDITION" in codes(project)


def test_cross_feature_reference(project):
    p = project / "specs/001-demo/tasks.md"
    p.write_text(p.read_text(encoding="utf-8").replace("feature: 001-demo", "feature: 002-other", 1),
                 encoding="utf-8")
    # T001 now claims another feature while satisfying FR-001 (feature 001-demo).
    assert "CROSS_FEATURE_REFERENCE" in codes(project)


def test_multiple_feature_scopes(tmp_path):
    from tests.conftest import write_project
    root = write_project(tmp_path / "multi")
    spec2 = root / "specs/002-other"
    spec2.mkdir(parents=True)
    (spec2 / "spec.md").write_text(
        "- **FR-101**: Other feature requirement\n<!-- speckitext\nid: FR-101\n"
        "kind: requirement\ngoverned_by: CON-001\nfeature: 002-other\n-->\n", encoding="utf-8")
    (spec2 / "tasks.md").write_text(
        "### VER-101: Other check\n<!-- speckitext\nid: VER-101\nkind: verification\n-->\nRun tests.\n\n"
        "- [ ] T101 Other feature task\n<!-- speckitext\nid: T101\nkind: task\n"
        "satisfies: FR-101\nverified_by: VER-101\nfeature: 002-other\n-->\n", encoding="utf-8")
    assert validate_graph(Graph.build(root)) == []
