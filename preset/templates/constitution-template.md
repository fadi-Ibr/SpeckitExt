# [PROJECT_NAME] Constitution

Every rule below carries a stable `CON-xxx` ID and explicit applicability.
IDs never change when rules are edited, inserted, or removed. Applicability is
one of `GLOBAL` (always in every context package), `SCOPED` (included when the
selected tasks touch a listed component), or `CONDITIONAL` (included when the
deterministic condition holds). Unresolvable conditions fail validation.

## Core Principles

### CON-001: [PRINCIPLE_1_NAME]
<!-- speckitext
id: CON-001
kind: constitution
applicability: GLOBAL
-->
[PRINCIPLE_1_DESCRIPTION]

### CON-002: [PRINCIPLE_2_NAME]
<!-- speckitext
id: CON-002
kind: constitution
applicability: GLOBAL
-->
[PRINCIPLE_2_DESCRIPTION]

### CON-003: [PRINCIPLE_3_NAME]
<!-- speckitext
id: CON-003
kind: constitution
applicability: SCOPED
scope: COMP-001
-->
[PRINCIPLE_3_DESCRIPTION — applies only to the scoped component]

### CON-004: [PRINCIPLE_4_NAME]
<!-- speckitext
id: CON-004
kind: constitution
applicability: CONDITIONAL
condition: component == COMP-001
-->
[PRINCIPLE_4_DESCRIPTION — applies only when the condition holds]

## Governance

Amendments add new `CON-xxx` IDs or edit rule text in place; IDs are never
renumbered or reused. Run `speckitext validate --project .` after every edit.

**Version**: [CONSTITUTION_VERSION] | **Ratified**: [RATIFICATION_DATE] | **Last Amended**: [LAST_AMENDED_DATE]
