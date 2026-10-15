"""Traceability graph construction and traversal (deterministic, no LLM)."""
from __future__ import annotations

from collections import defaultdict, deque
from pathlib import Path

from .parsing import Document, Section, parse_file
from .project import discover_files
from .schema import Relation


class Graph:
    def __init__(self) -> None:
        self.nodes: dict[str, Section] = {}
        self.duplicates: list[Section] = []
        self.edges: list[Relation] = []
        self.documents: list[Document] = []

    @classmethod
    def build(cls, project: Path) -> "Graph":
        g = cls()
        for path in discover_files(Path(project)):
            doc = parse_file(path, Path(project))
            g.documents.append(doc)
            g.duplicates.extend(doc.duplicates)
            for sec in doc.sections:
                if sec.node_id in g.nodes:
                    g.duplicates.append(sec)
                else:
                    g.nodes[sec.node_id] = sec
        for sec in g.nodes.values():
            for rel, target in sec.relations():
                g.edges.append(Relation(sec.node_id, rel, target))
        return g

    def out_edges(self, node_id: str, relation: str | None = None) -> list[Relation]:
        return [e for e in self.edges
                if e.source == node_id and (relation is None or e.relation == relation)]

    def in_edges(self, node_id: str, relation: str | None = None) -> list[Relation]:
        return [e for e in self.edges
                if e.target == node_id and (relation is None or e.relation == relation)]

    def targets(self, node_id: str, relation: str | None = None) -> list[str]:
        return sorted({e.target for e in self.out_edges(node_id, relation)})

    def sources(self, node_id: str, relation: str | None = None) -> list[str]:
        return sorted({e.source for e in self.in_edges(node_id, relation)})

    def dependency_closure(self, roots: list[str]) -> list[str]:
        """Transitive depends_on prerequisites of roots, topologically ordered."""
        seen: set[str] = set()
        order: list[str] = []
        def visit(nid: str, stack: tuple[str, ...]) -> None:
            if nid in seen or nid in stack:
                return
            seen.add(nid)
            for dep in self.targets(nid, "depends_on"):
                visit(dep, stack + (nid,))
            order.append(nid)
        for r in sorted(roots):
            visit(r, ())
        return [n for n in order if n not in set(roots)]

    def reverse_dependents(self, roots: list[str]) -> list[str]:
        """Everything that (transitively) references any root, via any relation."""
        rev: dict[str, set[str]] = defaultdict(set)
        for e in self.edges:
            rev[e.target].add(e.source)
        seen: set[str] = set()
        queue: deque[str] = deque(sorted(roots))
        while queue:
            cur = queue.popleft()
            for src in sorted(rev.get(cur, ())):
                if src not in seen and src not in set(roots):
                    seen.add(src); queue.append(src)
        return sorted(seen)

    def find_cycles(self) -> list[list[str]]:
        """Cycles in the depends_on subgraph, each reported once (sorted nodes)."""
        deps = {n: self.targets(n, "depends_on") for n in self.nodes}
        cycles: list[list[str]] = []
        reported: set[tuple[str, ...]] = set()
        WHITE, GRAY, BLACK = 0, 1, 2
        color = {n: WHITE for n in deps}
        def dfs(node: str, stack: list[str]) -> None:
            color[node] = GRAY; stack.append(node)
            for nxt in deps.get(node, []):
                if nxt not in color:
                    continue
                if color[nxt] == GRAY:
                    cyc = tuple(sorted(stack[stack.index(nxt):]))
                    if cyc not in reported:
                        reported.add(cyc); cycles.append(list(cyc))
                elif color[nxt] == WHITE:
                    dfs(nxt, stack)
            stack.pop(); color[node] = BLACK
        for n in sorted(deps):
            if color[n] == WHITE:
                dfs(n, [])
        return cycles

    def topological_order(self, subset: list[str]) -> list[str]:
        """Dependencies first; deterministic alphabetical tie-break."""
        subset_set = set(subset)
        indeg = {n: 0 for n in subset_set}
        adj: dict[str, list[str]] = defaultdict(list)
        for n in subset_set:
            for dep in self.targets(n, "depends_on"):
                if dep in subset_set:
                    adj[dep].append(n); indeg[n] += 1
        ready = sorted(n for n, d in indeg.items() if d == 0)
        order: list[str] = []
        while ready:
            cur = ready.pop(0); order.append(cur)
            for nxt in sorted(adj[cur]):
                indeg[nxt] -= 1
                if indeg[nxt] == 0:
                    ready.append(nxt); ready.sort()
        order.extend(sorted(subset_set - set(order)))  # cycle remainder, deterministic
        return order
