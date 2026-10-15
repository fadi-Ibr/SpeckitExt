"""User-level (global) SpeckitExt deployment.

One canonical runtime (the installed `speckitext` Python package) plus
lightweight SKILL.md adapters in each agent's verified user skill directory.
No compiler copies. The installer owns exactly the files listed in its
manifest (~/.speckitext/install.json, or $SPECKITEXT_HOME) with content
hashes; unrelated and user-modified files are never touched.

Verified user skill directories on this machine:
  claude  ~/.claude/skills/
  codex   ~/.agents/skills/   (Codex lists skills from here; ~/.codex/skills is
                              its legacy home and is not written)
  kimi    ~/.kimi-code/skills/
  muse    ~/.agents/skills/   (verified via `muse skills list --source user`,
                              which reports paths under $HOME/.agents/skills)

Codex and Muse therefore share one installed adapter file.
A user-level skill never overrides a project-local skill of the same name;
project precedence is handled by registration detection + bootstrap, not by
this installer.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .fingerprint import fingerprint_bytes

SKILL_NAME = "speckitext"

AGENT_SKILL_DIRS: dict[str, str] = {
    "claude": ".claude/skills",
    "codex": ".agents/skills",
    "kimi": ".kimi-code/skills",
    "muse": ".agents/skills",
}

SKILL_BODY = """\
---
name: speckitext
description: SpeckitExt traceability-aware Spec Kit workflow. Use when implementing a task or batch by ID (e.g. "Implement T042 using SpeckitExt"), validating Spec Kit planning artifacts, compiling scoped implementation context, suggesting task batches, analyzing change impact, or migrating a legacy Spec Kit project. Delegates to the installed `speckitext` CLI; never load whole constitution/spec/plan/tasks documents for implementation.
---

# SpeckitExt

SpeckitExt moves relationship discovery into planning: Spec Kit artifacts carry
stable IDs and typed relationships, and a deterministic compiler builds the
exact context a task needs. You receive one focused package, not the project's
planning corpus.

## Implementing a task or batch by ID

