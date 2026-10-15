"""Markdown parsing: sections, speckitext metadata blocks, and task lines.

Identity (schema 2.0): every section has a local ID (original, e.g. T001),
a legacy alias (exact original string; empty for ID-less tasks), a feature
identity (from specs/<dir>, explicit feature:/canonical_id metadata, or a
persisted identity map), and a canonical ID (<feature>::<local>, or plain
<local> for global/shared entities). Headings/bullets/tasks are discovered
structurally; task checkboxes are recognized even with generalized legacy
labels (T070E, G5-T1, TR-A) or with no ID at all (deterministic T-AUTO-*).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .fingerprint import fingerprint_text
from .identity import (feature_from_path, generated_local_id, make_canonical,
                       sanitize_feature, split_canonical)
from .schema import ID_TOKEN_RE, LEGACY_TASK_RE, RELATIONS, kind_for_id, local_part

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
META_START_RE = re.compile(r"^\s*<!--\s*speckitext\s*$")
META_END_RE = re.compile(r"^\s*-->\s*$")
TASK_RE = re.compile(r"^\s*-\s*\[(?P<mark>[ xX])\]\s*(?P<rest>.*)$")
BULLET_ID_RE = re.compile(r"^\s*-\s*\*\*(?P<id>(?:CON|FR|SC|DEC|COMP|CTR|DM|VER|RES)-\d{3,}|T\d{1,6}[A-Z]?|[A-Za-z0-9][A-Za-z0-9._-]*::[A-Za-z0-9_-]+)\*\*\s*:?\s*(?P<rest>.*)$")
LINKS_RE = re.compile(r"^\s*(?:Links|Relations)\s*:\s*(?P<rest>.+)$", re.IGNORECASE)
# Legacy task label at the very start of a checkbox body: bold, bracketed,
# colon/dash terminated, or followed by whitespace + text. Structural only.
_TASK_LEAD_RE = re.compile(
    r"^(?:\*\*(?P<bold>[A-Za-z0-9][A-Za-z0-9_-]{1,40})\*\*|\[(?P<brack>[A-Za-z0-9][A-Za-z0-9_-]{1,40})\]|"
    r"(?P<plain>[A-Z][A-Za-z0-9_-]{1,40})(?=\s*[:\-–]\s|\s+))\s*:?\s*(?P<rest>.*)$")


def document_role(rel_path: str) -> str:
    """Document role determines checkbox meaning (not the checkbox alone).

    ``tasks``: a ``tasks.md`` file -- checkboxes are implementation tasks.
    ``checklist``: a file under a ``checklists/`` directory -- checkboxes are
    quality-gate checklist items, never implementation tasks.
    ``other``: any other artifact -- checkboxes are not implementation tasks.
    """
    parts = [p for p in str(rel_path).replace("\\", "/").split("/") if p]
    if "checklists" in parts:
        return "checklist"
    if parts and parts[-1] == "tasks.md":
        return "tasks"
    return "other"


def is_task_bearing(rel_path: str) -> bool:
    return document_role(rel_path) == "tasks"


def slugify(heading: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", heading.lower()).strip("-")
    return slug or "section"


def _parse_meta_lines(lines: list[str]) -> dict:
    meta: dict = {}
    for raw in lines:
        line = raw.strip()
        if not line or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key, value = key.strip(), value.strip()
        if key in RELATIONS or key in ("scope",):
            meta[key] = [v.strip() for v in value.split(",") if v.strip()]
        else:
            meta[key] = value
    return meta


@dataclass
class Section:
    node_id: str  # canonical ID
    kind: str
    heading: str
    anchor: str
    content: str
    path: str
    start_line: int
    end_line: int
    meta: dict = field(default_factory=dict)
    status: str = ""
    local_id: str = ""
    legacy_alias: str = ""
    feature_id: str = ""
    id_missing: bool = False

    def __post_init__(self):
        if not self.local_id:
            self.local_id = split_canonical(self.node_id)[1]
        if not self.feature_id:
            self.feature_id = split_canonical(self.node_id)[0] or feature_from_path(self.path)
            if str(self.meta.get("feature", "")).strip():
                self.feature_id = sanitize_feature(str(self.meta["feature"]))
        if "legacy_alias" in (self.meta or {}):
            self.legacy_alias = str(self.meta["legacy_alias"])
        elif not self.legacy_alias and not self.id_missing:
            self.legacy_alias = self.local_id
        if str((self.meta or {}).get("id_missing", "")).lower() == "true":
            self.id_missing = True

    @property
    def fingerprint(self) -> str:
        return fingerprint_text(self.content)

    @property
    def feature(self) -> str:
        return self.feature_id or str(self.meta.get("feature", ""))

    def raw_relations(self) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        for rel in RELATIONS:
            for target in self.meta.get(rel, []) or []:
                out.append((rel, target))
        return out

    def relations(self) -> list[tuple[str, str]]:
        # Raw (unresolved) targets as authored; Graph resolves to canonical.
        # Sections outside a Graph expose raw relations for compatibility.
        resolved = self.meta.get("_resolved_relations")
        if resolved is not None:
            return list(resolved)
        return self.raw_relations()

    def to_ref(self, reason: str = "") -> dict:
        return {"id": self.node_id, "canonical_id": self.node_id,
                "local_id": self.local_id, "legacy_alias": self.legacy_alias,
                "feature": self.feature_id, "kind": self.kind, "path": self.path,
                "anchor": self.anchor, "lines": [self.start_line, self.end_line],
                "fingerprint": self.fingerprint, "reason": reason}


@dataclass
class Document:
    path: str
    sections: list[Section] = field(default_factory=list)
    duplicates: list[Section] = field(default_factory=list)
    raw: str = ""
    task_occurrences: int = 0  # implementation-task checkbox count (tasks.md only)
    role: str = "other"
    checklist_items: list[dict] = field(default_factory=list)

    @property
    def checklist_occurrences(self) -> int:
        return len(self.checklist_items)

    @property
    def checklist_completed(self) -> int:
        return sum(1 for i in self.checklist_items if i.get("status") == "done")

    @property
    def checklist_pending(self) -> int:
        return sum(1 for i in self.checklist_items if i.get("status") != "done")


def _ids_in(text: str) -> list[str]:
    seen: list[str] = []
    for tok in ID_TOKEN_RE.findall(text):
        if tok not in seen:
            seen.append(tok)
    return seen


def _feature_for(rel_path: str, meta: dict, identity_map: dict | None) -> str:
    if identity_map:
        derived = feature_from_path(rel_path)
        mapped = (identity_map.get("features") or {}).get(derived)
        if mapped:
            return sanitize_feature(str(mapped))
    explicit = str(meta.get("feature", "")).strip() if meta else ""
    if explicit:
        return sanitize_feature(explicit)
    return feature_from_path(rel_path)


def _canonical_for(meta: dict, local: str, kind: str, feature: str) -> str:
    canon = str(meta.get("canonical_id", "")).strip() if meta else ""
    if canon:
        return canon
    return make_canonical(feature, local, kind)


def extract_task_local(rest: str, meta: dict) -> tuple[str, bool]:
    """(local_id, id_missing) for a checkbox body. Meta id wins; then a
    canonical/standard/legacy label in structural leading position."""
    mid = str(meta.get("id", "")).strip() if meta else ""
    if mid:
        return split_canonical(mid)[1], False
    canon_meta = str(meta.get("canonical_id", "")).strip() if meta else ""
    if canon_meta:
        return split_canonical(canon_meta)[1], False
    m = _TASK_LEAD_RE.match(rest.strip())
    if m:
        cand = m.group("bold") or m.group("brack") or m.group("plain") or ""
        if "::" in cand:
            return split_canonical(cand)[1], False
        if LEGACY_TASK_RE.fullmatch(cand) or kind_for_id(cand) == "task":
            return cand, False
        # Structured custom ID: uppercase-led label with digit or hyphen.
        if re.fullmatch(r"[A-Z][A-Za-z0-9_-]*", cand) and (any(c.isdigit() for c in cand) or "-" in cand or "_" in cand):
            return cand, False
    toks = _ids_in(rest)
    for tok in toks:
        if "::" in tok:
            return split_canonical(tok)[1], False
        if kind_for_id(tok) == "task" and LEGACY_TASK_RE.fullmatch(tok):
            return tok, False
    return "", True


def parse_text(text: str, rel_path: str, identity_map: dict | None = None) -> Document:
    lines = text.replace("\r\n", "\n").split("\n")
    doc = Document(path=rel_path, raw=text)
    doc.role = document_role(rel_path)
    _in_checklist_heading = False
    _checklist_flags: list[bool] = []
    for _ln in lines:
        _hm = HEADING_RE.match(_ln)
        if _hm:
            _in_checklist_heading = "checklist" in _hm.group(2).lower()
        _checklist_flags.append(_in_checklist_heading)
    def _is_task_line(idx: int) -> bool:
        return bool(TASK_RE.match(lines[idx])) and doc.role == "tasks" and not _checklist_flags[idx]
    def _is_checklist_line(idx: int) -> bool:
        return bool(TASK_RE.match(lines[idx])) and not _is_task_line(idx)
    doc.task_occurrences = sum(1 for _i in range(len(lines)) if _is_task_line(_i))
    for _i, _ln in enumerate(lines):
        _cm = TASK_RE.match(_ln)
        if _cm and _is_checklist_line(_i):
            doc.checklist_items.append({"text": _cm.group("rest").strip(), "status": "done" if _cm.group("mark").lower() == "x" else "pending", "line": _i + 1, "path": rel_path})
    heading_idx: list[tuple[int, int, str]] = []
    meta_blocks: list[tuple[int, int, dict]] = []
    i = 0
    while i < len(lines):
        if META_START_RE.match(lines[i]):
            buf: list[str] = []
            j = i + 1
            while j < len(lines) and not META_END_RE.match(lines[j]):
                buf.append(lines[j]); j += 1
            meta_blocks.append((i, j, _parse_meta_lines(buf)))
            i = j + 1
            continue
        m = HEADING_RE.match(lines[i])
        if m:
            heading_idx.append((i, len(m.group(1)), m.group(2)))
        i += 1

    def meta_for_heading(line_no: int) -> dict:
        # A block directly following the heading wins; only then a block
        # directly preceding it. Another heading in between breaks the
        # association in either direction.
        heading_lines = [h[0] for h in heading_idx]

        def _clear(a: int, b: int) -> bool:
            # No other heading/bullet/task section may start between.
            return not any(a < h < b for h in heading_lines) and not any(
                BULLET_ID_RE.match(lines[k]) or TASK_RE.match(lines[k])
                for k in range(a + 1, b))

        for start, end, meta in meta_blocks:
            if 0 < start - line_no <= 2 and _clear(line_no, start):
                return dict(meta)
        for start, end, meta in meta_blocks:
            if 0 < line_no - end <= 2 and _clear(end, line_no):
                return dict(meta)
        return {}

    def section_range(idx: int) -> tuple[int, int]:
        start, level, _ = heading_idx[idx]
        end = len(lines)
        for k in range(idx + 1, len(heading_idx)):
            if heading_idx[k][1] <= level:
                end = heading_idx[k][0]
                break
        return start, end

    captured: set[str] = set()  # canonical IDs
    taken_locals: dict[str, set[str]] = {}  # feature -> locals (for T-AUTO dedup)

    for idx, (start, level, heading) in enumerate(heading_idx):
        if doc.role == "checklist":
            continue
        end_s, end_e = section_range(idx)
        content = "\n".join(lines[start:end_e])
        meta = meta_for_heading(start)
        raw_id = str(meta.get("id", "")).strip() or str(meta.get("canonical_id", "")).strip()
        if not raw_id:
            toks = _ids_in(heading)
            raw_id = toks[0] if toks else ""
        if not raw_id:
            continue
        local = split_canonical(raw_id)[1]
        kind = str(meta.get("kind", "")).strip() or (kind_for_id(local) or "")
        if not kind:
            continue
        feature = _feature_for(rel_path, meta, identity_map)
        if "::" in raw_id:
            feature = split_canonical(raw_id)[0] or feature
        canonical = _canonical_for(meta, local, kind, feature)
        sec = Section(node_id=canonical, kind=kind, heading=heading, anchor=slugify(heading),
                      content=content, path=rel_path, start_line=start + 1, end_line=end_e,
                      meta=meta, status=str(meta.get("status", "")).strip(),
                      local_id=local, legacy_alias=local, feature_id=feature)
        (doc.duplicates if canonical in captured else doc.sections).append(sec)
        captured.add(canonical)
        taken_locals.setdefault(feature, set()).add(local)

    for n, line in enumerate(lines):
        if doc.role == 'checklist':
            continue
        m = BULLET_ID_RE.match(line)
        if not m:
            continue
        raw_id = m.group("id")
        local = split_canonical(raw_id)[1]
        end = len(lines)
        for k in range(n + 1, len(lines)):
            if BULLET_ID_RE.match(lines[k]) or HEADING_RE.match(lines[k]):
                end = k; break
        content = "\n".join(lines[n:end])
        meta = _meta_after(lines, n, end)
        meta_id = str(meta.get("id", "")).strip()
        if meta_id:
            local = split_canonical(meta_id)[1]
        kind = str(meta.get("kind", "")).strip() or (kind_for_id(local) or "")
        if not kind:
            continue
        feature = _feature_for(rel_path, meta, identity_map)
        if "::" in raw_id:
            feature = split_canonical(raw_id)[0] or feature
        canonical = _canonical_for(meta, local, kind, feature)
        sec = Section(node_id=canonical, kind=kind, heading=m.group("rest")[:80] or local,
                      anchor=slugify(local), content=content, path=rel_path,
                      start_line=n + 1, end_line=end, meta={**meta, "id": local},
                      status=str(meta.get("status", "")).strip(),
                      local_id=local, legacy_alias=local, feature_id=feature)
        (doc.duplicates if canonical in captured else doc.sections).append(sec)
        captured.add(canonical)
        taken_locals.setdefault(feature, set()).add(local)

    for n, line in enumerate(lines):
        if not _is_task_line(n):
            continue
        m = TASK_RE.match(line)
        if not m:
            continue
        end = len(lines)
        for k in range(n + 1, len(lines)):
            if TASK_RE.match(lines[k]) or HEADING_RE.match(lines[k]):
                end = k; break
        block = lines[n:end]
        meta = _meta_after(lines, n, end)
        feature = _feature_for(rel_path, meta, identity_map)
        local, missing = extract_task_local(m.group("rest"), meta)
        if missing:
            taken = taken_locals.setdefault(feature, set())
            local = generated_local_id(m.group("rest"), taken)
        taken_locals.setdefault(feature, set()).add(local)
        canonical = _canonical_for(meta, local, "task", feature)
        links = _links_in(block)
        for rel, targets in links.items():
            merged = list(meta.get(rel, []) or [])
            for t in targets:
                if t not in merged:
                    merged.append(t)
            meta[rel] = merged
        sec = Section(node_id=canonical, kind="task",
                      heading=m.group("rest").strip(), anchor=slugify(local),
                      content="\n".join(block), path=rel_path, start_line=n + 1, end_line=end,
                      meta={**meta, "id": local},
                      status="done" if m.group("mark").lower() == "x" else "pending",
                      local_id=local, legacy_alias="" if missing else local,
                      feature_id=feature, id_missing=missing)
        (doc.duplicates if canonical in captured else doc.sections).append(sec)
        captured.add(canonical)

    all_secs = doc.sections + doc.duplicates
    for sec in all_secs:
        later = [o.start_line for o in all_secs
                 if sec.start_line < o.start_line <= sec.end_line and o is not sec]
        if later:
            cut = min(later)
            sec.content = "\n".join(lines[sec.start_line - 1:cut - 1])
            sec.end_line = cut - 1
    doc.sections.sort(key=lambda s: s.start_line)
    doc.duplicates.sort(key=lambda s: s.start_line)
    return doc


def _meta_after(lines: list[str], start: int, end: int) -> dict:
    for n in range(start, min(end, len(lines))):
        if META_START_RE.match(lines[n]):
            buf: list[str] = []
            j = n + 1
            while j < len(lines) and not META_END_RE.match(lines[j]):
                buf.append(lines[j]); j += 1
            return _parse_meta_lines(buf)
    return {}


def _links_in(block: list[str]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for line in block:
        m = LINKS_RE.match(line)
        if m:
            for tok in _ids_in(m.group("rest")):
                kind = kind_for_id(split_canonical(tok)[1])
                if kind is None and LEGACY_TASK_RE.fullmatch(split_canonical(tok)[1]):
                    kind = "task"  # Links: line is structural task context
                rel = {"requirement": "satisfies", "success_criterion": "satisfies",
                       "task": "depends_on", "constitution": "governed_by",
                       "component": "affects_component", "decision": "implements",
                       "contract": "implements", "data_model": "implements",
                       "verification": "verified_by"}.get(kind or "", "")
                if rel:
                    out.setdefault(rel, []).append(tok)
        dep = re.search(r"\(depends on ([^)]+)\)", line, re.IGNORECASE)
        if dep:
            for tok in _ids_in(dep.group(1)):
                if kind_for_id(split_canonical(tok)[1]) == "task" or LEGACY_TASK_RE.fullmatch(split_canonical(tok)[1]):
                    out.setdefault("depends_on", []).append(tok)
    return out


def parse_file(path: Path, project_root: Path, identity_map: dict | None = None) -> Document:
    text = path.read_text(encoding="utf-8")
    rel = path.resolve().relative_to(project_root.resolve()).as_posix()
    return parse_text(text, rel, identity_map=identity_map)
