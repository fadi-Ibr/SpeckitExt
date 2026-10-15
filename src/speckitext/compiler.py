"""Deterministic task/batch-scoped context compilation. No LLM, no embeddings.

Freshness contract: a package is current only when it matches the context
resolved from the CURRENT graph for its recorded selection and approved
expansions -- same tasks, dependency closure, governance, traceability
closure, source fingerprints, and compiler/schema versions -- and its own
serialized content still matches its recorded package fingerprint.
Compilation and freshness checking share one inclusion-resolution path
(`resolve_inclusion`); expansion re-renders through the same canonical
renderer as compilation, never by appending unmanaged text.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import COMPILER_VERSION, SCHEMA_VERSION
from .fingerprint import fingerprint_text
from .governance import resolve_governance
from .graph import Graph
from .validate import validate_all

PACKAGE_META_RE = re.compile(r"<!--\s*speckitext-package\s*\n(.*?)\n-->", re.DOTALL)

_KIND_ORDER = ["constitution", "requirement", "success_criterion", "decision",
               "component", "contract", "data_model", "research",
               "verification", "task"]


class CompileError(ValueError):
    pass


def resolve_inclusion(graph: Graph, task_ids: list[str],
                      extra_ids: list[str] | None = None) -> dict:
    """Canonical inclusion resolution shared by compile and freshness checks.

    Returns the ordered included section IDs, prerequisite closure, blocked
    prerequisites, and governance traces for `task_ids` plus any explicitly
    approved non-task `extra_ids` (context expansions).
    """
    task_ids = sorted(set(task_ids))
    for tid in task_ids:
        sec = graph.nodes.get(tid)
        if sec is None:
            raise CompileError(f"unknown task id: {tid}")
        if sec.kind != "task":
            raise CompileError(f"id {tid} is kind {sec.kind}, not a task")
    extra_ids = sorted(set(extra_ids or []))
    for nid in extra_ids:
        if nid not in graph.nodes:
            raise CompileError(f"unknown section id: {nid}")
        if graph.nodes[nid].kind == "task":
            raise CompileError(
                f"section {nid} is a task; tasks enter a package only as an "
                "explicit compile selection, never as a context expansion")

    included: set[str] = set(task_ids)
    prereqs = graph.dependency_closure(task_ids)
    blocked = sorted(pid for pid in prereqs
                     if (sec := graph.nodes.get(pid)) is not None
                     and sec.status != "done")
    frontier = list(task_ids) + prereqs
    visited: set[str] = set()
    while frontier:
        cur = frontier.pop()
        if cur in visited or cur not in graph.nodes:
            continue
        visited.add(cur)
        for _rel, target in graph.nodes[cur].relations():
            if target in graph.nodes and target not in included:
                included.add(target)
                frontier.append(target)
    for nid in extra_ids:
        included.add(nid)

    components = sorted({t for n in included
                         for t in graph.targets(n, "affects_component")}
                        | {t for tid in task_ids
                           for t in graph.targets(tid, "implements")
                           if t in graph.nodes and graph.nodes[t].kind == "component"})
    features = sorted({graph.nodes[t].feature for t in task_ids if graph.nodes[t].feature})
    tags = sorted({str(t) for tid in task_ids
                   for t in (graph.nodes[tid].meta.get("tags", []) or [])})
    gov_included, gov_excluded = resolve_governance(graph, components, features, tags)
    gov_ids = {g["id"] for g in gov_included}
    ordered = [n for n in included
               if graph.nodes[n].kind != "constitution" or n in gov_ids or n in extra_ids]
    for gid in gov_ids:
        if gid not in ordered:
            ordered.append(gid)
    ordered.sort(key=lambda n: (_KIND_ORDER.index(graph.nodes[n].kind)
                                if graph.nodes[n].kind in _KIND_ORDER else 99, n))
    return {"ordered": ordered, "prerequisites": prereqs, "blocked": blocked,
            "governance_included": gov_included, "governance_excluded": gov_excluded,
            "components": components, "features": features, "tags": tags}


def compile_context(graph: Graph, project: Path, task_ids: list[str],
                    expanded: list[dict] | None = None,
                    extra_ids: list[str] | None = None) -> dict:
    task_ids = sorted(set(task_ids))
    diags = validate_all(graph)
    errors = [x for x in diags if x.severity == "error"]
    if errors:
        raise CompileError("graph validation failed: " +
                           "; ".join(f"{e.code} {e.node_id}" for e in errors[:8]))
    expanded = list(expanded or [])
    if extra_ids is None:
        extra_ids = [str(e["id"]) for e in expanded if isinstance(e, dict) and "id" in e]
    inc = resolve_inclusion(graph, task_ids, extra_ids)
    ordered, prereqs, blocked = inc["ordered"], inc["prerequisites"], inc["blocked"]
    task_set = set(task_ids)
    extra_set = set(extra_ids or [])
    expansion_reasons = {str(e.get("id")): str(e.get("reason", "")) for e in expanded}

    refs: list[dict] = []
    for nid in ordered:
        sec = graph.nodes[nid]
        if nid in task_set:
            reason = "selected task"
        elif nid in extra_set and nid not in task_set:
            reason = f"expansion: {expansion_reasons.get(nid, 'approved expansion')}"
        elif nid in prereqs:
            reason = "completed prerequisite" if sec.status == "done" else "unresolved prerequisite"
        else:
            reason = _reason(graph, nid, task_ids, inc["governance_included"])
        refs.append(sec.to_ref(reason))
    meta = {
        "schema_version": SCHEMA_VERSION, "compiler_version": COMPILER_VERSION,
        "selected_tasks": sorted(task_ids),
        "prerequisites": prereqs, "blocked_prerequisites": blocked,
        "included_ids": ordered, "source_refs": refs,
        "governance_included": inc["governance_included"],
        "governance_excluded": inc["governance_excluded"],
        "expansions": expanded, "validation": "pass",
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
        lines.append(f"| {r['id']} | {r['kind']} | {r['path']} | {r['anchor']} | {r['fingerprint'][:19]}... | {r['reason']} |")
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
    for kind in _KIND_ORDER:
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


_REQUIRED_META = ("schema_version", "compiler_version", "selected_tasks",
                  "included_ids", "source_refs", "package_fingerprint")


def read_package_meta(package_path: Path) -> dict:
    try:
        text = Path(package_path).read_text(encoding="utf-8")
    except OSError as exc:
        raise CompileError(f"cannot read context package {package_path}: {exc}") from exc
    m = PACKAGE_META_RE.search(text)
    if not m:
        raise CompileError(f"not a speckitext context package (missing metadata block): {package_path}")
    try:
        meta = json.loads(m.group(1))
    except ValueError as exc:
        raise CompileError(f"invalid package metadata JSON in {package_path}: {exc}") from exc
    if not isinstance(meta, dict):
        raise CompileError(f"invalid package metadata in {package_path}: expected a JSON object")
    missing = [k for k in _REQUIRED_META if k not in meta]
    if missing:
        raise CompileError(
            f"invalid package metadata in {package_path}: missing required field(s) "
            f"{', '.join(missing)}; recompile the package")
    if str(meta["schema_version"]) != SCHEMA_VERSION:
        raise CompileError(
            f"incompatible package schema version {meta['schema_version']!r} "
            f"(this compiler writes {SCHEMA_VERSION!r}); recompile the package")
    if str(meta["compiler_version"]) != COMPILER_VERSION:
        raise CompileError(
            f"incompatible package compiler version {meta['compiler_version']!r} "
            f"(current {COMPILER_VERSION!r}); recompile the package")
    return meta


def package_staleness(graph: Graph, package_path: Path) -> list[dict]:
    """Differences between the package and the CURRENT graph's required context.

    Empty means fresh. Raises CompileError for missing/unreadable/malformed/
    incompatible packages. Detects changed source fingerprints, sections
    removed from the graph, newly required sections (new or newly applicable
    governance, changed relationships, new prerequisites), sections no longer
    required, changed prerequisite closure, and tampering with the serialized
    package body itself.
    """
    package_path = Path(package_path)
    meta = read_package_meta(package_path)
    try:
        text = package_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CompileError(f"cannot read context package {package_path}: {exc}") from exc

    stale: list[dict] = []

    def add(entry: dict) -> None:
        if entry not in stale:
            stale.append(entry)

    recorded_ids = [str(x) for x in meta.get("included_ids", [])]
    recorded_refs = {str(r.get("id")): r for r in meta.get("source_refs", [])
                     if isinstance(r, dict) and r.get("id")}
    if set(recorded_ids) != set(recorded_refs):
        add({"id": "", "kind": "package-integrity",
             "reason": "package metadata inconsistent: included_ids and source_refs disagree"})

    selected = [str(x) for x in meta.get("selected_tasks", [])]
    expansions = [e for e in meta.get("expansions", []) if isinstance(e, dict)]
    expansion_ids = [str(e["id"]) for e in expansions if "id" in e]
    expected: dict | None = None
    missing_selected = [t for t in selected if t not in graph.nodes]
    for tid in missing_selected:
        add({"id": tid, "kind": "missing-inclusion",
             "reason": "selected task no longer exists in the current graph"})
    if not missing_selected:
        try:
            expected = resolve_inclusion(
                graph, selected,
                [i for i in expansion_ids if i in graph.nodes
                 and graph.nodes[i].kind != "task"])
        except CompileError as exc:
            add({"id": "", "kind": "invalid-selection", "reason": str(exc)})

    if expected is not None:
        expected_ids = expected["ordered"]
        for nid in expected_ids:
            if nid not in recorded_ids:
                add({"id": nid, "kind": "missing-inclusion",
                     "reason": "required by the current graph/governance/closure "
                               "but absent from the package"})
        for nid in recorded_ids:
            if nid not in expected_ids:
                add({"id": nid, "kind": "extra-inclusion",
                     "reason": "present in the package but no longer required by "
                               "the current graph and not an approved expansion"})
        for pid in expected["prerequisites"]:
            if pid not in [str(x) for x in meta.get("prerequisites", [])]:
                add({"id": pid, "kind": "prerequisite-change",
                     "reason": "newly required prerequisite in the current graph"})
        for pid in [str(x) for x in meta.get("prerequisites", [])]:
            if pid not in expected["prerequisites"]:
                add({"id": pid, "kind": "prerequisite-change",
                     "reason": "recorded prerequisite no longer required by the current graph"})
        expected_set = set(expected_ids)
        for nid in expected_ids:
            if nid not in recorded_refs:
                continue
            sec = graph.nodes.get(nid)
            if sec is None:
                add({"id": nid, "kind": "missing-inclusion",
                     "reason": "source section removed from the current graph"})
            elif sec.fingerprint != recorded_refs[nid].get("fingerprint"):
                add({"id": nid, "kind": "stale-source",
                     "reason": "source fingerprint changed",
                     "package": recorded_refs[nid].get("fingerprint"),
                     "current": sec.fingerprint})
        for nid in recorded_ids:
            if nid not in expected_set and nid not in graph.nodes:
                add({"id": nid, "kind": "extra-inclusion",
                     "reason": "source section removed from the current graph"})
    else:
        for nid, ref in recorded_refs.items():
            sec = graph.nodes.get(nid)
            if sec is None:
                add({"id": nid, "kind": "missing-inclusion",
                     "reason": "source section removed from the current graph"})
            elif sec.fingerprint != ref.get("fingerprint"):
                add({"id": nid, "kind": "stale-source",
                     "reason": "source fingerprint changed",
                     "package": ref.get("fingerprint"), "current": sec.fingerprint})

    body = PACKAGE_META_RE.sub("", text, count=1)
    if fingerprint_text(body) != meta.get("package_fingerprint"):
        add({"id": "", "kind": "package-integrity",
             "reason": "package content fingerprint mismatch: the serialized "
                       "package was modified or is corrupt; recompile it"})
    return sorted(stale, key=lambda e: (str(e.get("id", "")), str(e.get("reason", ""))))


def expand_context(graph: Graph, project: Path, package_path: Path,
                   add_ids: list[str], reason: str) -> dict:
    """Expand a fresh package through the canonical renderer.

    The original selection is preserved; requested non-task sections are
    added as recorded, deduplicated expansions. Expanding with a task ID is
    refused: tasks change implementation scope and require an explicit new
    compile selection. Stale or corrupt packages are refused.
    """
    package_path = Path(package_path)
    meta = read_package_meta(package_path)
    stale = package_staleness(graph, package_path)
    if stale:
        raise CompileError(
            "cannot expand a stale package; recompile it first: " +
            "; ".join(f"{s.get('id') or 'package'}: {s['reason']}" for s in stale[:8]))
    for nid in add_ids:
        if nid not in graph.nodes:
            raise CompileError(f"cannot expand: unknown id {nid}")
        if graph.nodes[nid].kind == "task":
            raise CompileError(
                f"cannot expand with task {nid}: expansion adds context only and "
                "must not silently expand implementation scope; compile an "
                "explicit new task selection instead")
    selected = [str(x) for x in meta["selected_tasks"]]
    merged: list[dict] = []
    seen: set[str] = set()
    for entry in list(meta.get("expansions", [])) + [{"id": i, "reason": reason} for i in add_ids]:
        if not isinstance(entry, dict) or "id" not in entry:
            continue
        key = str(entry["id"])
        if key in seen:
            continue
        seen.add(key)
        merged.append({"id": key, "reason": str(entry.get("reason", reason))})
    extra_ids = [e["id"] for e in merged
                 if e["id"] in graph.nodes and graph.nodes[e["id"]].kind != "task"]
    return compile_context(graph, project, selected, expanded=merged, extra_ids=extra_ids)
