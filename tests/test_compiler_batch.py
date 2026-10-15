import json

from speckitext.batch import suggest_batches
from speckitext.compiler import compile_context, expand_context, package_staleness
from speckitext.graph import Graph


def test_single_task_context_is_scoped(project):
    g = Graph.build(project)
    r = compile_context(g, project, ["T002"])
    text = r["text"]
    assert "FR-001" in text and "DEC-001" in text and "CTR-001" in text
    assert "CON-001" in text  # GLOBAL always included
    assert "CON-002" in text and "CON-003" in text  # SCOPED/CONDITIONAL hit COMP-001
    assert "FR-002" not in text and "FR-003" not in text  # unrelated excluded
    assert "keyboard navigation" not in text  # CON-004 scoped to COMP-002, excluded
    assert "T004" not in text and "T005" not in text
    assert r["blocked"] == []  # T001 prerequisite is done


def test_deterministic_output(project):
    g = Graph.build(project)
    a = compile_context(g, project, ["T002", "T003"])["text"]
    b = compile_context(Graph.build(project), project, ["T003", "T002"])["text"]
    assert a == b


def test_blocked_prerequisite(project):
    g = Graph.build(project)
    r = compile_context(g, project, ["T003"])
    assert r["blocked"] == ["001-demo::T002"]  # T002 not done


def test_batch_context_deduplicates(project):
    g = Graph.build(project)
    r = compile_context(g, project, ["T002", "T003"])
    assert r["text"].count("### CON-001") == 1
    assert r["text"].count("**FR-001**") + r["text"].count("FR-001:") >= 1
    assert r["meta"]["included_ids"].count("001-demo::FR-001") == 1


def test_governance_exclusion_trace(project):
    g = Graph.build(project)
    r = compile_context(g, project, ["T004"])
    excluded = {e["id"] for e in r["meta"]["governance_excluded"]}
    assert "CON-002" in excluded and "CON-004" not in excluded  # CON-004 hits COMP-002
    assert "CON-001" in r["text"]


def test_stale_detection(project, tmp_path):
    g = Graph.build(project)
    pkg = tmp_path / "pkg.md"
    pkg.write_text(compile_context(g, project, ["T002"])["text"], encoding="utf-8")
    assert package_staleness(Graph.build(project), pkg) == []
    spec = project / "specs/001-demo/spec.md"
    spec.write_text(spec.read_text(encoding="utf-8").replace("email and password", "email, password and MFA"),
                    encoding="utf-8")
    stale = package_staleness(Graph.build(project), pkg)
    assert [s["id"] for s in stale] == ["001-demo::FR-001"]


def test_expand_records_reason(project, tmp_path):
    g = Graph.build(project)
    pkg = tmp_path / "pkg.md"
    pkg.write_text(compile_context(g, project, ["T002"])["text"], encoding="utf-8")
    r = expand_context(Graph.build(project), project, pkg, ["FR-002"], "needed for redirect target")
    assert "001-demo::FR-002" in r["meta"]["included_ids"]
    assert r["meta"]["expansions"][-1]["reason"] == "needed for redirect target"


def test_batch_suggest_groups_related_only(project):
    g = Graph.build(project)
    batches = suggest_batches(g)
    grouped = {frozenset(b["tasks"]) for b in batches}
    assert frozenset({"001-demo::T002", "001-demo::T003"}) in grouped  # share FR-001/COMP-001 + dependency
    assert all(not ({"001-demo::T002", "001-demo::T004"} <= set(b["tasks"])) for b in batches)  # unrelated not merged
    t4 = [b for b in batches if "001-demo::T004" in b["tasks"]][0]
    assert t4["tasks"] == ["001-demo::T004"]


def test_batch_topological_order(project):
    g = Graph.build(project)
    batches = suggest_batches(g)
    auth = [b for b in batches if "001-demo::T003" in b["tasks"]][0]
    assert auth["tasks"].index("001-demo::T002") < auth["tasks"].index("001-demo::T003")


def test_batch_size_cap(project):
    g = Graph.build(project)
    batches = suggest_batches(g, max_tasks=1)
    assert all(len(b["tasks"]) == 1 for b in batches)


def test_impact_analysis(project):
    from speckitext.impact import impact_for_ids
    g = Graph.build(project)
    r = impact_for_ids(g, ["FR-001"])
    assert {"001-demo::T001", "001-demo::T002", "001-demo::T003", "001-demo::DEC-001"} <= set(r["affected"])
    assert "001-demo::T004" not in r["affected"]
