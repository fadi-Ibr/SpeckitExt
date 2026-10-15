---
description: Author the specification with FR/SC IDs governed by constitution rules
---

# SpeckitExt traceability addendum (specify)

After the core workflow below, ensure every FR-xxx/SC-xxx entry carries a
speckitext metadata block with `governed_by:` naming the CON-xxx rules that
govern it. Preserve every pre-existing ID exactly; append new IDs only. Finish
by running `speckitext validate --project .` and fixing every diagnostic.

{CORE_TEMPLATE}
