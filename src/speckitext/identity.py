"""Canonical identity model (schema 2.0).

Local identifier: original ID inside its feature (``T001``, ``FR-001``,
``T070E``, ``G5-T1``). Legacy alias: the exact original string, preserved.
Feature identity: stable namespace derived from the ``specs/<dir>`` directory
(or an explicit ``feature:``/persisted identity mapping); constitution/global
entities use the empty (shared) feature.
Canonical identity: ``<feature>::<local>`` for feature-local entities,
plain ``<local>`` for global/shared entities (e.g. ``CON-001``).

Canonical IDs are deterministic and stable across completion, edits,
reordering and insertion: they depend only on (feature, local), never on
document order or content position. A persisted ``canonical_id`` in a
section's metadata (written by migration) wins over directory derivation,
so a directory rename that preserves that metadata preserves identity.
The persisted mapping lives in ``.speckitext/identity.json`` (versioned).
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

IDENTITY_VERSION = 1
IDENTITY_PATH = ".speckitext/identity.json"
SEPARATOR = "::"
GLOBAL_FEATURES = ("", "shared", "global")

_FEATURE_RE = re.compile(r"[^A-Za-z0-9._-]+")


def sanitize_feature(raw: str) -> str:
    f = _FEATURE_RE.sub("-", str(raw).strip()).strip("-")
    return f


def feature_from_path(rel_path: str) -> str:
    parts = rel_path.replace("\\", "/").split("/")
    if len(parts) >= 3 and parts[0] == "specs":
        return sanitize_feature(parts[1])
    return ""


def is_global_feature(feature: str) -> bool:
    return (feature or "") in GLOBAL_FEATURES


def make_canonical(feature: str, local: str, kind: str = "") -> str:
    local = str(local).strip()
    if not local:
        return ""
    if SEPARATOR in local:  # already canonical
        return local
    if kind == "constitution" or is_global_feature(feature or ""):
        return local
    return f"{sanitize_feature(feature)}{SEPARATOR}{local}"


def split_canonical(canonical: str) -> tuple[str, str]:
    if SEPARATOR in canonical:
        f, _, local = canonical.partition(SEPARATOR)
        return f, local
    return "", canonical


def is_canonical(ref: str) -> bool:
    return SEPARATOR in (ref or "")


def generated_local_id(text: str, taken: set[str] | None = None) -> str:
    """Deterministic ID for an ID-less task: hash of normalized task text.

    Stable across completion (checkbox ignored by caller), reordering and
    insertion of other tasks. Collisions get a deterministic -2/-3 suffix.
    """
    norm = re.sub(r"\s+", " ", (text or "").strip().lower())
    digest = hashlib.sha256(norm.encode("utf-8")).hexdigest()[:8]
    base = f"T-AUTO-{digest}"
    if taken is None or base not in taken:
        return base
    n = 2
    while f"{base}-{n}" in taken:
        n += 1
    return f"{base}-{n}"


def load_identity_map(project: Path) -> dict:
    p = Path(project) / IDENTITY_PATH
    if not p.is_file():
        return {"version": IDENTITY_VERSION, "features": {}, "entities": []}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"version": IDENTITY_VERSION, "features": {}, "entities": [],
                "corrupt": True}
    if not isinstance(data, dict):
        return {"version": IDENTITY_VERSION, "features": {}, "entities": [],
                "corrupt": True}
    data.setdefault("version", IDENTITY_VERSION)
    data.setdefault("features", {})
    data.setdefault("entities", [])
    return data


def feature_for_path(project: Path, rel_path: str, identity_map: dict | None = None) -> str:
    derived = feature_from_path(rel_path)
    if identity_map:
        mapped = (identity_map.get("features") or {}).get(derived)
        if mapped:
            return sanitize_feature(str(mapped))
    return derived


class AmbiguousReferenceError(ValueError):
    def __init__(self, ref: str, candidates: list[str]):
        self.ref, self.candidates = ref, sorted(candidates)
        super().__init__(
            f"ambiguous reference {ref!r}; candidates: {', '.join(self.candidates)}; "
            f"qualify as <feature>::<id> or select with --feature")


class UnknownReferenceError(ValueError):
    def __init__(self, ref: str):
        self.ref = ref
        super().__init__(f"unknown reference {ref!r}")


class IdentityResolver:
    """Single resolver used by graph, validation, compiler, batch, impact,
    governance and migration. No first-match global search."""

    def __init__(self, sections=()):
        self.by_canonical: dict[str, object] = {}
        self.by_feature_local: dict[tuple[str, str], list[str]] = {}
        self.by_local: dict[str, list[str]] = {}
        for sec in sections:
            self.add(sec)

    def add(self, sec) -> None:
        canon = sec.node_id
        self.by_canonical.setdefault(canon, sec)
        key = (sec.feature_id or "", sec.local_id or split_canonical(canon)[1])
        self.by_feature_local.setdefault(key, [])
        if canon not in self.by_feature_local[key]:
            self.by_feature_local[key].append(canon)
        lst = self.by_local.setdefault(key[1], [])
        if canon not in lst:
            lst.append(canon)

    def candidates_for_local(self, local: str) -> list[str]:
        if is_canonical(local):
            return [local] if local in self.by_canonical else []
        return sorted(self.by_local.get(local, []))

    def resolve(self, ref: str, source_feature: str = "",
                source_canonical: str = "") -> str:
        """Resolve `ref` to a canonical ID or raise Ambiguous/Unknown."""
        ref = str(ref).strip()
        if not ref:
            raise UnknownReferenceError(ref)
        if is_canonical(ref):
            if ref in self.by_canonical:
                return ref
            raise UnknownReferenceError(ref)
        # An exact global/shared entity wins only if no same-feature entity
        # shadows it (same-feature check below runs first for feature sources).
        if source_feature and not is_global_feature(source_feature):
            hits = self.by_feature_local.get((source_feature, ref), [])
            if len(hits) == 1:
                return hits[0]
            if len(hits) > 1:
                raise AmbiguousReferenceError(ref, hits)
        # Global/shared (empty feature) entity.
        ghits = self.by_feature_local.get(("", ref), []) + \
            self.by_feature_local.get(("shared", ref), [])
        ghits = sorted(set(ghits))
        if len(ghits) == 1 and not (source_feature and not is_global_feature(source_feature)):
            return ghits[0]
        if len(ghits) > 1:
            raise AmbiguousReferenceError(ref, ghits)
        if ghits and source_feature:
            return ghits[0]
        all_hits = self.candidates_for_local(ref)
        if len(all_hits) == 1:
            return all_hits[0]
        if len(all_hits) > 1:
            raise AmbiguousReferenceError(ref, all_hits)
        raise UnknownReferenceError(ref)

    def try_resolve(self, ref: str, source_feature: str = "") -> tuple[str | None, str]:
        try:
            return self.resolve(ref, source_feature), ""
        except AmbiguousReferenceError as exc:
            return None, str(exc)
        except UnknownReferenceError as exc:
            return None, str(exc)
