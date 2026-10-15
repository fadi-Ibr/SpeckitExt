"""Change-impact analysis: reverse traceability closure over changed IDs/files."""
from __future__ import annotations

from pathlib import Path

from .graph import Graph


def _resolve(graph: Graph, ref: str) -> str:
    cands = graph.candidates(ref) if graph.resolver else []
    if len(cands) > 1 and "::" not in ref:
        raise ValueError(f"ambiguous id {ref!r}; qualify one of: {', '.join(cands)}")
    try:
        return graph.resolve(ref)
    except Exception:
        return ref


def impact_for_ids(graph: Graph, changed_ids: list[str]) -> dict:
    changed = sorted({_resolve(graph, c) for c in changed_ids})
    affected = graph.reverse_dependents(changed)
    by_kind: dict[str, list[str]] = {}
    for nid in affected:
        by_kind.setdefault(graph.nodes[nid].kind, []).append(nid)
    affected_tasks = by_kind.get("task", [])
    details = [{"canonical_id": n, "local_id": graph.nodes[n].local_id,
                "feature": graph.nodes[n].feature_id, "kind": graph.nodes[n].kind}
               for n in affected]
    changed_details = [{"canonical_id": c, "local_id": graph.nodes[c].local_id,
                         "feature": graph.nodes[c].feature_id}
                        for c in changed if graph.nodes.get(c) is not None]
    return {"changed": changed, "changed_details": changed_details,
            "affected": affected, "affected_details": details,
            "affected_by_kind": by_kind, "affected_tasks": affected_tasks,
            "stale_packages_note": "any compiled package referencing a changed or affected id is stale"}


def impact_for_files(graph: Graph, project: Path, changed_files: list[str]) -> dict:
    rels = {Path(f).as_posix() for f in changed_files}
    changed = sorted(s.node_id for s in graph.nodes.values() if s.path in rels)
    return impact_for_ids(graph, changed)
