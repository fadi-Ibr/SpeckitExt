"""Full, all-or-nothing migration of legacy Spec Kit projects.

Transaction layout (under the project, never touching sources until activation):

    .speckitext/migrations/<txn-id>/
        journal.json     state machine: prepared -> staged -> activated | rolled-back | failed
        backup/<relpath> byte-exact originals of every file activation will touch
        staged/<relpath> fully transformed copies; the staged tree is validated
                         as a complete project before activation is allowed

Activation copies staged files over the originals one by one, journaling each
step. Any failure (including an injected one) restores every touched file from
backup and marks the transaction failed. Rollback restores an activated
transaction from its backups. Re-running apply on an already-migrated project
is a no-op. Incomplete migrations (findings that block validation) can never
activate: the staged graph must validate clean first.
"""
from __future__ import annotations

import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from .graph import Graph
from .parsing import parse_text
from .project import discover_files
from .schema import ID_TOKEN_RE, kind_for_id
from .validate import is_valid, validate_graph

STATE_DIR = ".speckitext/migrations"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _next_id(existing: list[str], prefix_pattern: str, fmt: str) -> str:
    nums = []
    for e in existing:
        m = re.fullmatch(prefix_pattern, e)
        if m:
            nums.append(int(m.group(1)))
    return fmt.format((max(nums) + 1) if nums else 1)


class Migration:
    def __init__(self, project: Path):
        self.project = Path(project)

    # ---- discovery / transformation -------------------------------------
    def plan(self) -> dict:
        """Dry-run: inventory, proposed transformations, findings. Writes nothing."""
        files = discover_files(self.project)
        # Project-wide evidence first: constitution rules govern requirements by
        # definition, so GLOBAL constitution IDs are the governed_by source.
        global_consts: list[str] = []
        for p in files:
            rel0 = p.resolve().relative_to(self.project.resolve()).as_posix()
            for sec in parse_text(p.read_text(encoding="utf-8"), rel0).sections:
                if sec.kind == "constitution" and \
                        str(sec.meta.get("applicability", "GLOBAL")).upper() == "GLOBAL":
                    global_consts.append(sec.node_id)
        global_consts = sorted(set(global_consts))
        inventory, findings, transforms = [], [], {}
        existing_ids: list[str] = []
        for p in files:
            rel = p.resolve().relative_to(self.project.resolve()).as_posix()
            text = p.read_text(encoding="utf-8")
            doc = parse_text(text, rel)
            existing_ids.extend(s.node_id for s in doc.sections)
            new_text, file_findings = transform_text(text, rel, existing_ids, global_consts)
            existing_ids.extend(ID_TOKEN_RE.findall(new_text))
            inventory.append({"path": rel, "sections": [s.node_id for s in doc.sections],
                              "would_change": new_text != text})
            findings.extend(file_findings)
            if new_text != text:
                transforms[rel] = new_text
        return {"inventory": inventory, "findings": findings, "transforms": transforms,
                "already_migrated": not transforms and not findings}

    # ---- staged apply -----------------------------------------------------
    def apply(self, fail_after: int | None = None) -> dict:
        plan = self.plan()
        if plan["already_migrated"]:
            graph = Graph.build(self.project)
            if is_valid(validate_graph(graph)):
                return {"status": "noop", "detail": "already migrated and valid; nothing to do"}
            return {"status": "refused",
                    "detail": "project carries traceability metadata but graph is invalid; fix findings first",
                    "findings": plan["findings"]}
        if plan["findings"]:
            return {"status": "refused",
                    "detail": "migration findings require human resolution; activation blocked",
                    "findings": plan["findings"]}
        txn_id = _now()
        root = self.project / STATE_DIR / txn_id
        (root / "backup").mkdir(parents=True, exist_ok=True)
        (root / "staged").mkdir(parents=True, exist_ok=True)
        journal = {"txn": txn_id, "state": "prepared", "files": sorted(plan["transforms"]),
                   "completed": [], "created": _now()}
        self._write_journal(root, journal)
        # Stage: full transformed copies + untouched copies of every other artifact,
        # so the staged tree validates as a complete project.
        for p in discover_files(self.project):
            rel = p.resolve().relative_to(self.project.resolve()).as_posix()
            dest = root / "staged" / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(plan["transforms"].get(rel, p.read_text(encoding="utf-8")),
                            encoding="utf-8")
            backup = root / "backup" / rel
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(p, backup)
        journal["state"] = "staged"; self._write_journal(root, journal)
        staged_graph = Graph.build(root / "staged")
        diags = validate_graph(staged_graph)
        if not is_valid(diags):
            journal["state"] = "failed"
            journal["detail"] = "staged graph failed validation; activation refused"
            self._write_journal(root, journal)
            return {"status": "refused", "txn": txn_id,
                    "detail": journal["detail"],
                    "diagnostics": [str(x) for x in diags if x.severity == "error"]}
        # Activation: journaled, one file at a time, restore-on-any-failure.
        try:
            for i, rel in enumerate(journal["files"]):
                if fail_after is not None and i >= fail_after:
                    raise OSError("injected failure during activation")
                dest = self.project / rel
                tmp = dest.with_suffix(dest.suffix + ".speckitext-tmp")
                shutil.copyfile(root / "staged" / rel, tmp)
                os.replace(tmp, dest)
                journal["completed"].append(rel); self._write_journal(root, journal)
        except OSError as exc:
            self._restore(root, journal)
            journal["state"] = "failed"; journal["detail"] = f"activation failed, restored: {exc}"
            self._write_journal(root, journal)
            return {"status": "failed-restored", "txn": txn_id, "detail": journal["detail"]}
        journal["state"] = "activated"; self._write_journal(root, journal)
        return {"status": "activated", "txn": txn_id, "files": journal["files"]}

    def rollback(self, txn_id: str | None = None) -> dict:
        base = self.project / STATE_DIR
        if txn_id is None:
            candidates = sorted(p for p in base.glob("*") if p.is_dir()) if base.is_dir() else []
            activated = [p for p in candidates
                         if json.loads((p / "journal.json").read_text(encoding="utf-8")).get("state") == "activated"]
            if not activated:
                return {"status": "nothing-to-rollback", "detail": "no activated transaction found"}
            root = activated[-1]
        else:
            root = base / txn_id
        journal = json.loads((root / "journal.json").read_text(encoding="utf-8"))
        if journal["state"] != "activated":
            return {"status": "nothing-to-rollback",
                    "detail": f"transaction {journal['txn']} is {journal['state']}, not activated"}
        self._restore(root, journal)
        journal["state"] = "rolled-back"; self._write_journal(root, journal)
        return {"status": "rolled-back", "txn": journal["txn"], "files": journal["files"]}

    # ---- helpers ----------------------------------------------------------
    def _restore(self, root: Path, journal: dict) -> None:
        for rel in journal["files"]:
            backup = root / "backup" / rel
            dest = self.project / rel
            if backup.is_file():
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(backup, dest)

    @staticmethod
    def _write_journal(root: Path, journal: dict) -> None:
        (root / "journal.json").write_text(json.dumps(journal, indent=2), encoding="utf-8")


