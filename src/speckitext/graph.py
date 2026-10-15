"""Traceability graph construction and traversal (deterministic, no LLM).

Nodes are keyed by canonical ID (``<feature>::<local>``; plain for global).
Duplicate local IDs across features are distinct nodes; duplicate canonical
IDs land in ``duplicates``. All references are resolved through the single
IdentityResolver: same-feature first, explicit ``feat::ID`` for cross-feature,
unique-global fallback only when unambiguous. Unresolved/ambiguous edges are
retained with their raw target so validation can diagnose them (never a
silent first-match).
"""
from __future__ import annotations

from collections import defaultdict, deque
from pathlib import Path

from .identity import IdentityResolver, is_canonical, load_identity_map
from .parsing import Document, Section, parse_file
from .project import discover_files
from .schema import Relation


class CanonicalDict(dict):
    """dict keyed by canonical ID with unambiguous local-ID fallback lookup.

    This keeps short ``T001`` lookups working in single-feature projects
    while multi-feature projects must use canonical or feature context:
    an ambiguous local lookup raises KeyError instead of picking a winner.
    """

    def __init__(self, graph=None):
        super().__init__()
        self._graph = graph

    def _fallback(self, key):
        g = self._graph
        if g is None or not isinstance(key, str) or is_canonical(key):
            return None
        cands = g.resolver.candidates_for_local(key) if g.resolver else []
        return cands[0] if len(cands) == 1 else None

    def __getitem__(self, key):
        try:
            return super().__getitem__(key)
        except KeyError:
            fb = self._fallback(key)
            if fb is not None:
                return super().__getitem__(fb)
            raise

    def get(self, key, default=None):  # type: ignore[override]
        if super().__contains__(key):
            return super().__getitem__(key)
        fb = self._fallback(key) if isinstance(key, str) else None
        return super().__getitem__(fb) if fb is not None else default

    def __contains__(self, key):
        if super().__contains__(key):
            return True
        return isinstance(key, str) and self._fallback(key) is not None


class Graph:
    def __init__(self) -> None:
        self.nodes: CanonicalDict = CanonicalDict(self)
        self.duplicates: list[Section] = []
        self.edges: list[Relation] = []
        self.documents: list[Document] = []
        self.resolver: IdentityResolver | None = None
        self.resolution_errors: list[dict] = []  # {source, relation, raw, error}
        self.identity_map: dict = {}
        self.project = None

    @classmethod
    def build(cls, project: Path) -> "Graph":
        g = cls()
        project = Path(project)
        g.project = project
        g.identity_map = load_identity_map(project)
        all_secs: list[Section] = []
        for path in discover_files(project):
            doc = parse_file(path, project, identity_map=g.identity_map)
            g.documents.append(doc)
            g.duplicates.extend(doc.duplicates)
            for sec in doc.sections:
                if sec.node_id in dict.keys(g.nodes):
                    g.duplicates.append(sec)
                else:
                    dict.__setitem__(g.nodes, sec.node_id, sec)
                    all_secs.append(sec)
        # CanonicalDict fallback needs resolver; build it now.
        g.resolver = IdentityResolver(all_secs)
        g.nodes._graph = g  # type: ignore[attr-defined]
        # Detect duplicate local IDs within one feature with distinct
        # canonicals (conflicting explicit canonical_id) -> duplicates holder.
        seen_fl: dict[tuple[str, str], Section] = {}
        for sec in all_secs:
            key = (sec.feature_id, sec.local_id)
            prev = seen_fl.get(key)
            if prev is not None and prev.node_id != sec.node_id:
                g.duplicates.append(sec)
            else:
                seen_fl[key] = sec
        for sec in all_secs:
            resolved: list[tuple[str, str]] = []
            for rel, raw in sec.raw_relations():
                explicit = is_canonical(str(raw))
                target, err = g.resolver.try_resolve(str(raw), sec.feature_id)
                if target is None:
                    g.resolution_errors.append(
                        {"source": sec.node_id, "relation": rel, "raw": str(raw),
                         "error": err, "path": sec.path})
                    target = str(raw)  # retained unresolved for validation
                resolved.append((rel, target))
                g.edges.append(Relation(sec.node_id, rel, target,
                                        raw_target=str(raw), explicit=explicit))
            sec.meta["_resolved_relations"] = resolved
        return g

    # -- identity helpers ---------------------------------------------------
    def resolve(self, ref: str, feature: str = "") -> str:
        """Resolve a local/qualified reference to canonical (raises ValueError)."""
        assert self.resolver is not None
        return self.resolver.resolve(ref, feature)

    def candidates(self, ref: str) -> list[str]:
        assert self.resolver is not None
        return self.resolver.candidates_for_local(ref)

    # -- traversal ----------------------------------------------------------
    def out_edges(self, node_id: str, relation: str | None = None) -> list[Relation]:
        node_id = self._canon(node_id)
        return [e for e in self.edges
                if e.source == node_id and (relation is None or e.relation == relation)]

    def in_edges(self, node_id: str, relation: str | None = None) -> list[Relation]:
        node_id = self._canon(node_id)
        return [e for e in self.edges
                if e.target == node_id and (relation is None or e.relation == relation)]

    def _canon(self, node_id: str) -> str:
        if dict.__contains__(self.nodes, node_id):
            return node_id
        fb = self.nodes._fallback(node_id)  # type: ignore[attr-defined]
        return fb if fb else node_id

    def targets(self, node_id: str, relation: str | None = None) -> list[str]:
        return sorted({e.target for e in self.out_edges(node_id, relation)})

    def sources(self, node_id: str, relation: str | None = None) -> list[str]:
        return sorted({e.source for e in self.in_edges(node_id, relation)})

    def dependency_closure(self, roots: list[str]) -> list[str]:
        seen: set[str] = set()
        order: list[str] = []

        def visit(nid: str, stack: tuple[str, ...]) -> None:
            if nid in seen or nid in stack:
                return
            seen.add(nid)
            for dep in self.targets(nid, "depends_on"):
                visit(dep, stack + (nid,))
            order.append(nid)

        for r in sorted(self._canon(x) for x in roots):
            visit(r, ())
        rootset = {self._canon(x) for x in roots}
        return [n for n in order if n not in rootset]

    def reverse_dependents(self, roots: list[str]) -> list[str]:
        rev: dict[str, set[str]] = defaultdict(set)
        for e in self.edges:
            rev[e.target].add(e.source)
        seen: set[str] = set()
        canon_roots = {self._canon(r) for r in roots}
        queue: deque[str] = deque(sorted(canon_roots))
        while queue:
            cur = queue.popleft()
            for src in sorted(rev.get(cur, ())):
                if src not in seen and src not in canon_roots:
                    seen.add(src); queue.append(src)
        return sorted(seen)

    def find_cycles(self) -> list[list[str]]:
        deps = {n: self.targets(n, "depends_on") for n in dict.keys(self.nodes)}
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
        subset = [self._canon(x) for x in subset]
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
        order.extend(sorted(subset_set - set(order)))
        return order
