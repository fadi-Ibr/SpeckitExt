---
description: Enroll new identities into the SpeckitExt identity map
---

## User Input

```text
$ARGUMENTS
```

Run `speckitext identity sync --project .` from the project root after
authoring new tasks or planning entities. It enrolls new canonical
identities into `.speckitext/identity.json` atomically and idempotently.
If it refuses (unexplained identity disappearance, corrupt map,
duplicates), report the diagnostics verbatim and fix the artifacts — a
renamed or removed enrolled identity needs an explicit reconciliation
record in the identity map (`removed`, or `reassigned` with its
replacement, plus a reason), never a silent edit or a hand-deleted map
entry. Use `--dry-run` to preview pending enrollment without writing.
