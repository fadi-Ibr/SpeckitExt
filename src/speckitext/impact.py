"""Change-impact analysis: reverse traceability closure over changed IDs/files."""
from __future__ import annotations

from pathlib import Path

from .graph import Graph


def impact_for_ids(graph: Graph, changed_ids: list[str]) -> dict:
    affected = graph.reverse_dependents(changed_ids)
    by_kind: dict[str, list[str]] = {}
    for nid in affected:
        by_kind.setdefault(graph.nodes[nid].kind, []).append(nid)
    affected_tasks = by_kind.get("task", [])
    return {"changed": sorted(changed_ids), "affected": affected,
            "affected_by_kind": by_kind, "affected_tasks": affected_tasks,
            "stale_packages_note": "any compiled package referencing a changed or affected id is stale"}


def impact_for_files(graph: Graph, project: Path, changed_files: list[str]) -> dict:
    rels = {Path(f).as_posix() for f in changed_files}
    changed = sorted(s.node_id for s in graph.nodes.values() if s.path in rels)
    return impact_for_ids(graph, changed)
