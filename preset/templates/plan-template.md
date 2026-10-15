# Implementation Plan: [FEATURE]

**Branch**: `[###-feature-name]` | **Date**: [DATE] | **Spec**: [link]
**Input**: Feature specification from `/specs/[###-feature-name]/spec.md`

<!--
SpeckitExt traceability: decisions (DEC-xxx), components (COMP-xxx), contracts
(CTR-xxx) and data-model entities (DM-xxx) each carry a speckitext metadata
block with typed relationships (governed_by, satisfies, constrained_by,
affects_component, depends_on). Example:

### DEC-001: [Decision title]
<!-- speckitext
id: DEC-001
kind: decision
governed_by: CON-001
satisfies: FR-001
affects_component: COMP-001
-->
-->

## Summary

[Primary requirement + technical approach]

## Technical Context

**Language/Version**: [e.g., Python 3.11 or NEEDS CLARIFICATION]
**Primary Dependencies**: [e.g., FastAPI or NEEDS CLARIFICATION]
**Storage**: [if applicable]
**Testing**: [e.g., pytest]
**Target Platform**: [e.g., Linux server]
**Project Type**: [e.g., library/cli/web-service]

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*
Run `speckitext validate --project .` and resolve every diagnostic.

## Decisions

### DEC-001: [Decision title]
<!-- speckitext
id: DEC-001
kind: decision
governed_by: CON-001
satisfies: FR-001
affects_component: COMP-001
-->
[Decision, rationale, alternatives considered]

## Components

### COMP-001: [Component name]
<!-- speckitext
id: COMP-001
kind: component
governed_by: CON-001
-->
[Responsibility, owned files, interfaces]

## Project Structure

```text
specs/[###-feature]/
├── plan.md
├── research.md
├── data-model.md
├── contracts/
└── tasks.md
```

**Structure Decision**: [Selected structure with real directories]
