"""Graph validation. A graph with any error diagnostic is not implementation-ready."""
from __future__ import annotations

from .governance import unresolved_conditions
from .graph import Graph
from .schema import (APPLICABILITIES, RELATION_RULES, Diagnostic, kind_for_id, valid_id)


def validate_graph(graph: Graph) -> list[Diagnostic]:
    d: list[Diagnostic] = []
    for sec in graph.duplicates:
        # Same canonical = duplicate canonical; same feature+local with a
        # different canonical = conflicting legacy alias in one feature.
        d.append(Diagnostic("DUPLICATE_ID",
                            "duplicate canonical identifier (same feature+local identity)",
                            sec.node_id, sec.path))
    # Conflicting legacy alias: one feature+local claimed by 2 canonicals is
    # already in duplicates; also flag a local reused with explicit conflict.
    for err in getattr(graph, "resolution_errors", []) or []:
        msg = str(err.get("error", ""))
        code = "AMBIGUOUS_REFERENCE" if "ambiguous" in msg else "UNRESOLVED_REFERENCE"
        d.append(Diagnostic(code, f"{err.get('relation')} reference cannot be resolved: {msg}",
                            str(err.get("source", "")), str(err.get("path", ""))))
    for sec in graph.nodes.values():
        if not valid_id(sec.node_id, sec.kind):
            d.append(Diagnostic("INVALID_ID",
                f"id does not match namespace pattern for kind {sec.kind!r}",
                sec.node_id, sec.path))
    for e in graph.edges:
        if e.relation not in RELATION_RULES:
            d.append(Diagnostic("INVALID_RELATION", f"unknown relation {e.relation!r}",
                                e.source, _path(graph, e.source)))
            continue
        src = graph.nodes.get(e.source); tgt = graph.nodes.get(e.target)
        if tgt is None:
            d.append(Diagnostic("UNRESOLVED_REFERENCE",
                f"{e.relation} target does not exist", e.source, _path(graph, e.source)))
            continue
        if src is None:
            continue
        allowed_src, allowed_tgt = RELATION_RULES[e.relation]
        if allowed_src != "*" and src.kind not in allowed_src:
            d.append(Diagnostic("INVALID_RELATION_DIRECTION",
                f"{e.relation} not allowed from kind {src.kind}", e.source, src.path))
        if allowed_tgt != "*" and tgt.kind not in allowed_tgt:
            d.append(Diagnostic("INVALID_RELATION_DIRECTION",
                f"{e.relation} must target {sorted(allowed_tgt)}, got {tgt.kind}",
                e.source, src.path))
        # Cross-feature: feature-local targets in another feature require an
        # explicitly qualified reference (feat::ID) or a shared/global target.
        if src.feature_id and tgt.feature_id and src.feature_id != tgt.feature_id \
                and tgt.feature_id not in ("shared", "global") and not e.explicit:
            d.append(Diagnostic("CROSS_FEATURE_REFERENCE",
                f"unqualified reference crosses feature boundary {src.feature_id} -> {tgt.feature_id}; "
                f"qualify as {tgt.node_id}",
                e.source, src.path))
    for cyc in graph.find_cycles():
        d.append(Diagnostic("DEPENDENCY_CYCLE",
            "dependency cycle among: " + ", ".join(cyc), cyc[0], _path(graph, cyc[0])))
    for sec in graph.nodes.values():
        rels = {r for r, _ in sec.relations()}
        if sec.kind == "requirement":
            if "governed_by" not in rels:
                d.append(Diagnostic("MISSING_REQUIRED_RELATION",
                    "requirement must declare governed_by a constitution rule",
                    sec.node_id, sec.path))
        if sec.kind == "task":
            if not ({"satisfies", "implements"} & rels):
                d.append(Diagnostic("MISSING_REQUIRED_RELATION",
                    "task must declare satisfies or implements at least one requirement/decision/component",
                    sec.node_id, sec.path))
            if "verified_by" not in rels:
                d.append(Diagnostic("MISSING_REQUIRED_RELATION",
                    "task must declare verified_by a verification obligation",
                    sec.node_id, sec.path))
            for dep in graph.targets(sec.node_id, "depends_on"):
                dep_sec = graph.nodes.get(dep)
                if dep_sec is not None and dep_sec.kind == "task" and dep_sec.status not in ("done", "pending"):
                    d.append(Diagnostic("INVALID_TASK_DEPENDENCY",
                        f"dependency {dep} has invalid status {dep_sec.status!r}",
                        sec.node_id, sec.path))
        if sec.kind == "constitution":
            app = str(sec.meta.get("applicability", "GLOBAL")).upper()
            if app not in APPLICABILITIES:
                d.append(Diagnostic("INVALID_APPLICABILITY",
                    f"applicability must be one of {APPLICABILITIES}", sec.node_id, sec.path))
            if app == "SCOPED" and not (sec.meta.get("scope") or []):
                d.append(Diagnostic("MISSING_REQUIRED_RELATION",
                    "SCOPED rule must declare a non-empty scope", sec.node_id, sec.path))
    d.extend(unresolved_conditions(graph))
    # Orphans: requirements no task satisfies/implements; tasks covered check.
    satisfied = {e.target for e in graph.edges if e.relation in ("satisfies", "implements")}
    for sec in graph.nodes.values():
        if sec.kind in ("requirement", "success_criterion") and sec.node_id not in satisfied:
            d.append(Diagnostic("ORPHAN_REQUIREMENT",
                "no task satisfies or implements this requirement", sec.node_id, sec.path))
    # Missing source sections: metadata id with no body beyond the heading line is fine;
    # an explicitly referenced anchor that does not exist is caught as unresolved ref.
    return sorted(d, key=lambda x: (x.code, x.node_id, x.path))


def validate_all(graph: Graph) -> list[Diagnostic]:
    """Graph integrity + implementation readiness (the compile/validate gate)."""
    from .readiness import validate_readiness
    return validate_graph(graph) + validate_readiness(graph)


def _path(graph: Graph, node_id: str) -> str:
    sec = graph.nodes.get(node_id)
    return sec.path if sec else ""


def is_valid(diags: list[Diagnostic]) -> bool:
    return not any(x.severity == "error" for x in diags)
