---
description: Full all-or-nothing migration of a legacy Spec Kit project
---

## User Input

```text
$ARGUMENTS
```

Migration is FULL, never gradual. First run
`speckitext migrate --project . --dry-run` and present the inventory, proposed
transformations, and every finding. Findings block activation: resolve them in
the source artifacts first; never invent relationships to pass validation.
Only after a clean dry-run, run `speckitext migrate --project . --apply`. If
anything goes wrong, run `speckitext migrate --project . --rollback`. Never
activate scoped implementation for an incompletely migrated project.
