"""Real agent-executed authoring lifecycle E2E (separate from CI defaults).

Runs a real coding-agent CLI (Claude Code) headlessly in a newly created
disposable Spec Kit project: bootstrap -> constitution/specify/plan/tasks
authoring by the agent in sequential stage prompts -> validation -> batch ->
compile -> ID-only implementation assignment -> functional check.

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

STAGE_PROMPTS = [
    "Use the speckit-constitution skill in this project to create a small "
    "constitution for the feature below: at least two GLOBAL rules with "
    "CON-xxx IDs and speckitext metadata blocks. Actually write the files. "
    f"Feature: {FEATURE}",
    "Use the speckit-specify skill in this project to specify the feature "
    "from the previous step: FR-xxx requirements, each with a speckitext "
    "metadata block declaring governed_by a constitution rule. Actually "
    "write the files under specs/.",
    "Use the speckit-plan skill in this project to plan the specified "
    "feature: at least one DEC-xxx decision and one COMP-xxx component with "
    "speckitext metadata linking them to the requirements. Actually write "
    "the files.",
    "Use the speckit-tasks skill in this project to generate "
    "implementation-ready tasks: stable Txxx IDs, speckitext metadata "
    "(satisfies/implements, verified_by a VER-xxx section naming an "
    "executable pytest command, depends_on, affects_component), plus "
    "Objective:/Scope:/Accept: lines under every task. Include the related "
    "greeting tasks and ONE unrelated README badge task. Then run "
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

    graph = Graph.build(proj)
    assert graph.nodes, "agent authored no traceability artifacts"
    kinds = {s.kind for s in graph.nodes.values()}
    assert {"constitution", "requirement", "task", "verification"} <= kinds
    diags = validate_all(graph)
    assert diags == [], [str(d) for d in diags]

    pending = sorted(n for n, s in graph.nodes.items()
                     if s.kind == "task" and s.status != "done")
    assert pending, "no pending tasks authored"
    target = pending[0]

    # Compiled package for the target excludes unrelated sections, keeps globals.
    pkg = compile_context(graph, proj, [target])
    assert "CON-" in pkg["text"]
    included = set(pkg["meta"]["included_ids"])
    assert target in included

    # Short ID-only assignment must be sufficient.
    impl = _run(_agent_cmd() + ["-p", f"Implement {target} using SpeckitExt.",
                                "--allow-dangerously-skip-permissions"], proj)
    assert impl.returncode == 0, impl.stdout[-3000:] + impl.stderr[-1000:]

    # The feature actually works after implementation (when the authored
    # greeting module exists, its behavior is checked for real).
    greet = proj / "src" / "greet.py"
    if greet.is_file():
        check = _run(["python", "-c",
                      "from src.greet import greet; assert greet('World') == 'Hello, World!'"],
                     proj, timeout=120)
        assert check.returncode == 0, check.stdout + check.stderr
