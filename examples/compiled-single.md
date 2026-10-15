<!-- speckitext-package
{"blocked_prerequisites":[],"compiler_version":"1.0.0","expansions":[],"governance_excluded":[{"applicability":"SCOPED","id":"CON-004","reason":"scope ['COMP-002'] does not intersect selected components ['COMP-001']"}],"governance_included":[{"applicability":"GLOBAL","id":"CON-001","reason":"GLOBAL: always included"},{"applicability":"SCOPED","id":"CON-002","reason":"SCOPED: scope intersects COMP-001"},{"applicability":"CONDITIONAL","id":"CON-003","reason":"CONDITIONAL: condition true: component == COMP-001"}],"included_ids":["CON-001","CON-002","CON-003","FR-001","DEC-001","COMP-001","CTR-001","VER-001","T001","T002"],"package_fingerprint":"sha256:2eb2e6f9fd647db31a3604259a17170b0a8b95c833caac9298fff21fe50e38ce","prerequisites":["T001"],"schema_version":"1.0","selected_tasks":["T002"],"source_refs":[{"anchor":"con-001-test-first","fingerprint":"sha256:1e7181c1f42c443319a002b36c7f9f5ee23f7d6ee950da36883eeca1d61b63d2","id":"CON-001","kind":"constitution","lines":[3,10],"path":".specify/memory/constitution.md","reason":"GLOBAL: always included"},{"anchor":"con-002-auth-hardening","fingerprint":"sha256:91c0cc6fa826be73eba90eab5815067b2d43c8d6c713fbacc6fb98090ecb8b8c","id":"CON-002","kind":"constitution","lines":[11,19],"path":".specify/memory/constitution.md","reason":"SCOPED: scope intersects COMP-001"},{"anchor":"con-003-audit-logging","fingerprint":"sha256:bfe935b9508e010c2e82d4affea50a7354ed0f03a673e289509df983a17d9861","id":"CON-003","kind":"constitution","lines":[20,28],"path":".specify/memory/constitution.md","reason":"CONDITIONAL: condition true: component == COMP-001"},{"anchor":"fr-001","fingerprint":"sha256:3de66e0f23035dd69d292cc5fe067fb14349affcd8a62f367579d5455780ef1d","id":"FR-001","kind":"requirement","lines":[3,9],"path":"specs/001-demo/spec.md","reason":"T002 --satisfies--> FR-001"},{"anchor":"dec-001-session-tokens","fingerprint":"sha256:90414ec2b7750148ec2dbb47d7bcf7ce91c69b34c07671b95d1b7524737680ac","id":"DEC-001","kind":"decision","lines":[3,12],"path":"specs/001-demo/plan.md","reason":"T002 --implements--> DEC-001"},{"anchor":"comp-001-auth-service","fingerprint":"sha256:2beb5cf88fa8cdd88ba67f26759755c86154154f0fd11a4f646f5019ba27ac0b","id":"COMP-001","kind":"component","lines":[13,20],"path":"specs/001-demo/plan.md","reason":"T002 --affects_component--> COMP-001"},{"anchor":"ctr-001-login-api","fingerprint":"sha256:3d42d5c463e0d844d8e052498cd574fd615f9eba88972cdc81b6feb50ef857ad","id":"CTR-001","kind":"contract","lines":[29,36],"path":"specs/001-demo/plan.md","reason":"T002 --implements--> CTR-001"},{"anchor":"ver-001-auth-tests","fingerprint":"sha256:797cf8aba5e832f0c857b26f71c6f7e2a03459568249bc71551d15933f59c68a","id":"VER-001","kind":"verification","lines":[3,9],"path":"specs/001-demo/tasks.md","reason":"T002 --verified_by--> VER-001"},{"anchor":"t001","fingerprint":"sha256:9abff195d219da5e7a68c39ecec596b2ffa879f510817d1aea4845b6d34582cf","id":"T001","kind":"task","lines":[17,25],"path":"specs/001-demo/tasks.md","reason":"completed prerequisite"},{"anchor":"t002","fingerprint":"sha256:3835d2ff3e5a1618a1cf740b3dd56822dfa465216c4f8facf3017f962ba07784","id":"T002","kind":"task","lines":[26,36],"path":"specs/001-demo/tasks.md","reason":"selected task"}],"validation":"pass"}
-->
# SpeckitExt Context Package

- Selected tasks: T002
- Compiler: speckitext 1.0.0 / schema 1.0
- Validation: pass

## Source provenance

