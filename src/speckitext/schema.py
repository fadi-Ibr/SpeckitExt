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

SCHEMA_VERSION = "1.0"

ID_PATTERNS: dict[str, re.Pattern[str]] = {
    "constitution": re.compile(r"^CON-\d{3,}$"),
    "requirement": re.compile(r"^FR-\d{3,}$"),
    "success_criterion": re.compile(r"^SC-\d{3,}$"),
    "decision": re.compile(r"^DEC-\d{3,}$"),
    "component": re.compile(r"^COMP-\d{3,}$"),
    "contract": re.compile(r"^CTR-\d{3,}$"),
    "data_model": re.compile(r"^DM-\d{3,}$"),
    "task": re.compile(r"^T\d{3,}$"),
    "verification": re.compile(r"^VER-\d{3,}$"),
    "research": re.compile(r"^RES-\d{3,}$"),
}

PREFIX_TO_KIND = {
    "CON": "constitution", "FR": "requirement", "SC": "success_criterion",
    "DEC": "decision", "COMP": "component", "CTR": "contract",
    "DM": "data_model", "VER": "verification", "RES": "research",
}

# Any ID token appearing anywhere in text (used for evidence-based migration).
ID_TOKEN_RE = re.compile(r"\b(?:CON|FR|SC|DEC|COMP|CTR|DM|VER|RES)-\d{3,}\b|\bT\d{3,}\b")

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


def kind_for_id(node_id: str) -> str | None:
    if re.fullmatch(r"T\d{3,}", node_id):
        return "task"
    prefix = node_id.split("-", 1)[0] if "-" in node_id else ""
    return PREFIX_TO_KIND.get(prefix)


def valid_id(node_id: str, kind: str | None = None) -> bool:
    inferred = kind_for_id(node_id)
    if inferred is None:
        return False
    if kind is not None and kind != inferred:
        return False
    return bool(ID_PATTERNS[inferred].fullmatch(node_id))


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

    def to_dict(self) -> dict:
        return {"source": self.source, "relation": self.relation, "target": self.target}
