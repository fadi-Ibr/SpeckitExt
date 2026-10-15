"""Project artifact discovery. Canonical sources stay where Spec Kit puts them."""
from __future__ import annotations

from pathlib import Path

ARTIFACT_PATTERNS = (
    ".specify/memory/constitution.md",
    "specs/*/spec.md",
    "specs/*/plan.md",
    "specs/*/tasks.md",
    "specs/*/data-model.md",
    "specs/*/research.md",
    "specs/*/quickstart.md",
    "specs/*/contracts/*.md",
    "specs/*/checklists/*.md",
)


def discover_files(project: Path) -> list[Path]:
    project = Path(project)
    found: dict[str, Path] = {}
    for pattern in ARTIFACT_PATTERNS:
        for p in sorted(project.glob(pattern)):
            if p.is_file():
                found[p.resolve().relative_to(project.resolve()).as_posix()] = p
    return [found[k] for k in sorted(found)]


def is_speckit_project(project: Path) -> bool:
    return (Path(project) / ".specify").is_dir() or bool(discover_files(project))
