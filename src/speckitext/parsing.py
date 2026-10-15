"""Markdown parsing: sections, speckitext metadata blocks, and task lines.

A section starts at an ATX heading. A section owns the lines up to the next
heading of the same or higher level. Metadata lives in an HTML comment:

    <!-- speckitext
    key: value, value
    -->

Headings may also carry an ID directly, e.g. ``### FR-001: Do the thing`` or
``- **FR-001**: requirement text`` bullet form used by Spec Kit spec templates.
Tasks are checkbox lines ``- [ ] T001 ...`` / ``- [x] T001 ...`` optionally
followed by an indented metadata comment or a ``Links:`` line.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .fingerprint import fingerprint_text
from .schema import ID_TOKEN_RE, RELATIONS, kind_for_id

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
META_START_RE = re.compile(r"^\s*<!--\s*speckitext\s*$")
META_END_RE = re.compile(r"^\s*-->\s*$")
TASK_RE = re.compile(r"^\s*-\s*\[(?P<mark>[ xX])\]\s+(?P<rest>.*)$")
BULLET_ID_RE = re.compile(r"^\s*-\s*\*\*(?P<id>(?:CON|FR|SC|DEC|COMP|CTR|DM|VER|RES)-\d{3,}|T\d{3,})\*\*\s*:?\s*(?P<rest>.*)$")
LINKS_RE = re.compile(r"^\s*(?:Links|Relations)\s*:\s*(?P<rest>.+)$", re.IGNORECASE)


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
    node_id: str
    kind: str
    heading: str
    anchor: str
    content: str
    path: str  # project-relative POSIX path
    start_line: int
    end_line: int
    meta: dict = field(default_factory=dict)
    status: str = ""  # tasks: pending|done; others: meta status or ""

    @property
    def fingerprint(self) -> str:
        return fingerprint_text(self.content)

    @property
    def feature(self) -> str:
        return str(self.meta.get("feature", ""))

    def relations(self) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        for rel in RELATIONS:
            for target in self.meta.get(rel, []) or []:
                out.append((rel, target))
        return out

    def to_ref(self, reason: str = "") -> dict:
        return {"id": self.node_id, "kind": self.kind, "path": self.path,
                "anchor": self.anchor, "lines": [self.start_line, self.end_line],
                "fingerprint": self.fingerprint, "reason": reason}


@dataclass
class Document:
    path: str
    sections: list[Section] = field(default_factory=list)
    duplicates: list[Section] = field(default_factory=list)
    raw: str = ""


def _ids_in(text: str) -> list[str]:
    seen: list[str] = []
    for tok in ID_TOKEN_RE.findall(text):
        if tok not in seen:
            seen.append(tok)
    return seen


def parse_text(text: str, rel_path: str) -> Document:
    lines = text.replace("\r\n", "\n").split("\n")
    doc = Document(path=rel_path, raw=text)
    # Pass 1: locate headings and metadata blocks. A metadata block belongs to
    # the heading it directly follows (within 2 lines); a block directly before
    # a heading is also accepted for robustness.
    heading_idx: list[tuple[int, int, str]] = []  # (line_no, level, heading)
    meta_blocks: list[tuple[int, int, dict]] = []  # (start_line, end_line, meta)
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
        for start, end, meta in meta_blocks:
            if 0 < start - line_no <= 2 or 0 < line_no - end <= 2:
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

    used_ids: set[int] = set()  # heading indexes consumed as sections
    for idx, (start, level, heading) in enumerate(heading_idx):
        end_s, end_e = section_range(idx)
        content = "\n".join(lines[start:end_e])
        meta = meta_for_heading(start)
        node_id = str(meta.get("id", "")).strip()
        if not node_id:
            toks = _ids_in(heading)
            node_id = toks[0] if toks else ""
        if not node_id:
            continue
        kind = str(meta.get("kind", "")).strip() or (kind_for_id(node_id) or "")
        if not kind:
            continue
        used_ids.add(idx)
        doc.sections.append(Section(
            node_id=node_id, kind=kind, heading=heading, anchor=slugify(heading),
            content=content, path=rel_path, start_line=start + 1, end_line=end_e,
            meta=meta, status=str(meta.get("status", "")).strip()))

    # Pass 2: bullet-ID lines (spec template style) not already captured.
    captured = {s.node_id for s in doc.sections}
    for n, line in enumerate(lines):
        m = BULLET_ID_RE.match(line)
        if m:
            node_id = m.group("id")
            is_dup = node_id in captured
            # Content extends to next bullet-ID or next heading.
            end = len(lines)
            for k in range(n + 1, len(lines)):
                if BULLET_ID_RE.match(lines[k]) or HEADING_RE.match(lines[k]):
                    end = k; break
            content = "\n".join(lines[n:end])
            meta = _meta_after(lines, n, end)
            kind = str(meta.get("kind", "")).strip() or (kind_for_id(node_id) or "")
            sec = Section(
                node_id=node_id, kind=kind, heading=m.group("rest")[:80] or node_id,
                anchor=slugify(node_id), content=content, path=rel_path,
                start_line=n + 1, end_line=end, meta={**meta, "id": node_id},
                status=str(meta.get("status", "")).strip())
            (doc.duplicates if is_dup else doc.sections).append(sec)
            captured.add(node_id)

    # Pass 3: task checkbox lines.
    for n, line in enumerate(lines):
        m = TASK_RE.match(line)
        if not m:
            continue
        toks = _ids_in(m.group("rest"))
        if not toks or kind_for_id(toks[0]) != "task":
            continue
        node_id = toks[0]
        is_dup = node_id in captured
        end = len(lines)
        for k in range(n + 1, len(lines)):
            if TASK_RE.match(lines[k]) or HEADING_RE.match(lines[k]):
                end = k; break
        block = lines[n:end]
        meta = _meta_after(lines, n, end)
        links = _links_in(block)
        for rel, targets in links.items():
            merged = list(meta.get(rel, []) or [])
            for t in targets:
                if t not in merged:
                    merged.append(t)
            meta[rel] = merged
        sec = Section(
            node_id=node_id, kind="task",
            heading=m.group("rest").strip(), anchor=slugify(node_id),
            content="\n".join(block), path=rel_path, start_line=n + 1, end_line=end,
            meta={**meta, "id": node_id},
            status="done" if m.group("mark").lower() == "x" else "pending")
        (doc.duplicates if is_dup else doc.sections).append(sec)
        captured.add(node_id)
    # A section's own content ends where the next captured section begins, so
    # e.g. a VER-xxx heading does not swallow the task list that follows it.
    all_secs = doc.sections + doc.duplicates
    for sec in all_secs:
        later = [o.start_line for o in all_secs
                 if sec.start_line < o.start_line <= sec.end_line and o is not sec]
        if later:
            cut = min(later)
            sec.content = "\n".join(lines[sec.start_line - 1:cut - 1])
            sec.end_line = cut - 1
    doc.sections.sort(key=lambda s: s.start_line)
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
                kind = kind_for_id(tok)
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
                if kind_for_id(tok) == "task":
                    out.setdefault("depends_on", []).append(tok)
    return out


def parse_file(path: Path, project_root: Path) -> Document:
    text = path.read_text(encoding="utf-8")
    rel = path.resolve().relative_to(project_root.resolve()).as_posix()
    return parse_text(text, rel)
