"""Full, all-or-nothing migration of legacy Spec Kit projects.

Durable transaction state machine (journal schema 2):

    prepared -> staged -> activating -> activated
    any non-terminal state --recover()--> recovered
    activated --rollback()--> rolling-back -> rolled-back
    interrupted rolling-back --recover()/rollback()--> rolled-back
    in-process activation failure -> failed (originals already restored)

Transaction layout (kept separate from authored content):

    .speckitext/migrations/<txn-id>/
        journal.json     state, per-file backup/staged SHA-256 manifest
        backup/<relpath> byte-exact originals of every file activation touches
        staged/<relpath> fully transformed copies, validated as a complete
                         project (graph + pending-task readiness) before
                         activation is allowed

Filesystem multi-file replacement is not atomic, so this module provides
recoverable logical atomicity: recovery evidence (backups + hashed journal)
is persisted and fsynced before any project file is replaced, the journal is
advanced after every replacement, and an interruption that lands between a
replacement and its journal update is reconciled on recovery by comparing
current file hashes against the backup/staged manifest. Recovery preflights
the whole transaction before touching any destination: a destination that
matches neither its original nor its staged hash is a recovery conflict,
is preserved untouched, and must be resolved explicitly (restore the file
to its original or staged content, or restore from backup/ manually).
A project with a non-terminal transaction is blocked from use until
`recover()` restores the byte-exact originals. Rollback follows the same
preflight -> restore -> verify -> finalize contract: it refuses missing
or corrupt backups and files edited after activation unless an explicit
forced resolution is requested, records progress under the rolling-back
state (so an interrupted rollback can be resumed by rollback() or
completed by recover()), and only reports rolled-back after every
restored file verifies against its original hash.
"""
from __future__ import annotations

import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from .fingerprint import fingerprint_bytes
from .graph import Graph
from .identity import (IDENTITY_PATH, IDENTITY_VERSION, feature_from_path,
                       generated_local_id, make_canonical, split_canonical)
from .parsing import extract_task_local, parse_text
from .project import discover_files
from .schema import ID_TOKEN_RE, kind_for_id
from .validate import is_valid, validate_all, validate_graph


def _matches_original(project, record) -> bool:
    dest = Path(project) / record["path"]
    if record.get("created"):
        return not dest.is_file()
    return dest.is_file() and _sha(dest) == record.get("backup_sha256")

STATE_DIR = ".speckitext/migrations"
JOURNAL_SCHEMA = 2
TERMINAL_STATES = ("activated", "rolled-back", "recovered", "failed")
INCOMPLETE_STATES = ("prepared", "staged", "activating", "recovery-required",
                     "rolling-back")

# ID-less headings in these files gain deterministic IDs of the mapped kind.
_HEADING_ID_ROLES = {
    "constitution.md": ("CON", "constitution"),
    "plan.md": ("DEC", "decision"),
    "data-model.md": ("DM", "data_model"),
    "research.md": ("RES", "research"),
}


class MigrationCrash(BaseException):
    """Simulated process death during activation (never caught in-process)."""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _next_id(existing: list[str], prefix_pattern: str, fmt: str) -> str:
    nums = []
    for e in existing:
        m = re.fullmatch(prefix_pattern, e)
        if m:
            nums.append(int(m.group(1)))
    return fmt.format((max(nums) + 1) if nums else 1)


def _alloc_id(existing: list[str], prefix: str) -> str:
    nums = [int(m.group(1)) for e in existing
            if (m := re.fullmatch(re.escape(prefix) + r"-(\d+)", e))]
    nid = f"{prefix}-{(max(nums) + 1) if nums else 1:03d}"
    existing.append(nid)
    return nid


