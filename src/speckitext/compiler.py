"""Deterministic task/batch-scoped context compilation. No LLM, no embeddings."""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import COMPILER_VERSION, SCHEMA_VERSION
from .fingerprint import fingerprint_text
from .governance import resolve_governance
from .graph import Graph
from .validate import validate_graph

PACKAGE_META_RE = re.compile(r"<!--\s*speckitext-package\s*\n(.*?)\n-->", re.DOTALL)


class CompileError(ValueError):
    pass


def _collect(graph: Graph, task_ids: list[str]) -> tuple[list[str], list[str], list[str]]:
    """Return (included node ids ordered, prerequisite task ids, blocked ids)."""
    for tid in task_ids:
        sec = graph.nodes.get(tid)
        if sec is None:
            raise CompileError(f"unknown task id: {tid}")
        if sec.kind != "task":
            raise CompileError(f"id {tid} is kind {sec.kind}, not a task")
    included: set[str] = set(task_ids)
    prereqs = graph.dependency_closure(task_ids)
    blocked: list[str] = []
    for pid in prereqs:
        sec = graph.nodes.get(pid)
        if sec is not None and sec.status != "done":
            blocked.append(pid)
    # Follow requirement/decision/component/contract/verification links transitively
    # (bounded closure over non-depends_on relations), plus reverse satisfies for decisions.
    frontier = list(task_ids) + prereqs
    visited: set[str] = set()
    while frontier:
        cur = frontier.pop()
        if cur in visited:
            continue
        visited.add(cur)
        for rel, target in graph.nodes[cur].relations() if cur in graph.nodes else []:
            if rel == "depends_on":
                continue
            if target in graph.nodes and target not in included:
                included.add(target); frontier.append(target)
        # Decisions/components that the included requirements point at via constrained_by.
        for rel, target in (graph.nodes[cur].relations() if cur in graph.nodes else []):
            if target in graph.nodes and target not in included:
                included.add(target); frontier.append(target)
    ordered_kinds = ["constitution", "requirement", "success_criterion", "decision",
                     "component", "contract", "data_model", "research", "verification", "task"]
    ordered = sorted(included, key=lambda n: (ordered_kinds.index(graph.nodes[n].kind)
                                              if graph.nodes[n].kind in ordered_kinds else 99, n))
    # Selected tasks last-in-order by topology among themselves; keep kind grouping but
    # order the task block topologically at render time.
    return ordered, prereqs, sorted(blocked)


def compile_context(graph: Graph, project: Path, task_ids: list[str],
                    expanded: list[dict] | None = None) -> dict:
    task_ids = sorted(set(task_ids))
    diags = validate_graph(graph)
    errors = [x for x in diags if x.severity == "error"]
    if errors:
        raise CompileError("graph validation failed: " +
                           "; ".join(f"{e.code} {e.node_id}" for e in errors[:8]))
    ordered, prereqs, blocked = _collect(graph, task_ids)
    task_set = set(task_ids)
    components = sorted({t for n in ordered for t in graph.targets(n, "affects_component")}
                        | {t for tid in task_ids for t in graph.targets(tid, "implements")
                           if t in graph.nodes and graph.nodes[t].kind == "component"})
    features = sorted({graph.nodes[t].feature for t in task_ids if graph.nodes[t].feature})
    tags = sorted({str(t) for tid in task_ids for t in (graph.nodes[tid].meta.get("tags", []) or [])})
    gov_included, gov_excluded = resolve_governance(graph, components, features, tags)
    gov_ids = {g["id"] for g in gov_included}
    ordered = [n for n in ordered if graph.nodes[n].kind != "constitution" or n in gov_ids]
    for g in gov_included:
        if g["id"] not in ordered:
            ordered.append(g["id"])
    ordered.sort(key=lambda n: (["constitution", "requirement", "success_criterion", "decision",
                                 "component", "contract", "data_model", "research",
                                 "verification", "task"].index(graph.nodes[n].kind), n))

    refs: list[dict] = []
    for nid in ordered:
        sec = graph.nodes[nid]
        if nid in task_set:
            reason = "selected task"
        elif nid in prereqs:
            reason = "completed prerequisite" if sec.status == "done" else "unresolved prerequisite"
        else:
            reason = _reason(graph, nid, task_ids, gov_included)
        refs.append(sec.to_ref(reason))
    meta = {
        "schema_version": SCHEMA_VERSION, "compiler_version": COMPILER_VERSION,
        "selected_tasks": sorted(task_ids),
        "prerequisites": prereqs, "blocked_prerequisites": blocked,
        "included_ids": ordered, "source_refs": refs,
        "governance_included": gov_included, "governance_excluded": gov_excluded,
        "expansions": expanded or [], "validation": "pass",
        "package_fingerprint": "",
    }
    body = _render(graph, meta, ordered, task_ids, prereqs, blocked)
    meta["package_fingerprint"] = fingerprint_text(body)
    text = _render(graph, meta, ordered, task_ids, prereqs, blocked, with_meta=True)
    return {"meta": meta, "text": text, "refs": refs, "blocked": blocked}


def _reason(graph: Graph, nid: str, task_ids: list[str], gov_included: list[dict]) -> str:
    for g in gov_included:
        if g["id"] == nid:
            return g["reason"]
    for tid in task_ids:
        for rel, target in graph.nodes[tid].relations():
            if target == nid:
                return f"{tid} --{rel}--> {nid}"
    return "transitive traceability closure"


