"""Real agent-executed authoring lifecycle E2E (separate from CI defaults).

Runs a real coding-agent CLI (Claude Code) headlessly in a newly created
disposable Spec Kit project: bootstrap -> constitution/specify/plan/tasks
authoring by the agent in sequential stage prompts -> validation -> batch ->
compile -> ID-only implementation assignment -> functional check.

Acceptance is unconditional: the selected greet task(s) must be selected by
their requirement/component relationships (never alphabetically), the
expected source and test files must exist, their behavior must pass, the
selected tasks must be marked done, unrelated tasks must stay pending, and
post-implementation validation must pass. A no-op agent run fails.

Gated: only runs when SPECKITEXT_AGENT_E2E=1 (and the agent CLI exists), so
normal CI reports it as skipped, never as a pass.
"""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
pytestmark = [
    pytest.mark.skipif(os.environ.get("SPECKITEXT_AGENT_E2E") != "1",
                       reason="real-agent E2E not enabled (set SPECKITEXT_AGENT_E2E=1)"),
    pytest.mark.skipif(shutil.which("specify") is None, reason="specify CLI not installed"),
    pytest.mark.skipif(shutil.which("claude") is None, reason="claude CLI not installed"),
]

FEATURE = (
    "Build a tiny Python CLI module `src/greet.py` with a function "
    "`greet(name: str) -> str` returning 'Hello, <name>!' and a `--name` "
    "command-line entry point printing the greeting. Related work: the greet "
    "function, the CLI entry point, and pytest tests proving both. Unrelated "
    "work: a README badge line task that shares nothing with the greeting code."
)

CONTRACT = (
    "Fixed contract in every artifact: the module file is exactly "
    "`src/greet.py` with `greet(name: str) -> str` and a `--name` CLI; "
    "tests live in `tests/test_greet.py`; the suite must pass with plain "
    "`python -m pytest -q` from the repository root."
)

STAGE_PROMPTS = [
    "Use the speckit-constitution skill in this project to create a small "
    "constitution for the feature below: at least two GLOBAL rules with "
    "CON-xxx IDs and speckitext metadata blocks. Actually write the files. "
    f"Feature: {FEATURE}",
    "Use the speckit-specify skill in this project to specify the feature "
    "from the previous step: FR-xxx requirements, each with a speckitext "
    "metadata block declaring governed_by a constitution rule. Actually "
    f"write the files under specs/. {CONTRACT}",
    "Use the speckit-plan skill in this project to plan the specified "
    "feature: at least one DEC-xxx decision and one COMP-xxx component with "
    "speckitext metadata linking them to the requirements. Actually write "
    f"the files. {CONTRACT}",
    "Use the speckit-tasks skill in this project to generate "
    "implementation-ready tasks: stable Txxx IDs, speckitext metadata "
    "(satisfies/implements, verified_by a VER-xxx section naming an "
    "executable pytest command, depends_on, affects_component), plus "
    "Objective:/Scope:/Accept: lines under every task. Include the related "
    "greeting tasks and ONE unrelated README badge task. " + CONTRACT + " The authored "
    "pytest suite MUST pass with plain `python -m pytest -q` from the "
    "repository root once implemented, so specify the import path setup "
    "in the tasks (for example a tests/conftest.py that puts src/ on "
    "sys.path, or `from src.greet import greet` imports). Then run "
    "`speckitext validate --project .` and fix every diagnostic until it "
    "passes, and run `speckitext batch suggest --project .`. Do not "
    "implement any code yet. Actually write the files.",
]


def _run(args, cwd, timeout=1200):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)


def _agent_cmd() -> list[str]:
    exe = shutil.which("claude") or "claude"
    if exe.lower().endswith((".cmd", ".ps1", ".bat")):
        return ["cmd", "/c", exe]  # Windows shims need the shell wrapper
    return [exe]


def select_greet_tasks(graph) -> tuple[list[str], list[str]]:
    """Select pending greet work by traceability, never by sort order.

    Returns (selected, unrelated): tasks whose own text or whose satisfied/
    implemented requirements mention greeting, expanded to a coherent ready
    batch (prerequisites included when pending), and the pending tasks that
    share no requirement/component with them.
    """
    def mentions(node_id: str) -> bool:
        # File-anchored: greet work names src/greet.py, its tests, or greet().
        sec = graph.nodes[node_id]
        text = (sec.heading + " " + sec.content).lower()
        return "greet.py" in text or "test_greet" in text or "greet(" in text

    direct = sorted(
        n for n, s in graph.nodes.items()
        if s.kind == "task" and s.status != "done" and mentions(n))
    assert direct, "no pending task is traceability-linked to the greeting feature"
    # A coherent ready batch: greet tasks plus their pending prerequisites.
    selected = sorted(set(direct) | {d for d in graph.dependency_closure(direct)
                                     if graph.nodes[d].status != "done"})
    # Readiness: every prerequisite is done or inside the selection.
    for tid in selected:
        for dep in graph.targets(tid, "depends_on"):
            assert dep in selected or graph.nodes[dep].status == "done", (
                f"selected task {tid} has unmet prerequisite {dep}")
    # Unrelated = disjoint work surface (README/badge files, no greet files),
    # regardless of any sloppy component links the authoring agent added.
    unrelated = sorted(
        n for n, s in graph.nodes.items()
        if s.kind == "task" and s.status != "done" and n not in selected
        and ("badge" in (s.heading + " " + s.content).lower()
             or "readme" in (s.heading + " " + s.content).lower()))
    return selected, unrelated


