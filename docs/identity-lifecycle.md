# Identity Lifecycle Design

## Authority and persistence

Once present, `.speckitext/identity.json` (version 1) is the authoritative
continuity record for a project's entities. The authored Markdown documents
are the current state; the `canonical_id` metadata in them must agree with
the map. A project with no identity map and no activated migration journal
referencing one is *unenrolled*: valid, but unprotected until migration or
`speckitext identity sync` enrolls it. A project whose activated migration
journal records an identity map that is now missing is an error
(`IDENTITY_MAP_MISSING`): deleting the sidecar never reverts a project to
unenrolled.

## Lifecycle states (per canonical identity)

| State | Authored | Persisted | Meaning |
|---|---|---|---|
| UNENROLLED | yes | no | New work not yet protected; `IDENTITY_UNENROLLED` warning while a map exists |
| ENROLLED | yes | yes | Normal state; the two records agree on identity |
| RETIRED | no | yes, with reconciliation | Intentionally removed or reassigned; record kept for provenance |
| DISAPPEARED | no | yes, without reconciliation | Error (`IDENTITY_DISAPPEARED`); blocks every graph operation |

Continuity is always evaluated against the full authored set, including an
empty set: an established project that loses all artifacts reports every
identity as disappeared. A genuinely new empty project has no map and no
journal, so nothing is expected of it.

## Allowed transitions

- Author a new entity: UNENROLLED, then ENROLLED via `identity sync`
  (or a full migration). The task-authoring checkpoints run sync before
  validation, so ordinary authoring enrolls without a separate ritual.
- Edit content, flip task status, reorder, or relocate a feature with its
  canonical identity preserved (identity map `features` mapping): stays
  ENROLLED. Sync refreshes only the source path/lines/status snapshot.
- Rename or remove an ENROLLED entity: keep its entity record and add one
  reconciliation (below), making it RETIRED. A replacement starts
  UNENROLLED and enrolls like any new entity.
- Reuse a RETIRED identity in authored documents while its reconciliation
  stands is a conflict. Removing the reconciliation and re-authoring the
  identity together is the explicit, auditable un-retirement.
- No transition is ever inferred: similar text, position, or filename never
  makes one identity the replacement for another, and no operation deletes
  entity records.

## Reconciliation (the single mechanism)

```json
{"canonical_id": "001-alpha::T001", "action": "removed", "reason": "withdrawn by spec change"}
{"canonical_id": "001-alpha::T001", "action": "reassigned", "replacement": "001-alpha::T999", "reason": "renumbered"}
```

Rules, all blocking errors when violated: keys are exactly
`canonical_id`/`action`/`replacement`/`reason` (legacy alias keys are
rejected with a rewrite hint); `action` is `removed` or `reassigned`;
`reason` is a non-empty string; `replacement` is required for
`reassigned`, forbidden for `removed`, must be currently authored, of the
same kind, claimed by exactly one reconciliation, not itself retired, and
must point directly at the authored replacement (no chains, no cycles).
The reconciled identity must have a retained entity record and must not
still be authored. Entity-record fields such as `retired` or
`replaced_by` carry no authority on their own.

## Read-only vs mutating operations

Read-only (never write the identity map): `validate`, `batch`, `impact`,
`doctor`, `migrate --dry-run`, `identity sync --dry-run`; `compile` and
`expand` write only their package output. Mutating: `migrate --apply`
(full staged transaction including the sidecar) and `identity sync`
(sidecar only). Both refuse on an incomplete migration, a corrupt or
expected-but-missing map, any identity error diagnostic (including
unexplained disappearance), duplicates, and canonical-ownership conflicts.
Sync therefore can enroll additions but can never launder a deletion into
an authorized removal.

## Transaction and failure behavior

Sync computes a deterministic candidate map (entities sorted by canonical
ID, stable key order), validates it in memory against the current graph,
and writes it with the same atomic procedure as the migration journal:
write `identity.json.tmp`, fsync, `os.replace`, fsync the directory. A
failure before or during the replace leaves the prior map byte-exact and
removes the temp file; a repeated sync with nothing to change writes
nothing (idempotent, byte-identical). Migration keeps its existing
staged/backup/rollback transaction; sync deliberately reuses the atomic
write pattern rather than introducing a second transaction architecture
for a single-file update.

## Backward compatibility

Identity-map version stays 1 and schema stays 2.0. Maps without
`reconciliations` remain valid; the field is written (possibly empty) by
sync and migration. Reconciliation alias key forms briefly accepted by
the previous revision were never written by any tool and are now rejected
explicitly so there is exactly one syntax at one validation strength.
Existing valid enrollments, aliases, canonical IDs, packages, and
migration journals are unaffected.
