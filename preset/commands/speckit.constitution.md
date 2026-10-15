---
description: Author the constitution with stable CON-xxx IDs and applicability metadata
---

# SpeckitExt traceability addendum (constitution)

After the core workflow below, ensure every principle/rule section carries a
`<!-- speckitext ... -->` block with a stable `CON-xxx` ID, `kind: constitution`,
and `applicability:` of GLOBAL, SCOPED (with `scope:` COMP-xxx list), or
CONDITIONAL (with a deterministic `condition:`). Never renumber or reuse an ID.
Finish by enrolling new identities with `speckitext identity sync --project .`,
then running `speckitext validate --project .` and fixing every diagnostic.

{CORE_TEMPLATE}
