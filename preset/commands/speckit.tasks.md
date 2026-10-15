---
description: Generate linked, implementation-ready tasks, then enforce the validation gate
---

# SpeckitExt traceability addendum (tasks)

During the core workflow below, give every task a stable Txxx ID and a
speckitext metadata block directly under it declaring satisfies or implements,
verified_by, depends_on, and affects_component.

## Implementation-readiness contract (authoring requirements)

Every task must be actionable from its ID alone — an assignment like
"Implement T042 using SpeckitExt" must need no restated specification. Each
task therefore carries, directly under its metadata block:

- `Objective:` — one concrete sentence naming the intended observable result.
- `Scope:` — the exact files/areas the task may change (ownership, not prose).
- `Accept:` — observable acceptance conditions separated by `;`.

Rules:

- Link shared detail by ID (requirements, DEC/COMP/CTR sections); never copy
  whole requirements, decisions, or contracts into a task body — the compiler
  retrieves them.
- Every `verified_by` target is a VER-xxx section naming an *executable*
  focused check (an actual command, e.g. `` `pytest tests/test_auth.py -q` ``),
  never prose like "run the tests".
- No unresolved placeholders (`[FEATURE]`, `TODO`, `TBD`, `NEEDS
  CLARIFICATION`) anywhere in a task or its VER-xxx sections.
- Semantic specificity is an authoring obligation: objectives and acceptance
  conditions must describe observable behavior, not restate the task title.
  Deterministic validation rejects omissions, placeholders, and vague
  verification; it cannot prove semantic quality — review for that.

VALIDATION GATE: after writing tasks.md, run `speckitext validate --project .`
(which includes readiness checks; `--graph-only` skips them). Do not report
the task list as complete while any diagnostic remains; fix links and task
bodies, never invent placeholder IDs.

{CORE_TEMPLATE}
