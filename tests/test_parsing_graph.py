from pathlib import Path

from speckitext.graph import Graph
from speckitext.parsing import parse_text
from speckitext.schema import valid_id


def test_heading_and_bullet_and_task_parsing(project):
    g = Graph.build(project)
    assert {"CON-001", "001-demo::FR-001", "001-demo::DEC-001", "001-demo::COMP-001", "001-demo::CTR-001",
            "001-demo::T001", "001-demo::T002", "001-demo::VER-001"} <= set(g.nodes)
    assert g.nodes["T001"].status == "done"
    assert g.nodes["T002"].status == "pending"
    assert ("satisfies", "001-demo::FR-001") in g.nodes["T002"].relations()
    assert ("depends_on", "001-demo::T001") in g.nodes["T002"].relations()


def test_id_stability_across_completion_and_insertion(tmp_path):
    text = ("- [ ] T002 Second\n<!-- speckitext\nid: T002\nkind: task\n"
            "satisfies: FR-001\nverified_by: VER-001\n-->\n")
    before = parse_text(text, "tasks.md").sections[0]
    flipped = parse_text(text.replace("[ ]", "[x]"), "tasks.md").sections[0]
    assert before.node_id == flipped.node_id == "T002"
    assert flipped.status == "done"
    inserted = "- [ ] T001 Inserted earlier\n" + text
    doc = parse_text(inserted, "tasks.md")
    assert [s.node_id for s in doc.sections] == ["T001", "T002"]


def test_valid_id_namespaces():
    assert valid_id("FR-001", "requirement") and valid_id("T001", "task")
    assert not valid_id("FR-1", "requirement") and not valid_id("XX-001")


def test_anchor_and_fingerprint_resolve(project):
    g = Graph.build(project)
    sec = g.nodes["001-demo::FR-001"]
    assert sec.path == "specs/001-demo/spec.md" and sec.anchor
    assert sec.fingerprint.startswith("sha256:") and sec.start_line >= 1


def test_windows_posix_paths(project):
    g = Graph.build(project)
    assert all("\\" not in s.path for s in g.nodes.values())
    assert all("/" in s.path or s.path.count("/") == 0 for s in g.nodes.values())
