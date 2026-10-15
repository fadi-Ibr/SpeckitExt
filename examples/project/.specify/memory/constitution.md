# Demo Constitution

### CON-001: Test first
<!-- speckitext
id: CON-001
kind: constitution
applicability: GLOBAL
-->
Every change ships with a failing-then-passing test.

### CON-002: Auth hardening
<!-- speckitext
id: CON-002
kind: constitution
applicability: SCOPED
scope: COMP-001
-->
Auth component must hash passwords with a slow KDF.

### CON-003: Audit logging
<!-- speckitext
id: CON-003
kind: constitution
applicability: CONDITIONAL
condition: component == COMP-001
-->
Auth operations must emit audit log lines.

### CON-004: Unrelated UI rule
<!-- speckitext
id: CON-004
kind: constitution
applicability: SCOPED
scope: COMP-002
-->
UI components must support keyboard navigation.
