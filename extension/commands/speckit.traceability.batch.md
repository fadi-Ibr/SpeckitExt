---
description: Suggest coherent dependency-aware task batches
---

## User Input

```text
$ARGUMENTS
```

Run `speckitext batch suggest --project .`. Present each suggested batch with
its grouping reasons, shared context, and blocked_by list. Let the user accept
a batch or name explicit task IDs instead; never merge unrelated tasks just to
fill capacity.
