---
description: Generate linked tasks, then enforce the traceability validation gate
---

# SpeckitExt traceability addendum (tasks)

During the core workflow below, give every task a stable Txxx ID and a
speckitext metadata block directly under it declaring satisfies or implements,
verified_by, depends_on, and affects_component. VALIDATION GATE: after writing
tasks.md, run `speckitext validate --project .`. Do not report the task list as
complete while any diagnostic remains; fix links, never invent placeholder IDs.

{CORE_TEMPLATE}
