"""Single-command activation of SpeckitExt in a NEW Spec Kit project.

Uses only upstream-supported APIs, in the order verified against specify-cli
1.0.10:

  specify init <name> --integration <first> --non-interactive   (if needed)
  specify integration install <each other> [--force]            (multi-install)
  specify preset add --dev <preset>                             (registers into default)
  specify extension add --dev <extension>
  specify integration use <each other>                          (re-registers there)
  specify integration use <original default>                    (restore)
  verify effective speckit-implement per integration (registration.py)
  write .specify/speckitext.json compatibility metadata

Established projects are refused: a project with authored feature artifacts
or an existing SpeckitExt installation must go through review / full
migration, never silent bootstrap.
"""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .compat import speckitext_info, specify_info
from .registration import INTEGRATION_DIRS, registration_status

DEFAULT_INTEGRATIONS = ("claude", "codex", "kimi", "muse")


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=600)


def locate_assets(preset_dir: str | None = None, extension_dir: str | None = None,
                  start: Path | None = None) -> tuple[Path, Path]:
    """Find the preset/ and extension/ directories of a SpeckitExt checkout."""
    import os
    candidates: list[Path] = []
    if os.environ.get("SPECKITEXT_REPO"):
        candidates.append(Path(os.environ["SPECKITEXT_REPO"]))
    here = Path(__file__).resolve()
    candidates += [here.parents[2], Path.cwd(), *( (start or Path.cwd()).parents )]
    preset = Path(preset_dir) if preset_dir else None
    extension = Path(extension_dir) if extension_dir else None
    for cand in candidates:
        if preset is None and (cand / "preset" / "preset.yml").is_file():
            preset = cand / "preset"
        if extension is None and (cand / "extension" / "extension.yml").is_file():
            extension = cand / "extension"
    if preset is None or extension is None:
        raise FileNotFoundError(
            "could not locate SpeckitExt preset/extension directories; pass "
            "--preset-dir/--extension-dir or set SPECKITEXT_REPO to a SpeckitExt checkout")
    return preset, extension


def _is_established(project: Path) -> str | None:
    specs = project / "specs"
    if specs.is_dir() and any(specs.glob("*/spec.md")):
        return "project already has authored feature specs (established project)"
    if (project / ".specify" / "presets" / "traceability").is_dir():
        return "SpeckitExt preset already installed in this project"
    if (project / ".specify" / "speckitext.json").is_file():
        return "project already bootstrapped (speckitext.json present)"
    return None


def bootstrap_project(project: Path, integrations: tuple[str, ...] = DEFAULT_INTEGRATIONS,
                      preset_dir: str | None = None, extension_dir: str | None = None) -> dict:
    project = Path(project)
    unknown = [i for i in integrations if i not in INTEGRATION_DIRS]
    if unknown:
        raise ValueError(f"unknown integrations: {unknown}")
    steps: list[dict] = []
    fresh = not (project / ".specify").is_dir()
    if not fresh:
        reason = _is_established(project)
        if reason:
            return {"status": "refused", "detail": reason +
                    "; bootstrap is for NEW projects only. Existing projects require "
                    "review and full migration (speckitext migrate --dry-run) first."}
    preset, extension = locate_assets(preset_dir, extension_dir, project)
    preset, extension = preset.resolve(), extension.resolve()  # subprocess cwd is the project
    project.mkdir(parents=True, exist_ok=True)
    if fresh:
        r = _run(["specify", "init", ".", "--integration", integrations[0],
                  "--non-interactive", "--force"], project)
        steps.append({"step": "init", "ok": r.returncode == 0,
                      "detail": (r.stdout + r.stderr).strip().splitlines()[-1:]})
        if r.returncode != 0:
            return {"status": "failed", "steps": steps,
                    "detail": "specify init failed; project left as-is"}
    for key in integrations[1:]:
        r = _run(["specify", "integration", "install", key], project)
        if r.returncode != 0:
            r = _run(["specify", "integration", "install", key, "--force"], project)
        steps.append({"step": f"integration install {key}", "ok": r.returncode == 0})
    for label, args in (("preset add", ["specify", "preset", "add", "--dev", str(preset)]),
                        ("extension add", ["specify", "extension", "add", "--dev", str(extension)])):
        r = _run(args, project)
        steps.append({"step": label, "ok": r.returncode == 0,
                      "detail": (r.stdout + r.stderr).strip().splitlines()[-1:]})
        if r.returncode != 0:
            return {"status": "failed", "steps": steps, "detail": f"{label} failed"}
    for key in integrations[1:]:
        r = _run(["specify", "integration", "use", key], project)
        steps.append({"step": f"integration use {key} (re-register)", "ok": r.returncode == 0})
    r = _run(["specify", "integration", "use", integrations[0]], project)
    steps.append({"step": f"restore default {integrations[0]}", "ok": r.returncode == 0})
    registration = registration_status(project)
    requested = {k: v for k, v in registration["integrations"].items() if k in integrations}
    all_active = all(v["override_active"] for v in requested.values())
    metadata = {"speckitext": speckitext_info(), "specify": specify_info(),
                "integrations": list(integrations),
                "registration": requested,
                "bootstrapped_at": datetime.now(timezone.utc).isoformat(),
                "speckitext_package_version": __version__}
    (project / ".specify" / "speckitext.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8")
    return {"status": "bootstrapped" if all_active else "bootstrapped-with-warnings",
            "steps": steps, "registration": requested,
            "metadata_file": ".specify/speckitext.json",
            "detail": "effective scoped speckit-implement verified for all requested "
                      "integrations" if all_active else
                      "some integrations lack an active SpeckitExt override; see registration diagnostics"}
