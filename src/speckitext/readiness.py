"""Implementation-readiness validation for generated tasks.

Graph validation (validate.py) proves IDs and relationships are sound. This
module proves a task is *actionable*: an agent handed only the task ID and the
compiled package must know what to build, where, and how to prove it worked.

Deterministically enforceable checks (all severity=error):
  READINESS_MISSING_OBJECTIVE   no `Objective:` line with a real intended result
  READINESS_MISSING_SCOPE       no `Scope:` line and no concrete file path in the task
  READINESS_MISSING_ACCEPTANCE  no `Accept:` line with acceptance conditions
  READINESS_PLACEHOLDER         unresolved [PLACEHOLDER] / TODO / TBD / NEEDS CLARIFICATION
  READINESS_VAGUE_VERIFICATION  linked VER-xxx section names no executable check

Semantic specificity ("is this objective *good*?") cannot be proven
deterministically; the authoring contract in preset/commands/speckit.tasks.md
covers it and these checks reject the mechanically detectable failures.
Shared detail stays in requirements/decisions/contracts and reaches the agent
through the compiler by ID — readiness never duplicates it into task bodies.
"""
from __future__ import annotations

import re

from .graph import Graph
from .schema import Diagnostic

_PLACEHOLDER_RE = re.compile(
    r"\[[A-Z][A-Za-z0-9 _/-]{2,}\]|\bTODO\b|\bTBD\b|NEEDS CLARIFICATION|\[FEATURE[^\]]*\]|\[Check[^\]]*\]")
_PATH_RE = re.compile(r"[\w][\w./\\-]*\.[A-Za-z]{1,5}\b")
_COMMAND_RE = re.compile(
    r"`([^`\n]{3,})`|^\s*(?:Run|Command)\s*:\s*(\S.*)$|"
    r"\b(pytest|python|npm|npx|yarn|pnpm|cargo|go test|dotnet|mvn|gradle|phpunit|rspec|jest|vitest|playwright)\b|"
    r"^\s*make\s+(?!sure\b)\S+",
    re.MULTILINE)


def _field(content: str, name: str) -> str:
    m = re.search(rf"(?mi)^\s*(?:[-*]\s*)?{name}\s*:\s*(.+)$", content)
    return m.group(1).strip() if m else ""


def verification_is_executable(content: str) -> bool:
    """A VER section is executable when it names an actual command/tool, not prose."""
    body = re.sub(r"<!--.*?-->", "", content, flags=re.DOTALL)
    if _PLACEHOLDER_RE.search(body):
        return False
    return bool(_COMMAND_RE.search(body))


def validate_readiness(graph: Graph, *, pending_only: bool = True) -> list[Diagnostic]:
    """Readiness for actionable tasks.

    Completed (done) tasks are historical records: they keep full graph
    traceability but are not re-checked for actionability, so migrated
    history never has to pretend it needs reimplementation. Pending tasks
    must be implementation-ready.
    """
    d: list[Diagnostic] = []
    for sec in sorted((s for s in graph.nodes.values() if s.kind == "task"
                       and not (pending_only and s.status == "done")),
                      key=lambda s: s.node_id):
        content = sec.content
        objective = _field(content, "Objective")
        if len(objective) < 12:
            d.append(Diagnostic("READINESS_MISSING_OBJECTIVE",
                "task must state `Objective: <intended result>` (one concrete sentence)",
                sec.node_id, sec.path))
        scope = _field(content, "Scope")
        if not scope and not _PATH_RE.search(content):
            d.append(Diagnostic("READINESS_MISSING_SCOPE",
                "task must state `Scope: <files/areas>` or name a concrete file path",
                sec.node_id, sec.path))
        accept = _field(content, "Accept")
        if len(accept) < 8:
            d.append(Diagnostic("READINESS_MISSING_ACCEPTANCE",
                "task must state `Accept: <observable acceptance conditions>`",
                sec.node_id, sec.path))
        m = _PLACEHOLDER_RE.search(re.sub(r"<!--.*?-->", "", content, flags=re.DOTALL))
        if m:
            d.append(Diagnostic("READINESS_PLACEHOLDER",
                f"task contains unresolved placeholder {m.group(0)!r}",
                sec.node_id, sec.path))
        for ver_id in graph.targets(sec.node_id, "verified_by"):
            ver = graph.nodes.get(ver_id)
            if ver is not None and not verification_is_executable(ver.content):
                d.append(Diagnostic("READINESS_VAGUE_VERIFICATION",
                    f"{ver_id} names no executable check (expected a command such as "
                    "`pytest tests/test_x.py -q`)", sec.node_id, sec.path))
    return sorted(d, key=lambda x: (x.code, x.node_id, x.path))