def transform_text(text: str, rel: str, existing_ids: list[str],
                   global_consts: list[str] | None = None) -> tuple[str, list[dict]]:
    """Add missing speckitext metadata using evidence in the text only.

    Deterministic evidence rules (documented, never invented history):
      * a heading/bullet/task ID gains an id/kind metadata block;
      * a requirement gains governed_by from the project's GLOBAL constitution
        rules (a constitution governs requirements by definition);
      * a task gains satisfies from requirement IDs named in its own text and
        verified_by from verification IDs named in its own text.
    A task with no such evidence yields a finding, not an invented link.
    """
    findings: list[dict] = []
    global_consts = global_consts or []
    lines = text.replace("\r\n", "\n").split("\n")
    out: list[str] = []

    def has_meta_after(idx: int) -> bool:
        return idx + 1 < len(lines) and "<!-- speckitext" in lines[idx + 1]

    def block_end(idx: int) -> int:
        end = len(lines)
        for k in range(idx + 1, len(lines)):
            if re.match(r"^#{1,6}\s", lines[k]) or re.match(r"^\s*-\s*\[[ xX]\]\s", lines[k]):
                end = k; break
        return end

    i = 0
    while i < len(lines):
        line = lines[i]
        out.append(line)
        heading = re.match(r"^(#{1,6})\s+(.*)$", line)
        if heading and not has_meta_after(i):
            toks = ID_TOKEN_RE.findall(heading.group(2))
            if toks and kind_for_id(toks[0]):
                out += ["<!-- speckitext", f"id: {toks[0]}",
                        f"kind: {kind_for_id(toks[0])}", "-->"]
        bullet = re.match(r"^\s*-\s*\*\*((?:FR|SC)-\d{3,})\*\*", line)
        if bullet and not has_meta_after(i) and global_consts:
            out += ["<!-- speckitext", f"id: {bullet.group(1)}",
                    f"kind: {kind_for_id(bullet.group(1))}",
                    f"governed_by: {', '.join(global_consts)}", "-->"]
        task = re.match(r"^\s*-\s*\[[ xX]\]\s+(.*)$", line)
        if task and not has_meta_after(i):
            toks = ID_TOKEN_RE.findall(task.group(1))
            if toks and kind_for_id(toks[0]) == "task":
                block = "\n".join(lines[i:block_end(i)])
                sat = sorted({t for t in ID_TOKEN_RE.findall(block)
                              if kind_for_id(t) in ("requirement", "success_criterion")})
                ver = sorted({t for t in ID_TOKEN_RE.findall(block)
                              if kind_for_id(t) == "verification"})
                if sat:
                    meta = ["<!-- speckitext", f"id: {toks[0]}", "kind: task",
                            f"satisfies: {', '.join(sat)}"]
                    if ver:
                        meta.append(f"verified_by: {', '.join(ver)}")
                    meta.append("-->")
                    out += meta
        i += 1
    new_text = "\n".join(out)
    # Tasks without evidence-based links are findings, not fabrications.
    doc2 = parse_text(new_text, rel)
    for sec in doc2.sections:
        if sec.kind != "task":
            continue
        rels = {r for r, _ in sec.relations()}
        if not ({"satisfies", "implements"} & rels):
            findings.append({"id": sec.node_id, "path": rel,
                             "finding": "task has no evidence-based requirement link; "
                                        "add a Links: line or speckitext metadata before migration"})
        elif "verified_by" not in rels:
            findings.append({"id": sec.node_id, "path": rel,
                             "finding": "task has no evidence-based verification link; "
                                        "name a VER-xxx check in the task before migration"})
    return new_text, findings