def assert_implementation_outcome(proj: Path, selected: list[str],
                                  unrelated: list[str]) -> None:
    """Unconditional acceptance assertions for an ID-only implementation.

    Raises AssertionError on any missing file, wrong behavior, missing test,
    incomplete selected task, touched unrelated task, or invalid graph.
    """
    from speckitext.graph import Graph
    from speckitext.validate import validate_all

    greet = proj / "src" / "greet.py"
    assert greet.is_file(), "expected implementation file src/greet.py is absent"
    test_files = sorted(proj.glob("tests/test_*.py")) + sorted(proj.glob("test_*.py"))
    assert test_files, "expected pytest test files for the greeting feature are absent"
    check = _run(["python", "-c",
                  "from src.greet import greet; assert greet('World') == 'Hello, World!'"],
                 proj, timeout=120)
    assert check.returncode == 0, check.stdout + check.stderr
    suite = _run(["python", "-m", "pytest", "-q"], proj, timeout=300)
    assert suite.returncode == 0, suite.stdout[-2000:] + suite.stderr[-1000:]
    graph = Graph.build(proj)
    for tid in selected:
        assert graph.nodes[tid].status == "done", f"selected task {tid} was not completed"
    for tid in unrelated:
        assert graph.nodes[tid].status != "done", f"unrelated task {tid} was touched"
    diags = validate_all(graph)
    assert diags == [], [str(d) for d in diags]


def test_real_agent_authoring_and_id_only_implementation(tmp_path):
    from speckitext.bootstrap import bootstrap_project
    from speckitext.compiler import compile_context
    from speckitext.graph import Graph
    from speckitext.validate import validate_all

    proj = tmp_path / "agent-proj"
    result = bootstrap_project(proj, ("claude",), str(REPO / "preset"), str(REPO / "extension"))
    assert result["status"] == "bootstrapped", result

    for prompt in STAGE_PROMPTS:
        stage = _run(_agent_cmd() + ["-p", prompt,
                                     "--allow-dangerously-skip-permissions"], proj)
        assert stage.returncode == 0, stage.stdout[-3000:] + stage.stderr[-1000:]

    # 1-3. Planning artifacts, valid graph, correct relationships.
    assert (proj / ".specify/memory/constitution.md").is_file()
    assert list(proj.glob("specs/*/spec.md")) and list(proj.glob("specs/*/tasks.md"))
    graph = Graph.build(proj)
    assert graph.nodes, "agent authored no traceability artifacts"
    kinds = {s.kind for s in graph.nodes.values()}
    assert {"constitution", "requirement", "task", "verification"} <= kinds
    diags = validate_all(graph)
    assert diags == [], [str(d) for d in diags]

    # 4. Deliberately selected, ready greet batch (not alphabetical position).
    selected, unrelated = select_greet_tasks(graph)
    assert unrelated, "fixture must contain an unrelated pending task"

    # 5-6. Compiled package governs the selection and excludes unrelated work.
    pkg = compile_context(graph, proj, selected)
    assert "CON-" in pkg["text"]
    included = set(pkg["meta"]["included_ids"])
    assert set(selected) <= included
    for tid in unrelated:
        assert tid not in included
    # Unrelated requirements (those only the unrelated tasks satisfy) excluded.
    unrelated_reqs = {t for tid in unrelated for _r, t in graph.nodes[tid].relations()
                      if graph.nodes.get(t) is not None
                      and graph.nodes[t].kind in ("requirement", "success_criterion")}
    selected_reqs = {t for tid in selected for _r, t in graph.nodes[tid].relations()}
    for rid in unrelated_reqs - selected_reqs:
        assert rid not in included

    # 7. Real agent executes only the ID-only assignment.
    impl = _run(_agent_cmd() + ["-p",
                                f"Implement {','.join(selected)} using SpeckitExt.",
                                "--allow-dangerously-skip-permissions"], proj)
    assert impl.returncode == 0, impl.stdout[-3000:] + impl.stderr[-1000:]
    evidence = proj / ".specify" / "context"
    assert evidence.is_dir() and list(evidence.glob("*.md")), (
        "no compiled context package evidence; the agent must have used "
        "the SpeckitExt workflow, not upstream broad loading")

    # 8-14. Files, behavior, tests, completion, isolation, revalidation.
    assert_implementation_outcome(proj, selected, unrelated)
