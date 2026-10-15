"""Effective implementation-command registration detection.

Inspects what an agent will actually load in a project -- the registered
skill/command files on disk -- not the preset source. A body is verified
SpeckitExt only when it carries the complete scoped-implementation
contract: it validates (`speckitext validate`), checks registration
(`speckitext doctor`), compiles scoped context (`speckitext compile`),
expands only through the compiler (`speckitext expand`), and forbids
broad whole-document loading. Merely mentioning `speckitext compile`
(for example in an example or quotation) classifies as `partial`, never
as verified. Any upstream broad-loading marker disqualifies a body.

Classifications: speckitext | upstream | partial | unknown | missing,
plus `conflict` when competing registrations coexist for one integration.
Project-local skills shadow user-level skills of the same name in every
supported agent; a project-local upstream speckit-implement therefore
shadows SpeckitExt's global skill, which this module reports as a
conflict, never as silent success.
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
# The complete contract a verified SpeckitExt implement body must carry.
REQUIRED_SPECKITEXT_MARKERS = (
    "speckitext doctor",
    "speckitext validate",
    "speckitext compile",
    "speckitext expand",
)
SCOPED_ONLY_MARKERS = (
    "Load ONLY the compiled context package",
    "Do NOT load the",
    "never load whole",
    "Never load whole",
)


def classify_implement_body(text: str) -> str:
    if any(m in text for m in UPSTREAM_MARKERS):
        return "upstream"
    has_required = all(m in text for m in REQUIRED_SPECKITEXT_MARKERS)
    has_scoped = any(m in text for m in SCOPED_ONLY_MARKERS)
    if has_required and has_scoped:
        return "speckitext"
    if "speckitext" in text:
        return "partial"
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
    # Only an override that actually targets the implement template can
    # shadow implementation; unrelated override files are not a conflict.
    override_shadow = override_dirs.is_dir() and any(
        "implement" in p.name.lower() for p in override_dirs.rglob("*") if p.is_file())
    for key, dirs in INTEGRATION_DIRS.items():
        entries: list[dict] = []
        for rel in dirs:
            for f in _implement_files(project, rel):
                body = f.read_text(encoding="utf-8", errors="replace")
                entries.append({"path": f.relative_to(project).as_posix(),
                                "location": "project-local",
                                "classification": classify_implement_body(body)})
        classifications = {e["classification"] for e in entries}
        if not entries:
            state, active = "missing", False
        elif "speckitext" in classifications and len(classifications) > 1:
            state, active = "conflict", False
        elif classifications == {"speckitext"}:
            state, active = "speckitext", True
        elif classifications == {"upstream"}:
            state, active = "upstream", False
        elif classifications == {"partial"}:
            state, active = "partial", False
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
        "partial": f"{key}: speckit-implement mentions SpeckitExt but does not carry the "
                   "complete scoped contract (doctor/validate/compile/expand plus "
                   "no-broad-loading); it is NOT a verified SpeckitExt registration",
        "conflict": f"{key}: competing speckit-implement registrations exist and at "
                    "most one is verified SpeckitExt; resolve the conflict before "
                    "implementing",
    }[state]