| ID | Kind | Source | Anchor | Fingerprint | Inclusion reason |
|---|---|---|---|---|---|
| CON-001 | constitution | .specify/memory/constitution.md | con-001-test-first | sha256:1e7181c1f42c… | GLOBAL: always included |
| CON-002 | constitution | .specify/memory/constitution.md | con-002-auth-hardening | sha256:91c0cc6fa826… | SCOPED: scope intersects COMP-001 |
| CON-003 | constitution | .specify/memory/constitution.md | con-003-audit-logging | sha256:bfe935b9508e… | CONDITIONAL: condition true: component == COMP-001 |
| FR-001 | requirement | specs/001-demo/spec.md | fr-001 | sha256:3de66e0f2303… | T002 --satisfies--> FR-001 |
| DEC-001 | decision | specs/001-demo/plan.md | dec-001-session-tokens | sha256:90414ec2b775… | T002 --implements--> DEC-001 |
| COMP-001 | component | specs/001-demo/plan.md | comp-001-auth-service | sha256:2beb5cf88fa8… | T002 --affects_component--> COMP-001 |
| CTR-001 | contract | specs/001-demo/plan.md | ctr-001-login-api | sha256:3d42d5c463e0… | T002 --implements--> CTR-001 |
| VER-001 | verification | specs/001-demo/tasks.md | ver-001-auth-tests | sha256:797cf8aba5e8… | T002 --verified_by--> VER-001 |
| T001 | task | specs/001-demo/tasks.md | t001 | sha256:9abff195d219… | completed prerequisite |
| T002 | task | specs/001-demo/tasks.md | t002 | sha256:3835d2ff3e5a… | selected task |

## Governing rules (applicable only)

### CON-001: Test first
<!-- speckitext
id: CON-001
kind: constitution
applicability: GLOBAL
-->
Every change ships with a failing-then-passing test.

<!-- source: .specify/memory/constitution.md#con-001-test-first lines 3-10 fingerprint sha256:1e7181c1f42c443319a002b36c7f9f5ee23f7d6ee950da36883eeca1d61b63d2 -->

### CON-002: Auth hardening
<!-- speckitext
id: CON-002
kind: constitution
applicability: SCOPED
scope: COMP-001
-->
Auth component must hash passwords with a slow KDF.

<!-- source: .specify/memory/constitution.md#con-002-auth-hardening lines 11-19 fingerprint sha256:91c0cc6fa826be73eba90eab5815067b2d43c8d6c713fbacc6fb98090ecb8b8c -->

### CON-003: Audit logging
<!-- speckitext
id: CON-003
kind: constitution
applicability: CONDITIONAL
condition: component == COMP-001
-->
Auth operations must emit audit log lines.

<!-- source: .specify/memory/constitution.md#con-003-audit-logging lines 20-28 fingerprint sha256:bfe935b9508e010c2e82d4affea50a7354ed0f03a673e289509df983a17d9861 -->

## Requirements

- **FR-001**: Users MUST log in with email and password
<!-- speckitext
id: FR-001
kind: requirement
governed_by: CON-001
feature: 001-demo
-->

<!-- source: specs/001-demo/spec.md#fr-001 lines 3-9 fingerprint sha256:3de66e0f23035dd69d292cc5fe067fb14349affcd8a62f367579d5455780ef1d -->

## Architecture and decisions

### DEC-001: Session tokens
<!-- speckitext
id: DEC-001
kind: decision
governed_by: CON-001
satisfies: FR-001
affects_component: COMP-001
-->
Use opaque session tokens stored server-side.

<!-- source: specs/001-demo/plan.md#dec-001-session-tokens lines 3-12 fingerprint sha256:90414ec2b7750148ec2dbb47d7bcf7ce91c69b34c07671b95d1b7524737680ac -->

## Components

### COMP-001: Auth service
<!-- speckitext
id: COMP-001
kind: component
governed_by: CON-001
-->
Owns src/auth.py; login, logout, session lookup.

<!-- source: specs/001-demo/plan.md#comp-001-auth-service lines 13-20 fingerprint sha256:2beb5cf88fa8cdd88ba67f26759755c86154154f0fd11a4f646f5019ba27ac0b -->

## Contracts

### CTR-001: Login API
<!-- speckitext
id: CTR-001
kind: contract
governed_by: CON-001
-->
POST /login {email, password} -> {session_token} or 401.

<!-- source: specs/001-demo/plan.md#ctr-001-login-api lines 29-36 fingerprint sha256:3d42d5c463e0d844d8e052498cd574fd615f9eba88972cdc81b6feb50ef857ad -->

## Verification criteria

### VER-001: Auth tests
<!-- speckitext
id: VER-001
kind: verification
-->
Run: pytest tests/test_auth.py -q

<!-- source: specs/001-demo/tasks.md#ver-001-auth-tests lines 3-9 fingerprint sha256:797cf8aba5e832f0c857b26f71c6f7e2a03459568249bc71551d15933f59c68a -->

## Tasks

- [x] T001 Create auth module skeleton in src/auth.py
<!-- speckitext
id: T001
kind: task
satisfies: FR-001
verified_by: VER-001
affects_component: COMP-001
feature: 001-demo
-->

<!-- source: specs/001-demo/tasks.md#t001 lines 17-25 fingerprint sha256:9abff195d219da5e7a68c39ecec596b2ffa879f510817d1aea4845b6d34582cf -->

- [ ] T002 Implement login endpoint for FR-001 in src/auth.py
<!-- speckitext
id: T002
kind: task
satisfies: FR-001
implements: DEC-001, CTR-001
depends_on: T001
verified_by: VER-001
affects_component: COMP-001
feature: 001-demo
-->

<!-- source: specs/001-demo/tasks.md#t002 lines 26-36 fingerprint sha256:3835d2ff3e5a1618a1cf740b3dd56822dfa465216c4f8facf3017f962ba07784 -->

## Governance excluded (explainable trace)

- CON-004 (SCOPED): scope ['COMP-002'] does not intersect selected components ['COMP-001']
