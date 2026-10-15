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

from .schema import Diagnostic

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
    data.setdefault("reconciliations", [])
    if not isinstance(data.get("reconciliations"), list):
        return {"version": data.get("version", IDENTITY_VERSION), "features": {},
                "entities": [], "corrupt": True,
                "corrupt_reason": "identity map 'reconciliations' must be a list"}
    if not isinstance(data.get("features"), dict) or not isinstance(data.get("entities"), list):
        return {"version": data.get("version", IDENTITY_VERSION), "features": {},
                "entities": [], "corrupt": True,
                "corrupt_reason": "identity map 'features' must be an object and 'entities' a list"}
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


def identity_map_diagnostics(identity_map, sections=(), project=None) -> list:
    """Fail-closed integrity checks for the persisted identity map.

    No map (file absent) is valid for a fresh project. A present map must be
    well-typed, version-supported, internally consistent, and in agreement
    with authored canonical metadata for entities present in both. Source
    line/path differences alone are not inconsistencies (relocation). The
    map is also the continuity record: a persisted identity that is no
    longer authored needs an explicit ``reconciliations`` record
    (removed, or reassigned to a named replacement, with a reason) or it
    is reported as IDENTITY_DISAPPEARED. New authored identities are fine
    and are never guessed to be replacements. Validation is read-only:
    it never deletes or rewrites mappings."""
    diags: list = []
    def add(code, msg, nid=""):
        diags.append(Diagnostic(code, msg, nid, IDENTITY_PATH))
    if project is not None and not (Path(project) / IDENTITY_PATH).is_file():
        return []
    if identity_map is None:
        return []
    if not isinstance(identity_map, dict):
        add("IDENTITY_MAP_INVALID", "identity map must be a JSON object")
        return diags
    if identity_map.get("corrupt"):
        add("IDENTITY_MAP_CORRUPT",
            f"identity map is corrupt and cannot be trusted: {identity_map.get('corrupt_reason', 'invalid JSON or structure')}; "
            "original mapping preserved for inspection/recovery; fix or remove it explicitly, identities will not be silently rebuilt")
        return diags
    # A default empty map from a missing file is valid (checked via project above);
    # when called without project, an entirely empty map is treated as no map.
    if project is None and not identity_map.get("features") and not identity_map.get("entities") and "version" not in identity_map:
        return []
    version = identity_map.get("version")
    if version != IDENTITY_VERSION:
        add("IDENTITY_MAP_UNSUPPORTED_VERSION",
            f"unsupported identity map version {version!r} (expected {IDENTITY_VERSION}); refusing to trust persisted identities")
    features = identity_map.get("features")
    if not isinstance(features, dict):
        add("IDENTITY_MAP_INVALID", "identity map 'features' must be an object mapping directory feature to stable feature")
        features = {}
    entities = identity_map.get("entities")
    if not isinstance(entities, list):
        add("IDENTITY_MAP_INVALID", "identity map 'entities' must be a list")
        entities = []
    for k, v in list(features.items()):
        if not isinstance(k, str) or not isinstance(v, str) or not v or sanitize_feature(v) != v or sanitize_feature(k) != k:
            add("IDENTITY_MAP_INVALID", f"invalid feature mapping {k!r}: {v!r}; keys and values must be stable feature identifiers")
    seen_canon: dict = {}
    seen_fl: dict = {}
    seen_alias: dict = {}
    valid_entities = []
    for e in entities:
        if not isinstance(e, dict):
            add("IDENTITY_MAP_INVALID", "identity map entity records must be objects")
            continue
        canon, local, feat, kind, alias = e.get("canonical_id"), e.get("local_id"), e.get("feature"), e.get("kind"), e.get("legacy_alias", "")
        if not all(isinstance(x, str) for x in (canon, local, feat, kind)) or not isinstance(alias, str) or not canon or not local or not kind:
            add("IDENTITY_MAP_INVALID", f"identity map entity has missing or non-string canonical_id/local_id/feature/kind: {e!r}")
            continue
        valid_entities.append(e)
        if canon in seen_canon:
            add("IDENTITY_MAP_DUPLICATE", f"duplicate canonical identity {canon!r} in identity map", canon)
        seen_canon[canon] = e
        cf, cl = split_canonical(canon)
        if cl != local:
            add("IDENTITY_MAP_INCONSISTENT", f"canonical identity {canon!r} local part {cl!r} does not match local_id {local!r}", canon)
        if kind == "constitution" or is_global_feature(feat):
            if cf and not is_global_feature(cf):
                add("IDENTITY_MAP_INCONSISTENT", f"global entity {canon!r} must use the plain global namespace, not {cf!r}", canon)
        else:
            if cf != sanitize_feature(feat):
                add("IDENTITY_MAP_INCONSISTENT", f"canonical namespace {cf!r} does not match feature {feat!r} for {canon!r}", canon)
        key_fl = (feat, local)
        if key_fl in seen_fl and seen_fl[key_fl] != canon:
            add("IDENTITY_MAP_INCONSISTENT", f"feature {feat!r} local {local!r} is claimed by conflicting canonical identities {seen_fl[key_fl]!r} and {canon!r}", canon)
        seen_fl[key_fl] = canon
        if alias:
            key_a = (feat, alias)
            if key_a in seen_alias and seen_alias[key_a] != canon:
                add("IDENTITY_MAP_INCONSISTENT", f"legacy alias {alias!r} in feature {feat!r} conflicts between {seen_alias[key_a]!r} and {canon!r}", canon)
            seen_alias[key_a] = canon
        sp = e.get("source_path")
        if isinstance(sp, str) and sp:
            dirf = feature_from_path(sp)
            if dirf and not is_global_feature(feat):
                mapped = features.get(dirf) if isinstance(features, dict) else None
                if mapped is not None:
                    if sanitize_feature(str(mapped)) != feat:
                        add("IDENTITY_MAP_INCONSISTENT", f"entity {canon!r} feature {feat!r} disagrees with feature mapping {dirf!r} -> {mapped!r}", canon)
                elif dirf != feat:
                    add("IDENTITY_MAP_INCONSISTENT", f"entity {canon!r} source {sp!r} is in feature directory {dirf!r} but declares feature {feat!r} with no explaining feature mapping", canon)
    # Persisted vs authored agreement for overlapping canonicals.
    secs = list(sections or ())
    by_canon = {getattr(s, "node_id", ""): s for s in secs}
    for e in valid_entities:
        s = by_canon.get(e["canonical_id"])
        if s is None:
            continue
        if getattr(s, "local_id", "") != e["local_id"] or getattr(s, "feature_id", "") != e["feature"] or getattr(s, "kind", "") != e["kind"]:
            add("IDENTITY_MAP_INCONSISTENT", f"persisted identity {e['canonical_id']!r} (local={e['local_id']!r}, feature={e['feature']!r}, kind={e['kind']!r}) disagrees with authored metadata (local={getattr(s, 'local_id', '')!r}, feature={getattr(s, 'feature_id', '')!r}, kind={getattr(s, 'kind', '')!r})", e["canonical_id"])
        elif e.get("legacy_alias", "") != getattr(s, "legacy_alias", "") and not (e.get("legacy_alias", "") == "" and getattr(s, "id_missing", False)):
            # Authored alias for an ID-less (T-AUTO) entity is empty; otherwise alias must be preserved exactly.
            if not getattr(s, "id_missing", False):
                add("IDENTITY_MAP_INCONSISTENT", f"persisted legacy alias {e.get('legacy_alias')!r} for {e['canonical_id']!r} disagrees with authored alias {getattr(s, 'legacy_alias', '')!r}", e["canonical_id"])
    # Continuity: the persisted map is the authoritative record of migrated
    # identities. A persisted identity that is no longer authored must carry
    # an explicit, auditable reconciliation (its entity record is retained
    # for provenance); disappearance without one fails closed. A new
    # authored identity is never guessed to be a replacement.
    rec_by_canon: dict = {}
    rec_replacement_owner: dict = {}
    _actions = {"removed": "removed", "retired": "removed", "deleted": "removed",
                "reassigned": "reassigned", "renamed": "reassigned", "replaced": "reassigned"}
    recs_raw = identity_map.get("reconciliations", [])
    if not isinstance(recs_raw, list):
        add("IDENTITY_RECONCILIATION_INVALID", "identity map 'reconciliations' must be a list of records")
        recs_raw = []
    for r in recs_raw:
        if not isinstance(r, dict):
            add("IDENTITY_RECONCILIATION_INVALID", "reconciliation records must be objects")
            continue
        rcanon = r.get("canonical_id") or r.get("old_canonical_id") or r.get("from") or ""
        raction = _actions.get(str(r.get("action") or r.get("type") or "").strip().lower())
        rrepl = r.get("replacement") or r.get("new_canonical_id") or r.get("replaced_by") or r.get("to") or ""
        rreason = r.get("reason") or ""
        if not isinstance(rcanon, str) or not rcanon or raction is None:
            add("IDENTITY_RECONCILIATION_INVALID",
                f"reconciliation must name canonical_id and action removed|reassigned: {r!r}", str(rcanon))
            continue
        if not isinstance(rreason, str) or not rreason.strip():
            add("IDENTITY_RECONCILIATION_INVALID",
                f"reconciliation for {rcanon!r} must record an auditable reason", rcanon)
            continue
        if raction == "reassigned" and (not isinstance(rrepl, str) or not rrepl):
            add("IDENTITY_RECONCILIATION_INVALID",
                f"reassigned reconciliation for {rcanon!r} must name its replacement canonical identity", rcanon)
            continue
        if rcanon not in seen_canon:
            add("IDENTITY_RECONCILIATION_INVALID",
                f"reconciliation names {rcanon!r} which is not a persisted identity; retain the entity record for provenance", rcanon)
            continue
        if rcanon in rec_by_canon:
            add("IDENTITY_RECONCILIATION_CONFLICT",
                f"conflicting reconciliations for persisted identity {rcanon!r}", rcanon)
            continue
        if raction == "reassigned":
            if rrepl == rcanon:
                add("IDENTITY_RECONCILIATION_CONFLICT",
                    f"reconciliation for {rcanon!r} names itself as its replacement", rcanon)
                continue
            if rrepl in rec_replacement_owner:
                add("IDENTITY_RECONCILIATION_CONFLICT",
                    f"replacement {rrepl!r} is claimed by both {rec_replacement_owner[rrepl]!r} and {rcanon!r}", rcanon)
                continue
            rec_replacement_owner[rrepl] = rcanon
        rec_by_canon[rcanon] = {"action": raction, "replacement": rrepl, "reason": rreason}
    # Entity-level retirement markers are an equivalent explicit record.
    for e in valid_entities:
        canon = e["canonical_id"]
        replaced_by = e.get("replaced_by") or ""
        retired = e.get("retired") is True or \
            str(e.get("status", "")).strip().lower() in ("removed", "retired") or bool(replaced_by)
        if retired and canon not in rec_by_canon:
            rec_by_canon[canon] = {"action": "reassigned" if replaced_by else "removed",
                                   "replacement": replaced_by, "reason": "entity retirement marker"}
    if secs:
        for e in valid_entities:
            canon = e["canonical_id"]
            if canon in by_canon:
                if canon in rec_by_canon:
                    add("IDENTITY_RECONCILIATION_CONFLICT",
                        f"persisted identity {canon!r} is still authored but carries a "
                        f"{rec_by_canon[canon]['action']} reconciliation", canon)
                continue
            rec = rec_by_canon.get(canon)
            if rec is None:
                add("IDENTITY_DISAPPEARED",
                    f"persisted identity {canon!r} (kind {e['kind']!r}, feature {e['feature']!r}) is no longer authored "
                    "and has no reconciliation; an identity rename/removal must be recorded explicitly in the identity "
                    "map 'reconciliations' (action removed, or reassigned with its replacement), keeping this entity "
                    "record for provenance. No replacement is inferred from similar text or position", canon)
            elif rec["action"] == "reassigned":
                repl_sec = by_canon.get(rec["replacement"])
                if repl_sec is None:
                    add("IDENTITY_RECONCILIATION_INVALID",
                        f"reassignment of {canon!r} names replacement {rec['replacement']!r} which is not authored", canon)
                elif getattr(repl_sec, "kind", "") != e["kind"]:
                    add("IDENTITY_RECONCILIATION_CONFLICT",
                        f"reassignment of {canon!r} (kind {e['kind']!r}) names {rec['replacement']!r} of kind {getattr(repl_sec, 'kind', '')!r}", canon)
    return sorted(diags, key=lambda x: (x.code, x.node_id, x.path))


