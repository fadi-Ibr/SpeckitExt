---
description: Compile a task/batch-scoped context package
---

## User Input

```text
$ARGUMENTS
```

The input names task IDs (e.g. `T003` or `T003,T004`). Run
`speckitext validate --project .`, then
`speckitext compile --project . --tasks <IDs> --output .specify/context/<selection>.md`.
Report the included IDs, blocked prerequisites, and package fingerprint. Load
only the compiled package for implementation; never substitute whole planning
documents for a failed compilation.
