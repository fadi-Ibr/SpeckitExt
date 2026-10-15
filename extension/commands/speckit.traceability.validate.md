---
description: Validate the SpeckitExt traceability graph
---

## User Input

```text
$ARGUMENTS
```

Run `speckitext validate --project .` from the project root. Report every
diagnostic verbatim (code, ID, file, reason). If validation fails, do not mark
planning complete and do not proceed to implementation; fix the artifacts and
re-run until the graph is valid.
