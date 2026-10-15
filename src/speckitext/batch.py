"""Dependency-aware coherent batch planning.

Tasks are grouped only when they share a component, requirement, decision, or a
dependency edge. Unrelated tasks are never merged just to fill capacity.
"""
from __future__ import annotations

from .graph import Graph


def _shared_keys(graph: Graph, tid: str) -> set[str]:
    keys: set[str] = set()
    for rel, target in graph.nodes[tid].relations():
        if rel in ("satisfies", "implements", "affects_component", "constrained_by"):
            keys.add(target)
    return keys


def suggest_batches(graph: Graph, max_tasks: int = 5, max_context_chars: int = 60000) -> list[dict]:
    tasks = {n: s for n, s in graph.nodes.items() if s.kind == "task"}
    done = {n for n, s in tasks.items() if s.status == "done"}
    ready = sorted(n for n, s in tasks.items()
                   if s.status != "done"
                   and all(d in done or True for d in graph.targets(n, "depends_on")))
    # Readiness: deps done or scheduled in the same batch (handled by grouping deps together).
    parent = {n: n for n in ready}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]; x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    for a in ready:
        for b in ready:
            if a < b and (_shared_keys(graph, a) & _shared_keys(graph, b)):
                union(a, b)
        for dep in graph.targets(a, "depends_on"):
            if dep in parent:
                union(a, dep)
    groups: dict[str, list[str]] = {}
    for n in ready:
        groups.setdefault(find(n), []).append(n)

    batches: list[dict] = []
    for members in sorted(groups.values(), key=lambda ms: min(ms)):
        members = graph.topological_order(sorted(members))
        # Split oversize groups deterministically, keeping dependency order.
        chunks: list[list[str]] = []
        cur: list[str] = []; chars = 0
        for m in members:
            size = len(graph.nodes[m].content)
            if cur and (len(cur) >= max_tasks or chars + size > max_context_chars):
                chunks.append(cur); cur = []; chars = 0
            cur.append(m); chars += size
        if cur:
            chunks.append(cur)
        for chunk in chunks:
            shared_comps = sorted(set.intersection(*[_shared_keys(graph, m) for m in chunk])
                                  ) if len(chunk) > 1 else sorted(_shared_keys(graph, chunk[0]))
            reasons = []
            if len(chunk) > 1:
                reasons.append("shared traceability targets: " +
                               (", ".join(shared_comps) if shared_comps else "dependency chain"))
            else:
                reasons.append("single coherent task (no shared-context partner)")
            blocked_by = sorted({d for m in chunk for d in graph.targets(m, "depends_on")
                                   if d not in chunk and graph.nodes.get(d) is not None
                                   and graph.nodes[d].status != "done"})
            batches.append({"tasks": chunk,
                            "task_details": [{"canonical_id": m, "local_id": graph.nodes[m].local_id,
                                              "legacy_alias": graph.nodes[m].legacy_alias,
                                              "feature": graph.nodes[m].feature_id} for m in chunk],
                            "reasons": reasons,
                            "blocked_by": blocked_by,
                            "shared_context": shared_comps,
                            "estimated_chars": sum(len(graph.nodes[m].content) for m in chunk)})
    batches.sort(key=lambda b: b["tasks"][0])
    return batches
