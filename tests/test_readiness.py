from speckitext.graph import Graph
from speckitext.readiness import validate_readiness
from speckitext.validate import validate_all


def codes(project) -> set[str]:
    return {d.code for d in validate_readiness(Graph.build(project))}


def test_fixture_is_readiness_clean(project):
    assert validate_all(Graph.build(project)) == []


def _edit_tasks(project, old, new):
    p = project / "specs/001-demo/tasks.md"
    p.write_text(p.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")


def test_missing_objective(project):
    _edit_tasks(project, "  Objective: POST /login returns a session token for valid credentials\n", "")
    assert "READINESS_MISSING_OBJECTIVE" in codes(project)


def test_missing_scope(project):
    _edit_tasks(project, "Implement login endpoint for FR-001 in src/auth.py",
                "Implement login endpoint for FR-001")
    _edit_tasks(project, "  Scope: src/auth.py\n", "", )
    # T002 loses both its Scope line and loses path only if all Scope lines removed hits other tasks too;
    assert "READINESS_MISSING_SCOPE" in codes(project)


def test_missing_acceptance(project):
    _edit_tasks(project, "  Accept: valid login returns 200 with token; bad password returns 401\n", "")
    assert "READINESS_MISSING_ACCEPTANCE" in codes(project)


def test_placeholder_rejected(project):
    _edit_tasks(project, "Scope: src/auth.py", "Scope: src/[COMPONENT].py")
    assert "READINESS_PLACEHOLDER" in codes(project)


def test_vague_verification_rejected(project):
    _edit_tasks(project, "Run: pytest tests/test_auth.py -q", "Run the tests and make sure things work")
    assert "READINESS_VAGUE_VERIFICATION" in codes(project)


def test_compile_gate_includes_readiness(project):
    from speckitext.compiler import CompileError, compile_context
    import pytest
    _edit_tasks(project, "  Accept: valid login returns 200 with token; bad password returns 401\n", "")
    with pytest.raises(CompileError):
        compile_context(Graph.build(project), project, ["T002"])
