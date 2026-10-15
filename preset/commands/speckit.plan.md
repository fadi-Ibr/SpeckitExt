---
description: Plan with DEC/COMP/CTR/DM IDs and typed relationships to requirements and rules
---

# SpeckitExt traceability addendum (plan)

During the core workflow below, give every decision, component, contract, and
data-model entity a stable DEC/COMP/CTR/DM ID with a speckitext metadata block
declaring governed_by, satisfies, constrained_by, and affects_component links as
applicable. Finish by enrolling new identities with
`speckitext identity sync --project .`, then running
`speckitext validate --project .` and fixing every diagnostic before
producing tasks.

{CORE_TEMPLATE}
