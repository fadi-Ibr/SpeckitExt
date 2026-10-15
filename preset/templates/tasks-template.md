---
description: "Task list template for feature implementation (SpeckitExt traceability)"
---

# Tasks: [FEATURE NAME]

**Input**: Design documents from `/specs/[###-feature-name]/`
**Prerequisites**: plan.md (required), spec.md (required)

<!--
SpeckitExt traceability: every task keeps its Txxx ID forever (completion only
flips [ ] to [x]) and declares, in the metadata comment directly under it:
  satisfies or implements -> the requirement/decision/component it delivers
  verified_by             -> the VER-xxx check that proves it
  depends_on              -> prerequisite Txxx tasks
  affects_component       -> COMP-xxx components it touches
A task without satisfies/implements and verified_by fails validation and can
never enter an implementation context package.
-->

## Verification obligations

### VER-001: [Check name]
<!-- speckitext
id: VER-001
kind: verification
-->
[Exact focused check command or test, and what passing proves]

## Phase 1: Setup

- [ ] T001 Create project structure per implementation plan
<!-- speckitext
id: T001
kind: task
satisfies: FR-001
verified_by: VER-001
affects_component: COMP-001
-->

## Phase 2: User Story 1 (Priority: P1)

- [ ] T002 [US1] Implement [feature] in src/[file]
<!-- speckitext
id: T002
kind: task
satisfies: FR-001
implements: DEC-001
depends_on: T001
verified_by: VER-001
affects_component: COMP-001
-->
