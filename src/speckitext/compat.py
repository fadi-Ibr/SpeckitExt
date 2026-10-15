"""Compatibility tracking and doctor reports.

Tested-compatibility is derived from actual integration tests in this repo,
never from a broad version-range declaration:

  TESTED_SPECIFY_VERSIONS  versions exercised by tests/test_e2e_specify.py and
                           the four-agent registration tests on this machine
  Below the preset/extension manifest floor (>=0.9.0) -> unsupported
  Newer than tested, at/above the floor            -> untested (distinct!)
  Unparseable / undetectable                       -> unknown

Diagnosis never upgrades or modifies the user's Spec Kit installation.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from . import COMPILER_VERSION, SCHEMA_VERSION, __version__

# Upstream source inspected for API compatibility (not an installed version).
UPSTREAM_REFERENCE = {
    "repository": "https://github.com/github/spec-kit",
    "commit": "3238fa9285694dc539aeb9829b337bfd6aed7317",
    "source_version": "1.2.1.dev0",
    "verified": "2026-10-15",
}
TESTED_SPECIFY_VERSIONS = ("1.0.10",)
MANIFEST_FLOOR = (0, 9, 0)  # requires.speckit_version in preset/extension manifests

AGENT_CLIS = {"claude": "claude", "codex": "codex", "kimi": "kimi", "muse": "muse"}


def _parse_version(text: str) -> tuple[int, ...] | None:
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", text or "")
    return tuple(int(x) for x in m.groups()) if m else None


def classify_specify_version(version: str | None) -> str:
    parsed = _parse_version(version or "")
    if parsed is None:
        return "unknown"
    if version and version.strip() in TESTED_SPECIFY_VERSIONS:
        return "tested-compatible"
    if parsed < MANIFEST_FLOOR:
        return "unsupported"
    return "untested"


def _run(args: list[str]) -> str:
    try:
        r = subprocess.run(args, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=30)
        return (r.stdout or "") + (r.stderr or "")
    except (OSError, subprocess.SubprocessError):
        return ""


def specify_info() -> dict:
    executables: list[str] = []
    seen: set[str] = set()
    for name in ("specify", "specify.exe"):
        for p in shutil.which(name, path=None) and [shutil.which(name)] or []:
            if p and p not in seen:
                seen.add(p); executables.append(p)
    # shutil.which finds only the first; also scan PATH entries for duplicates.
    import os
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        for name in ("specify.exe", "specify"):
            cand = Path(entry) / name
            if cand.is_file() and str(cand) not in seen:
                seen.add(str(cand)); executables.append(str(cand))
    active = executables[0] if executables else None
    version_out = _run([active, "--version"]).strip() if active else ""
    m = re.search(r"(\d+\.\d+\.\d+)", version_out)
    version = m.group(1) if m else None
    source = "unknown"
    if active and ".local" in active.replace("\\", "/"):
        tool_list = _run(["uv", "tool", "list"])
        if "specify-cli" in tool_list:
            source = "uv-tool (specify-cli)"
    return {"executables": executables, "active_executable": active,
            "version_output": version_out or None, "distribution_version": version,
            "installation_source": source,
            "classification": classify_specify_version(version),
            "tested_versions": list(TESTED_SPECIFY_VERSIONS),
            "upstream_reference": UPSTREAM_REFERENCE}


def agent_info() -> dict:
    out: dict[str, dict] = {}
    for key, exe in AGENT_CLIS.items():
        path = shutil.which(exe)
        version = _run([path, "--version"]).strip().splitlines()[0] if path else None
        out[key] = {"cli": path, "version": version if version else None,
                    "available": path is not None}
    return out


def speckitext_info() -> dict:
    return {"package_version": __version__, "schema_version": SCHEMA_VERSION,
            "compiler_version": COMPILER_VERSION}


def _manifest_version(path: Path) -> str | None:
    if not path.is_file():
        return None
    m = re.search(r'(?m)^\s*version:\s*"?([\d.]+)"?', path.read_text(encoding="utf-8", errors="replace"))
    return m.group(1) if m else None


def project_metadata(project: Path) -> dict:
    project = Path(project)
    meta_file = project / ".specify" / "speckitext.json"
    recorded = None
    if meta_file.is_file():
        import json
        try:
            recorded = json.loads(meta_file.read_text(encoding="utf-8"))
        except ValueError:
            recorded = {"error": "unparseable .specify/speckitext.json"}
    return {"recorded": recorded,
            "preset_version_installed": _manifest_version(
                project / ".specify" / "presets" / "traceability" / "preset.yml"),
            "extension_version_installed": _manifest_version(
                project / ".specify" / "extensions" / "traceability" / "extension.yml")}