Given "Implement T042 using SpeckitExt" (or "Implement the next ready
SpeckitExt batch"):

1. Run `speckitext doctor --project . --json` and confirm your agent's
   `override_active` is true. If not, report the diagnostic; never fall back
   to loading whole planning documents.
2. Run `speckitext validate --project .`. On failure, report diagnostics and
   stop; do not work around the gate.
3. Compile: `speckitext compile --project . --tasks T042 --output .specify/context/T042.md`
   (for a batch, use its task IDs; for "next ready batch", first run
   `speckitext batch suggest --project .` and confirm the suggested batch).
4. Load ONLY the compiled package. Inspect the real code it points at. If a
   genuinely needed planning section is missing, run
   `speckitext expand --project . --package <pkg> --ids <ID> --reason "<why>"`
   instead of opening a whole planning document.
5. Implement in the package's dependency order, run the focused VER-xxx checks
   it names plus one consolidated batch verification, then flip only the
   implemented tasks' checkboxes in tasks.md and re-run validation.
6. Report implemented IDs, changed files, checks and results, expansions, and
   blocked prerequisites. Project rules (verification, Git delivery) live in
   the project's AGENTS.md, not in tasks — follow them from there.

## Other workflows

- New project: `speckitext bootstrap --project <path>` installs the native
  Spec Kit preset+extension and registers the scoped implement command for all
  requested integrations. Never bootstrap an established project; existing
  projects require `speckitext migrate --dry-run` review first (full,
  all-or-nothing migration).
- Diagnosis: `speckitext doctor --json`, `speckitext doctor --global`.
"""


def state_home(home: Path | None = None) -> Path:
    """State directory. An explicit `home` is a *user home* (tests); the
    SPECKITEXT_HOME env var, when set, names the state directory directly."""
    import os
    if home is not None:
        return Path(home) / ".speckitext"
    env = os.environ.get("SPECKITEXT_HOME")
    return Path(env) if env else Path.home() / ".speckitext"


def _manifest_path(home: Path | None) -> Path:
    return state_home(home) / "install.json"


def _load_manifest(home: Path | None) -> dict:
    p = _manifest_path(home)
    if p.is_file():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            return {"files": [], "corrupt": True}
    return {"files": []}


def _save_manifest(home: Path | None, manifest: dict) -> None:
    p = _manifest_path(home)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")


def target_files(home: Path | None = None) -> list[dict]:
    """One entry per physical file; shared dirs (codex+muse) appear once."""
    base = Path.home() if home is None else Path(home)
    # state_home may redirect state, but skill dirs always anchor at the user home
    # unless an explicit home override is given (used by tests).
    seen: dict[str, dict] = {}
    for agent, rel in AGENT_SKILL_DIRS.items():
        dest = base / rel / SKILL_NAME / "SKILL.md"
        key = str(dest)
        if key not in seen:
            seen[key] = {"path": str(dest), "agents": []}
        seen[key]["agents"].append(agent)
    return sorted(seen.values(), key=lambda e: e["path"])


def install_global(home: Path | None = None, force: bool = False) -> dict:
    manifest = _load_manifest(home)
    owned = {e["path"]: e for e in manifest.get("files", [])}
    installed, conflicts, unchanged = [], [], []
    new_files: list[dict] = []
    content_hash = fingerprint_bytes(SKILL_BODY.encode("utf-8"))
    for entry in target_files(home):
        dest = Path(entry["path"])
        record = {"path": entry["path"], "agents": entry["agents"],
                  "sha256": content_hash, "version": __version__}
        if dest.is_file():
            current = fingerprint_bytes(dest.read_bytes())
            if current == content_hash:
                unchanged.append(entry["path"]); new_files.append(record); continue
            if entry["path"] not in owned and not force:
                conflicts.append({"path": entry["path"],
                                  "reason": "existing file not owned by SpeckitExt "
                                            "(possible user skill or name collision); "
                                            "not overwritten. Re-run with force=True only "
                                            "if it is safe to replace."})
                continue
            if entry["path"] in owned and owned[entry["path"]].get("sha256") != current and not force:
                conflicts.append({"path": entry["path"],
                                  "reason": "owned file was user-modified since install; "
                                            "not overwritten without force"})
                continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(SKILL_BODY.encode("utf-8"))  # byte-exact: hashes must match
        installed.append(entry["path"]); new_files.append(record)
    manifest = {"version": __version__,
                "installed_at": datetime.now(timezone.utc).isoformat(),
                "files": sorted(new_files + [e for e in manifest.get("files", [])
                                             if e["path"] not in {f["path"] for f in new_files}
                                             and e["path"] not in {c["path"] for c in conflicts}],
                                key=lambda e: e["path"])}
    _save_manifest(home, manifest)
    return {"status": "conflict" if conflicts else "installed",
            "installed": installed, "unchanged": unchanged, "conflicts": conflicts}


def uninstall_global(home: Path | None = None, force: bool = False) -> dict:
    manifest = _load_manifest(home)
    removed, kept, missing = [], [], []
    remaining: list[dict] = []
    for entry in manifest.get("files", []):
        dest = Path(entry["path"])
        if not dest.is_file():
            missing.append(entry["path"]); continue
        current = fingerprint_bytes(dest.read_bytes())
        if current != entry.get("sha256") and not force:
            kept.append({"path": entry["path"],
                         "reason": "user-modified since install; kept (use force to remove)"})
            remaining.append(entry); continue
        dest.unlink()
        try:
            dest.parent.rmdir()
        except OSError:
            pass
        removed.append(entry["path"])
    manifest["files"] = remaining
    _save_manifest(home, manifest)
    return {"status": "uninstalled" if not kept else "partial",
            "removed": removed, "kept": kept, "missing": missing}


def global_status(home: Path | None = None) -> dict:
    manifest = _load_manifest(home)
    owned = {e["path"]: e for e in manifest.get("files", [])}
    per_agent: dict[str, dict] = {}
    for entry in target_files(home):
        dest = Path(entry["path"])
        present = dest.is_file()
        matches = present and fingerprint_bytes(dest.read_bytes()) == entry.get("sha256", "") \
            if entry["path"] in owned else False
        status = {"skill_file": entry["path"], "installed": entry["path"] in owned and present,
                  "content_matches_manifest": bool(matches),
                  "shared_with": [a for a in entry["agents"]]}
        for agent in entry["agents"]:
            per_agent[agent] = dict(status)
    return {"manifest": str(_manifest_path(home)), "version": manifest.get("version"),
            "agents": per_agent}
