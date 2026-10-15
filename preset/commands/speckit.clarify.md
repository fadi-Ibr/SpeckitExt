---
description: Clarify while preserving stable IDs, relationships, and downstream traceability
---

# SpeckitExt traceability addendum (clarify)

During the core workflow below, never renumber, rename, or delete an existing
FR/SC/CON/DEC/T ID. When an answer changes a requirement, keep its ID, update
its text in place, then run `speckitext impact --project . --ids <ID>` to list
affected downstream artifacts and update them in the same change. Finish by
running `speckitext validate --project .` and fixing every diagnostic.

{CORE_TEMPLATE}