def section_identity_diagnostics(sec, identity_map=None) -> list:
    """Single canonical-ownership invariant for one authored section."""
    diags: list = []
    meta = getattr(sec, "meta", {}) or {}
    canonical = getattr(sec, "node_id", "") or ""
    kind = getattr(sec, "kind", "") or ""
    local = getattr(sec, "local_id", "") or split_canonical(canonical)[1]
    cf, cl = split_canonical(canonical)
    def add(code, msg):
        diags.append(Diagnostic(code, msg, canonical, getattr(sec, "path", "")))
    dirf = feature_from_path(getattr(sec, "path", "") or "")
    mapped = ""
    if isinstance(identity_map, dict) and isinstance(identity_map.get("features"), dict):
        mv = identity_map["features"].get(dirf)
        if mv:
            mapped = sanitize_feature(str(mv))
    declared = sanitize_feature(str(meta.get("feature", "")).strip()) if str(meta.get("feature", "")).strip() else ""
    if mapped and declared and mapped != declared:
        add("CANONICAL_FEATURE_MISMATCH", f"feature metadata {declared!r} contradicts persisted feature mapping {dirf!r} -> {mapped!r}")
    effective = mapped or declared or dirf
    if kind == "constitution" or is_global_feature(effective) or not effective:
        if cf and not is_global_feature(cf):
            add("INVALID_GLOBAL_NAMESPACE", f"global/shared entity {canonical!r} must use the plain global namespace (e.g. CON-001), not feature namespace {cf!r}")
    else:
        if not cf:
            add("CANONICAL_FEATURE_MISMATCH", f"feature-local entity {local!r} in feature {effective!r} must use canonical namespace {effective!r} (expected {effective}::{local})")
        elif cf != effective:
            add("CANONICAL_FEATURE_MISMATCH", f"canonical namespace {cf!r} contradicts feature ownership {effective!r} (directory {dirf!r}); preserve a matching identity mapping/feature metadata for a legitimate relocation")
    if cl != local:
        add("CANONICAL_LOCAL_MISMATCH", f"canonical local {cl!r} does not match local ID {local!r}")
    meta_local = str(meta.get("local_id", "")).strip() if meta.get("local_id") else ""
    if meta_local and meta_local != local:
        add("CANONICAL_LOCAL_MISMATCH", f"local_id metadata {meta_local!r} does not match local ID {local!r}")
    return diags
