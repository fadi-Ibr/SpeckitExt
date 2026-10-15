"""Versioned ID and relationship schema for SpeckitExt artifacts.

Namespaces (stable across edits, insertions, removals, and task completion):

    CON-001   constitution rule / principle
    FR-001    functional requirement        (preserved Spec Kit convention)
    SC-001    success criterion             (preserved Spec Kit convention)
    DEC-001   architectural decision
    COMP-001  component
    CTR-001   contract / interface
    DM-001    data-model entity
    T001      implementation task           (preserved Spec Kit convention)
    VER-001   verification obligation / check
    RES-001   supporting research reference

Every section carrying one of these IDs owns a metadata block:

    <!-- speckitext
    id: FR-001
    kind: requirement
    governed_by: CON-001
    -->

Relationship semantics (source --relation--> target):

    governed_by       any            -> constitution
    satisfies         task|decision|component -> requirement|success_criterion
    implements        task           -> requirement|decision|component|contract|data_model
    depends_on        task->task, component->component, decision->decision,
                      contract->contract, task->component
    constrained_by    any            -> constitution|decision
    affects_component task|decision  -> component
    verified_by       requirement|task|decision|component -> verification
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

SCHEMA_VERSION = "2.0"

# Generalized legacy task families (structural context restricts matching):
#   T001 / T070E      numeric with optional suffix letter
#   G5-T1 / FEAT2-T03 feature-prefixed task labels
#   TR-A / PL-C       alphanumeric labels
#   T-AUTO-<hash>     generated for ID-less tasks
#   <custom>          structured custom IDs from explicit speckitext metadata
LEGACY_TASK_RE = re.compile(
    r"^(?:T\d{1,6}[A-Z]?|[A-Z]{1,4}\d{1,4}[A-Z]?(?:-[A-Z0-9]+[A-Z]?)+|"
    r"[A-Z]{1,4}-[A-Z0-9]{1,6}[A-Z]?|T-AUTO-[0-9a-f]{8}(?:-\d+)?)$")
CUSTOM_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9][A-Za-z0-9_-]{1,63}$")

ID_PATTERNS: dict[str, re.Pattern[str]] = {
    "constitution": re.compile(r"^CON-\d{3,}$"),
    "requirement": re.compile(r"^FR-\d{3,}$"),
    "success_criterion": re.compile(r"^SC-\d{3,}$"),
    "decision": re.compile(r"^DEC-\d{3,}$"),
    "component": re.compile(r"^COMP-\d{3,}$"),
    "contract": re.compile(r"^CTR-\d{3,}$"),
    "data_model": re.compile(r"^DM-\d{3,}$"),
    "task": LEGACY_TASK_RE,
    "verification": re.compile(r"^VER-\d{3,}$"),
    "research": re.compile(r"^RES-\d{3,}$"),
}

PREFIX_TO_KIND = {
    "CON": "constitution", "FR": "requirement", "SC": "success_criterion",
    "DEC": "decision", "COMP": "component", "CTR": "contract",
    "DM": "data_model", "VER": "verification", "RES": "research",
}

# ID tokens in text (evidence-based migration / link extraction). Includes
# canonical qualified IDs and generalized legacy task labels; callers use
# structural context (checkbox/heading/bullet/Links lines) to avoid prose hits.
ID_TOKEN_RE = re.compile(r"\b[A-Za-z0-9][A-Za-z0-9._-]*::[A-Za-z0-9][A-Za-z0-9_-]*\b|\b(?:CON|FR|SC|DEC|COMP|CTR|DM|VER|RES)-\d{3,}\b|\bT\d{1,6}[A-Z]?\b|\b[A-Z]{1,4}\d{1,4}[A-Z]?(?:-[A-Z0-9]+[A-Z]?)+\b|\b[A-Z]{1,4}-[A-Z0-9]{1,6}[A-Z]?\b")

RELATIONS = ("governed_by", "satisfies", "implements", "depends_on",
             "constrained_by", "affects_component", "verified_by")

# relation -> (allowed source kinds, allowed target kinds); "*" means any kind.
RELATION_RULES: dict[str, tuple[frozenset[str] | str, frozenset[str] | str]] = {
    "governed_by": ("*", frozenset({"constitution"})),
    "satisfies": (frozenset({"task", "decision", "component"}),
                  frozenset({"requirement", "success_criterion"})),
    "implements": (frozenset({"task"}),
                   frozenset({"requirement", "decision", "component", "contract", "data_model"})),
    "depends_on": (frozenset({"task", "component", "decision", "contract"}),
                   frozenset({"task", "component", "decision", "contract"})),
    "constrained_by": ("*", frozenset({"constitution", "decision"})),
    "affects_component": (frozenset({"task", "decision"}), frozenset({"component"})),
    "verified_by": (frozenset({"requirement", "task", "decision", "component"}),
                    frozenset({"verification"})),
}

APPLICABILITIES = ("GLOBAL", "SCOPED", "CONDITIONAL")


def local_part(node_id: str) -> str:
    return node_id.split("::", 1)[1] if "::" in node_id else node_id


def kind_for_id(node_id: str) -> str | None:
    """Kind for established namespaces only. Generalized legacy task labels
    (G5-T1, TR-A) are tasks only in task-structural context or with an
    explicit kind, never by bare token inference in prose."""
    lid = local_part(node_id)
    if re.fullmatch(r"T\d{1,6}[A-Z]?", lid) or lid.startswith("T-AUTO-"):
        return "task"
    prefix = lid.split("-", 1)[0] if "-" in lid else ""
    return PREFIX_TO_KIND.get(prefix)


def valid_id(node_id: str, kind: str | None = None) -> bool:
    """Validate a canonical or local ID. Canonical ``feat::LOCAL`` validates
    its local part; task locals accept the generalized legacy families and
    structured custom IDs (explicit metadata), other kinds keep their
    established namespaces."""
    lid = local_part(node_id)
    inferred = kind_for_id(lid)
    k = kind or inferred
    if k is None:
        return False
    if kind is not None and inferred is not None and kind != inferred:
        # Structured custom task IDs have no inferable kind; allow for task.
        if not (kind == "task" and CUSTOM_ID_RE.fullmatch(lid)):
            return False
    if k == "task":
        return bool(LEGACY_TASK_RE.fullmatch(lid) or CUSTOM_ID_RE.fullmatch(lid))
    pat = ID_PATTERNS.get(k)
    return bool(pat and pat.fullmatch(lid))


@dataclass
class Diagnostic:
    code: str
    message: str
    node_id: str = ""
    path: str = ""
    severity: str = "error"  # error | warning

    def __str__(self) -> str:
        loc = f" [{self.path}]" if self.path else ""
        nid = f" {self.node_id}" if self.node_id else ""
        return f"{self.severity.upper()} {self.code}{nid}{loc}: {self.message}"

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "id": self.node_id,
                "path": self.path, "severity": self.severity}


@dataclass
class Relation:
    source: str
    relation: str
    target: str
    raw_target: str = ""
    explicit: bool = False

    def to_dict(self) -> dict:
        return {"source": self.source, "relation": self.relation, "target": self.target,
                "raw_target": self.raw_target or self.target, "explicit": self.explicit}
