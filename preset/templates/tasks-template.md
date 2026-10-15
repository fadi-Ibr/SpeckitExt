---
description: "Task list template for feature implementation (SpeckitExt traceability)"
---

# Tasks: [FEATURE NAME]

**Input**: Design documents from `/specs/[###-feature-name]/`
**Prerequisites**: plan.md (required), spec.md (required)

<!--
SpeckitExt traceability + readiness: every task keeps its Txxx ID forever
(completion only flips [ ] to [x]) and declares, in the metadata comment
directly under it:
  satisfies or implements -> the requirement/decision/component it delivers
  verified_by             -> the VER-xxx check that proves it
  depends_on              -> prerequisite Txxx tasks
  affects_component       -> COMP-xxx components it touches
Immediately under the metadata, every task carries three readiness lines:
  Objective: <one concrete sentence: the intended observable result>
  Scope: <exact files/areas the task may change>
  Accept: <observable acceptance conditions, separated by ";">
Do NOT copy requirements, decisions, or contracts into the task body; link by
ID and let the compiler retrieve shared detail. A task missing any of this —
or whose VER-xxx names no executable command — fails `speckitext validate`
and can never enter an implementation context package, so an assignment like
"Implement T002 using SpeckitExt" is sufficient on its own.
-->

## Verification obligations

### VER-001: Auth checks
<!-- speckitext
id: VER-001
kind: verification
-->
Run: `pytest tests/test_auth.py -q` — proves login behavior in FR-001.

## Phase 1: Setup

- [ ] T001 Create project structure per implementation plan
<!-- speckitext
id: T001
kind: task
satisfies: FR-001
verified_by: VER-001
affects_component: COMP-001
-->
  Objective: Project skeleton exists and the package imports cleanly
  Scope: src/, tests/
  Accept: package imports with no side effects; layout matches plan.md

## Phase 2: User Story 1 (Priority: P1)

- [ ] T002 [US1] Implement login endpoint in src/auth.py
<!-- speckitext
id: T002
kind: task
satisfies: FR-001
implements: DEC-001
depends_on: T001
verified_by: VER-001
affects_component: COMP-001
-->
  Objective: POST /login returns a session token for valid credentials
  Scope: src/auth.py, tests/test_auth.py
  Accept: valid login returns 200 with token; bad password returns 401