def _render(graph: Graph, meta: dict, ordered: list[str], task_ids: list[str],
            prereqs: list[str], blocked: list[str], with_meta: bool = False) -> str:
    lines: list[str] = []
    if with_meta:
        # Machine-readable provenance block (compact); the human-readable
        # provenance table below carries the same data for reviewers.
        lines.append("<!-- speckitext-package")
        lines.append(json.dumps(meta, separators=(",", ":"), sort_keys=True))
        lines.append("-->")
    lines.append("# SpeckitExt Context Package")
    lines.append("")
    lines.append(f"- Selected tasks: {', '.join(sorted(task_ids))}")
    lines.append(f"- Compiler: speckitext {COMPILER_VERSION} / schema {SCHEMA_VERSION}")
    lines.append(f"- Validation: {meta['validation']}")
    if blocked:
        lines.append(f"- BLOCKED prerequisites (not done): {', '.join(blocked)}")
    lines.append("")
    lines.append("## Source provenance")
    lines.append("")
    lines.append("| ID | Kind | Source | Anchor | Fingerprint | Inclusion reason |")
    lines.append("|---|---|---|---|---|---|")
    refmap = {r["id"]: r for r in meta["source_refs"]}
    for nid in ordered:
        r = refmap[nid]
        lines.append(f"| {r['id']} | {r['kind']} | {r['path']} | {r['anchor']} | {r['fingerprint'][:19]}… | {r['reason']} |")
    lines.append("")
    by_kind: dict[str, list[str]] = {}
    for nid in ordered:
        by_kind.setdefault(graph.nodes[nid].kind, []).append(nid)
    titles = {"constitution": "Governing rules (applicable only)",
              "requirement": "Requirements", "success_criterion": "Success criteria",
              "decision": "Architecture and decisions", "component": "Components",
              "contract": "Contracts", "data_model": "Data model",
              "research": "Research references", "verification": "Verification criteria",
              "task": "Tasks"}
    for kind in ["constitution", "requirement", "success_criterion", "decision", "component",
                 "contract", "data_model", "research", "verification", "task"]:
        ids = by_kind.get(kind, [])
        if not ids:
            continue
        if kind == "task":
            ids = graph.topological_order(ids)
        lines.append(f"## {titles[kind]}")
        lines.append("")
        for nid in ids:
            sec = graph.nodes[nid]
            lines.append(sec.content.strip())
            lines.append("")
            lines.append(f"<!-- source: {sec.path}#{sec.anchor} lines {sec.start_line}-{sec.end_line} fingerprint {sec.fingerprint} -->")
            lines.append("")
    if meta.get("governance_excluded"):
        lines.append("## Governance excluded (explainable trace)")
        lines.append("")
        for g in meta["governance_excluded"]:
            lines.append(f"- {g['id']} ({g['applicability']}): {g['reason']}")
        lines.append("")
    if meta.get("expansions"):
        lines.append("## Expansions")
        lines.append("")
        for e in meta["expansions"]:
            lines.append(f"- {e['id']}: {e['reason']}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def read_package_meta(package_path: Path) -> dict:
    text = Path(package_path).read_text(encoding="utf-8")
    m = PACKAGE_META_RE.search(text)
    if not m:
        raise CompileError(f"not a speckitext context package: {package_path}")
    return json.loads(m.group(1))


def package_staleness(graph: Graph, package_path: Path) -> list[dict]:
    """Sections whose current fingerprint differs from the package's recorded one."""
    meta = read_package_meta(package_path)
    stale: list[dict] = []
    for ref in meta.get("source_refs", []):
        sec = graph.nodes.get(ref["id"])
        if sec is None:
            stale.append({"id": ref["id"], "reason": "source section removed"})
        elif sec.fingerprint != ref["fingerprint"]:
            stale.append({"id": ref["id"], "reason": "source fingerprint changed",
                          "package": ref["fingerprint"], "current": sec.fingerprint})
    return stale


def expand_context(graph: Graph, project: Path, package_path: Path,
                   add_ids: list[str], reason: str) -> dict:
    meta = read_package_meta(package_path)
    for nid in add_ids:
        if nid not in graph.nodes:
            raise CompileError(f"cannot expand: unknown id {nid}")
    selected = sorted(set(meta["selected_tasks"]) |
                      {i for i in add_ids if graph.nodes[i].kind == "task"})
    extra_refs = [graph.nodes[i] for i in add_ids if graph.nodes[i].kind != "task"]
    result = compile_context(graph, project, selected,
                             expanded=(meta.get("expansions", []) +
                                       [{"id": i, "reason": reason} for i in add_ids]))
    # Ensure explicitly requested non-task sections appear even outside closure.
    missing = [s.node_id for s in extra_refs if s.node_id not in result["meta"]["included_ids"]]
    if missing:
        for nid in missing:
            result["meta"]["included_ids"].append(nid)
            result["meta"]["source_refs"].append(graph.nodes[nid].to_ref(f"expansion: {reason}"))
        result["text"] = result["text"].rstrip() + "\n\n## Expanded sections\n\n" + \
            "\n\n".join(graph.nodes[n].content.strip() for n in missing) + "\n"
    return result
