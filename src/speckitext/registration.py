"""Effective implementation-command registration detection.

Inspects what an agent will actually load in a project — the registered
skill/command files on disk — not the preset source. Classification:

  speckitext  body invokes `speckitext compile` and forbids broad loading
  upstream    body contains upstream's broad-loading outline markers
  unknown     file exists but matches neither signature
  missing     no speckit-implement registration found for that integration

Project-local skills shadow user-level skills of the same name in every
supported agent; a project-local upstream speckit-implement therefore shadows
SpeckitExt's global skill, which this module reports as a conflict, never as
silent success.
"""
from __future__ import annotations

from pathlib import Path

# integration key -> candidate project directories (skills mode, then commands mode)
INTEGRATION_DIRS: dict[str, tuple[str, ...]] = {
    "claude": (".claude/skills", ".claude/commands"),
    "codex": (".agents/skills", ".agents/commands"),
    "kimi": (".kimi-code/skills", ".kimi-code/commands"),
    "muse": (".agents/skills", ".agents/commands"),
}

UPSTREAM_MARKERS = (
    "Load and analyze the implementation context",
    "Read tasks.md for the complete task list",
    "Read plan.md for tech stack",
    "Read /memory/constitution.md for governance",
    "check-prerequisites",
)
SPECKITEXT_MARKERS = ("speckitext compile",)


def classify_implement_body(text: str) -> str:
    if any(m in text for m in SPECKITEXT_MARKERS):
        return "speckitext"
    if any(m in text for m in UPSTREAM_MARKERS):
        return "upstream"
    return "unknown"


def _implement_files(project: Path, rel_dir: str) -> list[Path]:
    base = project / rel_dir
    if not base.is_dir():
        return []
    found: list[Path] = []
    for cand in (base / "speckit-implement" / "SKILL.md",
                 base / "speckit.implement.md",
                 base / "speckit-implement.md"):
        if cand.is_file():
            found.append(cand)
    return found


def registration_status(project: Path) -> dict:
    """Per-integration effective speckit-implement status for a project."""
    project = Path(project)
    result: dict[str, dict] = {}
    override_dirs = project / ".specify" / "templates" / "overrides"
    override_shadow = override_dirs.is_dir() and any(override_dirs.iterdir())
    for key, dirs in INTEGRATION_DIRS.items():
        entries: list[dict] = []
        for rel in dirs:
            for f in _implement_files(project, rel):
                body = f.read_text(encoding="utf-8", errors="replace")
                entries.append({"path": f.relative_to(project).as_posix(),
                                "classification": classify_implement_body(body)})
        classifications = {e["classification"] for e in entries}
        if not entries:
            state, active = "missing", False
        elif "speckitext" in classifications and "upstream" in classifications:
            state, active = "conflict", False
        elif classifications == {"speckitext"}:
            state, active = "speckitext", True
        elif classifications == {"upstream"}:
            state, active = "upstream", False
        else:
            state, active = "unknown", False
        result[key] = {"state": state, "override_active": active, "files": entries,
                       "diagnostic": _diagnostic(key, state)}
    return {"integrations": result,
            "template_overrides_present": override_shadow,
            "all_active": all(v["override_active"] for v in result.values()
                              if v["state"] != "missing") and
                          any(v["override_active"] for v in result.values())}


def _diagnostic(key: str, state: str) -> str:
    return {
        "speckitext": f"{key}: SpeckitExt scoped implement is the effective command",
        "upstream": f"{key}: effective speckit-implement is the UPSTREAM broad-loading "
                    "version; SpeckitExt override is not active (project-local skill "
                    "shadowing or preset not registered for this integration). Run "
                    "`speckitext bootstrap` on a new project or re-register the preset "
                    "for this integration; do not silently use the upstream workflow",
        "missing": f"{key}: no speckit-implement registration found for this integration",
        "unknown": f"{key}: speckit-implement found but matches neither SpeckitExt nor "
                   "upstream signatures; inspect it manually before implementing",
        "conflict": f"{key}: both SpeckitExt and upstream speckit-implement registrations "
                    "exist; resolve the conflict before implementing",
    }[state]