def _fsync_file(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _fsync_dir(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _sha(path: Path) -> str:
    return fingerprint_bytes(path.read_bytes())


def incomplete_migrations(project: Path) -> list[dict]:
    """Non-terminal (or unreadable) migration transactions blocking use."""
    base = Path(project) / STATE_DIR
    out: list[dict] = []
    if not base.is_dir():
        return out
    for root in sorted(p for p in base.glob("*") if p.is_dir()):
        journal_path = root / "journal.json"
        if not journal_path.is_file():
            out.append({"txn": root.name, "state": "recovery-required",
                        "reason": "journal.json missing; transaction state unknown",
                        "recovery": "inspect .speckitext/migrations and restore "
                                    "from backup/ manually, then remove the "
                                    "transaction directory"})
            continue
        try:
            journal = json.loads(journal_path.read_text(encoding="utf-8"))
        except ValueError:
            out.append({"txn": root.name, "state": "recovery-required",
                        "reason": "journal.json is corrupt (invalid JSON)",
                        "recovery": "restore project files from the transaction "
                                    "backup/ directory, then remove the "
                                    "transaction directory"})
            continue
        state = journal.get("state", "")
        if state not in TERMINAL_STATES:
            out.append({"txn": journal.get("txn", root.name), "state": state,
                        "reason": f"migration transaction is {state or 'in an unknown state'}, not activated",
                        "recovery": "run `speckitext migrate --project . --recover`"})
    return out


def migration_block(project: Path) -> dict | None:
    """Recovery-required diagnostic if the project is partially migrated."""
    incomplete = incomplete_migrations(project)
    if not incomplete:
        return None
    return {"status": "recovery-required", "incomplete": incomplete,
            "detail": "project has an incomplete migration and must not be "
                      "used until recovered: " +
                      "; ".join(f"{i['txn']} ({i['state']}): {i['reason']}"
                                for i in incomplete),
            "recovery_command": "speckitext migrate --project . --recover"}


class Migration:
    def __init__(self, project: Path):
        self.project = Path(project)

    # ---- discovery / transformation -------------------------------------
    def plan(self) -> dict:
        """Dry-run: inventory, proposed transformations, findings. Writes nothing."""
        files = discover_files(self.project)
        texts: dict[str, str] = {}
        for p in files:
            rel = p.resolve().relative_to(self.project.resolve()).as_posix()
            texts[rel] = p.read_text(encoding="utf-8")
        # Constitution first: its (possibly newly assigned) GLOBAL rules are
        # the governed_by source for requirements in every other file.
        global_consts: list[str] = []
        pre_transformed: dict[str, str] = {}
        existing_ids: list[str] = []
        for rel, text in texts.items():
            for sec in parse_text(text, rel).sections:
                existing_ids.append(sec.node_id)
        for rel in sorted(texts):
            if Path(rel).name != "constitution.md":
                continue
            new_text, _ = transform_text(texts[rel], rel, existing_ids, [])
            pre_transformed[rel] = new_text
            for sec in parse_text(new_text, rel).sections:
                if sec.kind == "constitution" and \
                        str(sec.meta.get("applicability", "GLOBAL")).upper() == "GLOBAL":
                    global_consts.append(sec.node_id)
        global_consts = sorted(set(global_consts))

        inventory, findings, transforms = [], [], {}
        for p in files:
            rel = p.resolve().relative_to(self.project.resolve()).as_posix()
            text = texts[rel]
            doc = parse_text(text, rel)
            if rel in pre_transformed:
                new_text, file_findings = pre_transformed[rel], []
                # Recompute findings for the constitution from its transform.
                _, file_findings = transform_text(text, rel, list(existing_ids), global_consts)
                new_text = pre_transformed[rel]
            else:
                new_text, file_findings = transform_text(text, rel, existing_ids, global_consts)
            existing_ids.extend(ID_TOKEN_RE.findall(new_text))
            inventory.append({"path": rel, "sections": [s.node_id for s in doc.sections],
                              "would_change": new_text != text})
            findings.extend(file_findings)
            if new_text != text:
                transforms[rel] = new_text
        # Independent coverage proof: count checkbox occurrences in the
        # ORIGINAL texts (regex, parser-independent) vs canonical tasks in
        # the transformed graph. Any loss/duplication blocks migration.
        import tempfile
        from .readiness import validate_readiness
        staged_texts = {rel: transforms.get(rel, texts[rel]) for rel in texts}
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for rel, txt in staged_texts.items():
                dest = root / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(txt, encoding="utf-8")
            staged = Graph.build(root)
        for diag in validate_readiness(staged):
            findings.append({"id": diag.node_id, "path": diag.path,
                             "finding": f"pending task is not implementation-ready "
                                        f"({diag.code}): {diag.message}"})
        for err in staged.resolution_errors:
            findings.append({"id": err["source"], "path": err["path"],
                             "finding": f"unresolved/ambiguous reference {err['raw']!r}: {err['error']}"})
        for sec in staged.duplicates:
            findings.append({"id": sec.node_id, "path": sec.path,
                             "finding": "duplicate canonical/local identity within the same feature; "
                                        "resolve the conflicting legacy alias before migration"})
        # Enrich inventory per file and build the persistent mapping.
        entities: list[dict] = []
        features: dict[str, str] = {}
        total_occ = 0
        for entry in inventory:
            rel = entry["path"]
            orig = parse_text(texts[rel], rel)
            staged_doc = parse_text(staged_texts[rel], rel)
            tasks_o = [s for s in orig.sections + orig.duplicates if s.kind == "task"]
            feat = feature_from_path(rel)
            if feat:
                features[feat] = feat
            entry.update({
                "feature": feat,
                "task_count": orig.task_occurrences,
                "completed_count": sum(1 for s in tasks_o if s.status == "done"),
                "pending_count": sum(1 for s in tasks_o if s.status != "done"),
                "original_task_identifiers": [s.legacy_alias or s.local_id for s in tasks_o],
                "missing_identifiers": sum(1 for s in tasks_o if s.id_missing),
                "duplicate_local_identifiers": sorted(
                    {s.local_id for s in tasks_o if [x.local_id for x in tasks_o].count(s.local_id) > 1}),
                "canonical_tasks": [s.node_id for s in staged_doc.sections if s.kind == "task"],
            })
            total_occ += orig.task_occurrences
        for sec in sorted(staged.nodes.values(), key=lambda s: s.node_id):
            entities.append({"canonical_id": sec.node_id, "local_id": sec.local_id,
                             "legacy_alias": sec.legacy_alias, "feature": sec.feature_id,
                             "kind": sec.kind, "source_path": sec.path,
                             "source_lines": [sec.start_line, sec.end_line],
                             "status": sec.status})
            if sec.feature_id:
                features.setdefault(sec.feature_id, sec.feature_id)
        canonical_tasks = [e for e in entities if e["kind"] == "task"]
        if len(canonical_tasks) != total_occ:
            findings.append({"id": "", "path": "",
                             "finding": f"task inventory coverage mismatch: {total_occ} original "
                                        f"task occurrences vs {len(canonical_tasks)} canonical tasks; "
                                        f"migration must not lose or merge tasks"})
        identity_mapping = {"version": IDENTITY_VERSION, "schema_version": "2.0",
                            "features": dict(sorted(features.items())),
                            "entities": entities}
        return {"inventory": inventory, "findings": findings, "transforms": transforms,
                "identity_mapping": identity_mapping,
                "task_occurrences": total_occ,
                "canonical_task_count": len(canonical_tasks),
                "already_migrated": not transforms and not findings}

    # ---- staged apply -----------------------------------------------------
    def apply(self, fail_after: int | None = None,
              crash_after: int | None = None) -> dict:
        block = migration_block(self.project)
        if block:
            return {"status": "recovery-required", "detail": block["detail"],
                    "incomplete": block["incomplete"],
                    "recovery_command": block["recovery_command"]}
        plan = self.plan()
        if plan["already_migrated"]:
            graph = Graph.build(self.project)
            if is_valid(validate_all(graph)):
                return {"status": "noop", "detail": "already migrated and valid; nothing to do"}
            return {"status": "refused",
                    "detail": "project carries traceability metadata but the graph "
                              "is not implementation-ready; fix findings first",
                    "findings": plan["findings"]}
        if plan["findings"]:
            return {"status": "refused",
                    "detail": "migration findings require human resolution; activation blocked",
                    "findings": plan["findings"]}
        txn_id = _now()
        root = self.project / STATE_DIR / txn_id
        if root.exists():  # same-second rerun: keep transaction ids unique
            suffix = 1
            while (self.project / STATE_DIR / f"{txn_id}-{suffix}").exists():
                suffix += 1
            txn_id = f"{txn_id}-{suffix}"
            root = self.project / STATE_DIR / txn_id
        (root / "backup").mkdir(parents=True, exist_ok=True)
        (root / "staged").mkdir(parents=True, exist_ok=True)
        _files = sorted(plan["transforms"])
        if IDENTITY_PATH not in _files:
            _files = sorted(_files + [IDENTITY_PATH])
        journal: dict = {"schema_version": JOURNAL_SCHEMA, "txn": txn_id,
                         "state": "prepared", "files": _files,
                         "identity_mapping": plan.get("identity_mapping"),
                         "file_records": [], "completed": [], "created": _now()}
        self._write_journal(root, journal)
        # Stage complete transformed artifacts; persist recovery evidence
        # (byte-exact backups + hashes) before any destructive operation.
        records: list[dict] = []
        for p in discover_files(self.project):
            rel = p.resolve().relative_to(self.project.resolve()).as_posix()
            staged = root / "staged" / rel
            staged.parent.mkdir(parents=True, exist_ok=True)
            staged.write_text(plan["transforms"].get(rel, p.read_text(encoding="utf-8")),
                              encoding="utf-8")
            _fsync_file(staged)
            backup = root / "backup" / rel
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(p, backup)
            _fsync_file(backup)
            if rel in plan["transforms"]:
                records.append({"path": rel, "backup_sha256": _sha(backup),
                                "staged_sha256": _sha(staged)})
        # Identity sidecar participates in staging/backup/activation/rollback.
        _id_staged = root / "staged" / IDENTITY_PATH
        _id_staged.parent.mkdir(parents=True, exist_ok=True)
        _id_staged.write_text(json.dumps(plan.get("identity_mapping") or {},
                                         indent=2, sort_keys=True) + "\n", encoding="utf-8")
        _fsync_file(_id_staged)
        _id_dest = self.project / IDENTITY_PATH
        if _id_dest.is_file():
            _id_backup = root / "backup" / IDENTITY_PATH
            _id_backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(_id_dest, _id_backup)
            _fsync_file(_id_backup)
            records.append({"path": IDENTITY_PATH, "backup_sha256": _sha(_id_backup),
                            "staged_sha256": _sha(_id_staged)})
        else:
            records.append({"path": IDENTITY_PATH, "backup_sha256": "",
                            "staged_sha256": _sha(_id_staged), "created": True})
        journal["file_records"] = sorted(records, key=lambda r: r["path"])
        journal["state"] = "staged"
        self._write_journal(root, journal)
        staged_graph = Graph.build(root / "staged")
        _staged_tasks = sum(1 for s in staged_graph.nodes.values() if s.kind == "task")
        if _staged_tasks != plan.get("task_occurrences", _staged_tasks):
            journal["state"] = "failed"
            journal["detail"] = (f"staged task count {_staged_tasks} does not match original "
                                   f"inventory {plan.get('task_occurrences')}; activation refused")
            self._write_journal(root, journal)
            return {"status": "refused", "txn": txn_id, "detail": journal["detail"]}
        diags = validate_all(staged_graph)
        if not is_valid(diags):
            journal["state"] = "failed"
            journal["detail"] = ("staged project failed the activation gate "
                                 "(graph + pending-task readiness); activation refused")
            self._write_journal(root, journal)
            return {"status": "refused", "txn": txn_id,
                    "detail": journal["detail"],
                    "diagnostics": [str(x) for x in diags if x.severity == "error"]}
        # Activation: journal state first, then one fsynced journal advance
        # per replacement. A crash between a replacement and its journal
        # update is reconciled by recover() from the hashed manifest.
        journal["state"] = "activating"
        self._write_journal(root, journal)
        try:
            for i, rel in enumerate(journal["files"]):
                if fail_after is not None and i >= fail_after:
                    raise OSError("injected failure during activation")
                dest = self.project / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                tmp = dest.with_name(dest.name + ".speckitext-tmp")
                shutil.copyfile(root / "staged" / rel, tmp)
                _fsync_file(tmp)
                os.replace(tmp, dest)
                _fsync_dir(dest.parent)
                if crash_after is not None and i + 1 >= crash_after:
                    raise MigrationCrash(
                        "simulated process interruption during activation")
                journal["completed"].append(rel)
                self._write_journal(root, journal)
        except OSError as exc:
            try:
                self._restore(root, journal)
                unrestored = [r["path"] for r in journal["file_records"]
                              if not _matches_original(self.project, r)]
            except OSError:
                unrestored = list(journal["files"])
            if unrestored:
                journal["state"] = "recovery-required"
                journal["detail"] = (f"activation failed ({exc}) and originals "
                                     f"could not be fully restored for: {unrestored}")
                self._write_journal(root, journal)
                return {"status": "recovery-required", "txn": txn_id,
                        "detail": journal["detail"]}
            journal["state"] = "failed"
            journal["detail"] = f"activation failed, restored: {exc}"
            self._write_journal(root, journal)
            return {"status": "failed-restored", "txn": txn_id, "detail": journal["detail"]}
        journal["state"] = "activated"
        self._write_journal(root, journal)
        return {"status": "activated", "txn": txn_id, "files": journal["files"]}

    # ---- recovery ---------------------------------------------------------
    def recover(self) -> dict:
        """Restore every non-terminal transaction to its byte-exact originals.

        Idempotent: terminal transactions are left alone, and running
        recovery when nothing is incomplete is a no-op. Works from a fresh
        process; reconciles replacements whose journal update never landed
        by trusting file hashes, not the completed list. The whole
        transaction is preflighted before any destination is touched:
        every destination must currently match its original or its staged
        hash, otherwise recovery reports a conflict and preserves all
        files (including post-interruption user edits) untouched.
        """
        base = self.project / STATE_DIR
        if not base.is_dir():
            return {"status": "nothing-to-recover",
                    "detail": "no migration transactions found"}
        recovered, blocked, conflicts, plans = [], [], [], []
        for root in sorted(p for p in base.glob("*") if p.is_dir()):
            journal_path = root / "journal.json"
            try:
                journal = json.loads(journal_path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                blocked.append({"txn": root.name,
                                "reason": f"journal unreadable ({exc}); restore "
                                          "project files from backup/ manually, "
                                          "then remove the transaction directory"})
                continue
            if journal.get("state") in TERMINAL_STATES:
                continue
            problem = self._verify_backups(root, journal, check_staged=True)
            if problem:
                journal["state"] = "recovery-required"
                journal["detail"] = problem
                self._write_journal(root, journal)
                blocked.append({"txn": journal.get("txn", root.name), "reason": problem})
                continue
            found = self._destination_conflicts(journal)
            if found:
                conflicts.extend(found)
                blocked.append({"txn": journal.get("txn", root.name),
                                "reason": "recovery conflict: destination content "
                                          "matches neither the original nor the "
                                          "staged transaction state",
                                "conflicts": found})
                continue
            plans.append((root, journal))
        if conflicts:
            return {"status": "recovery-conflict", "recovered": [],
                    "blocked": blocked, "conflicts": conflicts,
                    "detail": "recovery refused: files changed after the "
                              "interrupted migration do not match the "
                              "transaction; no files were modified. Preserve "
                              "the edits, or restore each conflicted file to "
                              "its original/staged content (or from the "
                              "transaction backup/), then re-run "
                              "`speckitext migrate --project . --recover`",
                    "recovery_command": "speckitext migrate --project . --recover"}
        if blocked:
            return {"status": "recovery-required", "recovered": [],
                    "blocked": blocked,
                    "detail": "some transactions cannot be recovered automatically; "
                              "no partially migrated state may be used"}
        for root, journal in plans:
            was_rollback = journal.get("state") == "rolling-back"
            try:
                self._restore(root, journal, progress_key="recovery_completed")
            except OSError as exc:
                journal["state"] = "recovery-required"
                journal["detail"] = f"recovery interrupted during restoration: {exc}"
                self._write_journal(root, journal)
                blocked.append({"txn": journal.get("txn", root.name),
                                "reason": journal["detail"]})
                continue
            bad = [r["path"] for r in journal.get("file_records", [])
                   if not _matches_original(self.project, r)]
            if bad:
                journal["state"] = "recovery-required"
                journal["detail"] = f"restoration did not reproduce originals for: {bad}"
                self._write_journal(root, journal)
                blocked.append({"txn": journal.get("txn", root.name),
                                "reason": journal["detail"]})
                continue
            journal["state"] = "rolled-back" if was_rollback else "recovered"
            journal["detail"] = ("interrupted rollback completed by recovery: "
                                 "restored byte-exact originals" if was_rollback else
                                 "interrupted migration restored to byte-exact originals")
            self._write_journal(root, journal)
            recovered.append(journal.get("txn", root.name))
        if blocked:
            return {"status": "recovery-required", "recovered": recovered,
                    "blocked": blocked,
                    "detail": "some transactions cannot be recovered automatically; "
                              "no partially migrated state may be used"}
        if recovered:
            return {"status": "recovered", "recovered": recovered,
                    "detail": "all incomplete migrations restored to originals"}
        return {"status": "nothing-to-recover",
                "detail": "no incomplete migration transactions"}

    def _manifest_problem(self, journal: dict) -> str | None:
        """Journal schema/manifest inconsistency, or None if verifiable."""
        if journal.get("schema_version") != JOURNAL_SCHEMA:
            return (f"journal schema_version {journal.get('schema_version')!r} is "
                    f"not supported (expected {JOURNAL_SCHEMA}); recovery evidence "
                    "cannot be verified safely")
        files, records = journal.get("files"), journal.get("file_records")
        if not isinstance(files, list) or not isinstance(records, list) \
                or not all(isinstance(f, str) for f in files) \
                or not all(isinstance(r, dict) for r in records):
            return "journal file manifest is missing or malformed; cannot verify safely"
        if len(set(files)) != len(files) or \
                sorted(r.get("path", "") for r in records if isinstance(r, dict)) != sorted(files) \
                or len(records) != len(files):
            return ("journal file manifest does not match its hashed file records; "
                    "cannot verify safely")
        for record in records:
            if not isinstance(record, dict) or (not record.get("created") and not record.get("backup_sha256")) \
                    or not record.get("staged_sha256"):
                return (f"journal record for {record.get('path') if isinstance(record, dict) else '?'} "
                        "lacks recorded hashes; cannot verify safely")
        return None

    def _verify_backups(self, root: Path, journal: dict,
                        check_staged: bool = False) -> str | None:
        problem = self._manifest_problem(journal)
        if problem:
            return problem
        for record in journal.get("file_records", []):
            backup = root / "backup" / record["path"]
            if record.get("created"):
                pass  # newly created file: original state is absence
            elif not backup.is_file():
                return f"backup missing for {record['path']}; cannot recover safely"
            elif _sha(backup) != record.get("backup_sha256"):
                return (f"backup for {record['path']} does not match its journal "
                        "hash; cannot recover safely")
            if check_staged:
                staged = root / "staged" / record["path"]
                if not staged.is_file():
                    return f"staged copy missing for {record['path']}; cannot recover safely"
                if _sha(staged) != record.get("staged_sha256"):
                    return (f"staged copy for {record['path']} does not match its "
                            "journal hash; cannot recover safely")
        return None

    def _destination_conflicts(self, journal: dict,
                               staged_only: bool = False) -> list[dict]:
        """Destinations matching no expected transaction state.

        Expected states are the original (backup) hash and, unless
        staged_only is set (a fresh rollback expects the activated --
        staged -- content), the staged hash. A file already restored
        during an interrupted rollback therefore still preflights.
        """
        conflicts = []
        for record in journal.get("file_records", []):
            dest = self.project / record["path"]
            observed = _sha(dest) if dest.is_file() else None
            expected = [{"state": "staged", "sha256": record["staged_sha256"]}]
            if not staged_only:
                expected.append({"state": "original",
                                 "sha256": record["backup_sha256"]})
            if record.get("created") and observed is None:
                continue
            if observed not in [e["sha256"] for e in expected]:
                conflicts.append({
                    "path": record["path"], "observed_sha256": observed,
                    "expected": expected,
                    "reason": "destination is missing" if observed is None else
                              "destination content matches no expected "
                              "transaction state (post-interruption edit?)"})
        return conflicts

    # ---- rollback -----------------------------------------------------------
    def rollback(self, txn_id: str | None = None, force: bool = False) -> dict:
        """Preflight -> restore -> verify -> finalize rollback.

        Nothing is restored unless the journal schema/manifest verifies,
        every backup exists and matches its recorded original hash, and
        every destination is in its expected activated (staged) state --
        or, when resuming an interrupted rollback, its original state.
        `force` is the explicit, intentional resolution for destination
        conflicts only; it never bypasses backup integrity. Rolled-back
        is reported only after every destination verifies against its
        original hash; an interruption leaves the transaction in the
        non-terminal rolling-back state for recover()/rollback() resume.
        """
        base = self.project / STATE_DIR
        if txn_id is None:
            candidates = sorted(p for p in base.glob("*") if p.is_dir()) if base.is_dir() else []
            activated = []
            for p in candidates:
                try:
                    state = json.loads((p / "journal.json").read_text(
                        encoding="utf-8")).get("state")
                except (OSError, ValueError):
                    continue
                if state in ("activated", "rolling-back"):
                    activated.append(p)
            if not activated:
                return {"status": "nothing-to-rollback", "detail": "no activated transaction found"}
            root = activated[-1]
        else:
            root = base / txn_id
        try:
            journal = json.loads((root / "journal.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return {"status": "rollback-refused",
                    "detail": f"cannot read transaction journal: {exc}"}
        if journal.get("state") not in ("activated", "rolling-back"):
            return {"status": "nothing-to-rollback",
                    "detail": f"transaction {journal.get('txn', root.name)} is "
                              f"{journal.get('state')}, not activated"}
        # Preflight: missing/corrupt/inconsistent evidence refuses before
        # any destination is touched. Legacy journals without verifiable
        # hashes are refused, never treated as proof of safety.
        problem = self._verify_backups(root, journal)
        if problem:
            return {"status": "rollback-refused", "txn": journal.get("txn", root.name),
                    "detail": f"rollback refused before restoration: {problem}"}
        # Never silently overwrite work done after activation.
        resuming = journal["state"] == "rolling-back"
        conflicts = self._destination_conflicts(journal, staged_only=not resuming)
        for conflict in conflicts:
            conflict["reason"] = ("file changed after migration activation"
                                  if conflict["observed_sha256"] is not None
                                  else "destination is missing")
        if conflicts and not force:
            return {"status": "rollback-conflict", "txn": journal["txn"],
                    "conflicts": conflicts,
                    "detail": "files were edited after activation; rollback would "
                              "destroy those edits. Preserve or revert them "
                              "explicitly, or re-run rollback with the explicit "
                              "forced resolution."}
        journal["state"] = "rolling-back"
        if not resuming:
            journal["rollback_completed"] = []
        self._write_journal(root, journal)
        try:
            self._restore(root, journal, progress_key="rollback_completed")
        except OSError as exc:
            journal["state"] = "rolling-back"
            journal["detail"] = (f"rollback interrupted: {exc}; re-run rollback "
                                 "or `speckitext migrate --project . --recover`")
            self._write_journal(root, journal)
            return {"status": "recovery-required", "txn": journal["txn"],
                    "detail": journal["detail"],
                    "rollback_completed": list(journal.get("rollback_completed", []))}
        unrestored = [r["path"] for r in journal.get("file_records", [])
                      if not _matches_original(self.project, r)]
        if unrestored:
            journal["state"] = "rolling-back"
            journal["detail"] = (f"rollback did not reproduce originals for: "
                                 f"{unrestored}; re-run rollback or recover")
            self._write_journal(root, journal)
            return {"status": "recovery-required", "txn": journal["txn"],
                    "detail": journal["detail"], "unrestored": unrestored}
        journal["state"] = "rolled-back"
        journal["detail"] = "rollback verified: every file restored to its original hash"
        self._write_journal(root, journal)
        return {"status": "rolled-back", "txn": journal["txn"],
                "files": journal["files"], "forced": bool(force and conflicts)}

    # ---- helpers ----------------------------------------------------------
    def _restore(self, root: Path, journal: dict,
                 progress_key: str | None = None) -> None:
        """Restore every manifest file from its backup via safe replacement.

        Raises OSError (including FileNotFoundError for a missing backup)
        instead of silently skipping a file; callers preflight backups and
        verify destinations afterwards. With progress_key, each restored
        file is journaled before the next begins, so an interruption is
        resumable from the recorded progress.
        """
        _created = {r["path"] for r in journal.get("file_records", []) if r.get("created")}
        for rel in journal["files"]:
            backup = root / "backup" / rel
            dest = self.project / rel
            if rel in _created and not backup.is_file():
                if dest.is_file():
                    dest.unlink()
                if progress_key:
                    done = journal.setdefault(progress_key, [])
                    if rel not in done:
                        done.append(rel)
                    self._write_journal(root, journal)
                continue
            if not backup.is_file():
                raise FileNotFoundError(
                    f"backup missing for {rel}; cannot restore safely")
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_name(dest.name + ".speckitext-tmp")
            shutil.copyfile(backup, tmp)
            _fsync_file(tmp)
            os.replace(tmp, dest)
            _fsync_dir(dest.parent)
            if progress_key:
                done = journal.setdefault(progress_key, [])
                if rel not in done:
                    done.append(rel)
                self._write_journal(root, journal)

    @staticmethod
    def _write_journal(root: Path, journal: dict) -> None:
        journal["updated"] = _now()
        tmp = root / "journal.json.tmp"
        tmp.write_text(json.dumps(journal, indent=2, sort_keys=True), encoding="utf-8")
        _fsync_file(tmp)
        os.replace(tmp, root / "journal.json")
        _fsync_dir(root)


def transform_text(text: str, rel: str, existing_ids: list[str],
                   global_consts: list[str] | None = None) -> tuple[str, list[dict]]:
    """Add missing speckitext metadata using evidence in the text only.

    Deterministic evidence rules (never invented history):
      * a heading/bullet/task ID gains an id/kind metadata block;
      * ID-less headings in constitution/plan/data-model/research/contract
        files gain deterministic IDs by file role and document order;
      * a requirement gains governed_by from the project's GLOBAL
        constitution rules (a constitution governs requirements by
        definition);
      * a task gains satisfies from requirement IDs named in its own text
        and verified_by from verification IDs named in its own text.
    A task with no such evidence yields a finding, not an invented link.
    """
    findings: list[dict] = []
    global_consts = global_consts or []
    lines = text.replace("\r\n", "\n").split("\n")
    out: list[str] = []
    base = Path(rel).name
    role = _HEADING_ID_ROLES.get(base)
    if role is None and "/contracts/" in f"/{rel}":
        role = ("CTR", "contract")

    def has_meta_after(idx: int) -> bool:
        return idx + 1 < len(lines) and "<!-- speckitext" in lines[idx + 1]

    def block_end(idx: int) -> int:
        end = len(lines)
        for k in range(idx + 1, len(lines)):
            if re.match(r"^#{1,6}\s", lines[k]) or re.match(r"^\s*-\s*\[[ xX]\]\s", lines[k]):
                end = k
                break
        return end

    _feat = feature_from_path(rel)
    _taken: set[str] = set()

    def _meta_lines(local: str, kind: str, extra: list[str] | None = None,
                    legacy: str | None = None, missing: bool = False) -> list[str]:
        canon = make_canonical(_feat, local, kind)
        meta = ["<!-- speckitext", f"id: {local}", f"kind: {kind}"]
        if canon != local:
            meta.append(f"canonical_id: {canon}")
        meta.append(f"local_id: {local}")
        meta.append(f"legacy_alias: {legacy if legacy is not None else local}")
        if _feat and kind != "constitution":
            meta.append(f"feature: {_feat}")
        if missing:
            meta.append("id_missing: true")
        meta += (extra or [])
        meta.append("-->")
        return meta

    i = 0
    while i < len(lines):
        line = lines[i]
        out.append(line)
        heading = re.match(r"^(#{1,6})\s+(.*)$", line)
        if heading and not has_meta_after(i):
            toks = ID_TOKEN_RE.findall(heading.group(2))
            if toks and kind_for_id(toks[0]):
                kind = kind_for_id(toks[0])
                local = split_canonical(toks[0])[1]
                extra = ["applicability: GLOBAL"] if kind == "constitution" else []
                out += _meta_lines(local, kind, extra)
            elif role is not None and len(heading.group(1)) >= 2:
                prefix, kind = role
                nid = _alloc_id(existing_ids, prefix)
                extra = []
                if kind == "constitution":
                    extra.append("applicability: GLOBAL")
                elif global_consts:
                    extra.append(f"governed_by: {', '.join(global_consts)}")
                out += _meta_lines(nid, kind, extra)
        bullet = re.match(r"^\s*-\s*\*\*((?:FR|SC)-\d{3,})\*\*", line)
        if bullet and not has_meta_after(i):
            extra = [f"governed_by: {', '.join(global_consts)}"] if global_consts else []
            out += _meta_lines(bullet.group(1), kind_for_id(bullet.group(1)) or "requirement", extra)
        task = re.match(r"^\s*-\s*\[[ xX]\]\s+(.*)$", line)
        if task and not has_meta_after(i):
            local, missing = extract_task_local(task.group(1), {})
            if missing:
                local = generated_local_id(task.group(1), _taken)
            _taken.add(local)
            block = "\n".join(lines[i:block_end(i)])
            sat = sorted({t for t in ID_TOKEN_RE.findall(block)
                          if kind_for_id(t) in ("requirement", "success_criterion")})
            ver = sorted({t for t in ID_TOKEN_RE.findall(block)
                          if kind_for_id(t) == "verification"})
            if sat:
                extra = [f"satisfies: {', '.join(sat)}"]
                if ver:
                    extra.append(f"verified_by: {', '.join(ver)}")
                out += _meta_lines(local, "task", extra,
                                   legacy="" if missing else local, missing=missing)
        i += 1
    new_text = "\n".join(out)
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
