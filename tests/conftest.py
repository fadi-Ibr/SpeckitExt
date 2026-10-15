"""Synthetic SpeckitExt project fixture builder. Disposable temp projects only."""
from __future__ import annotations

from pathlib import Path

import pytest

CONSTITUTION = """# Demo Constitution

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
"""

SPEC = """# Feature Specification: Demo

- **FR-001**: Users MUST log in with email and password
<!-- speckitext
id: FR-001
kind: requirement
governed_by: CON-001
feature: 001-demo
-->
- **FR-002**: Users MUST see a dashboard after login
<!-- speckitext
id: FR-002
kind: requirement
governed_by: CON-001
feature: 001-demo
-->
- **FR-003**: Users MUST export reports as CSV
<!-- speckitext
id: FR-003
kind: requirement
governed_by: CON-001
feature: 001-demo
-->
"""

PLAN = """# Implementation Plan: Demo

### DEC-001: Session tokens
<!-- speckitext
id: DEC-001
kind: decision
governed_by: CON-001
satisfies: FR-001
affects_component: COMP-001
-->
Use opaque session tokens stored server-side.

### COMP-001: Auth service
<!-- speckitext
id: COMP-001
kind: component
governed_by: CON-001
-->
Owns src/auth.py; login, logout, session lookup.

### COMP-002: Dashboard UI
<!-- speckitext
id: COMP-002
kind: component
governed_by: CON-001
-->
Owns src/ui.py; post-login dashboard.

### CTR-001: Login API
<!-- speckitext
id: CTR-001
kind: contract
governed_by: CON-001
-->
POST /login {email, password} -> {session_token} or 401.
"""

TASKS = """# Tasks: Demo

### VER-001: Auth tests
<!-- speckitext
id: VER-001
kind: verification
-->
Run: pytest tests/test_auth.py -q

### VER-002: UI tests
<!-- speckitext
id: VER-002
kind: verification
-->
Run: pytest tests/test_ui.py -q

- [x] T001 Create auth module skeleton in src/auth.py
<!-- speckitext
id: T001
kind: task
satisfies: FR-001
verified_by: VER-001
affects_component: COMP-001
feature: 001-demo
-->
  Objective: Auth module skeleton exists and imports cleanly
  Scope: src/auth.py
  Accept: src/auth.py imports with no side effects; package layout matches plan
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
  Objective: POST /login returns a session token for valid credentials
  Scope: src/auth.py
  Accept: valid login returns 200 with token; bad password returns 401
- [ ] T003 Add password hashing for FR-001 in src/auth.py
<!-- speckitext
id: T003
kind: task
satisfies: FR-001
depends_on: T002
verified_by: VER-001
affects_component: COMP-001
feature: 001-demo
-->
  Objective: Passwords are hashed with a slow KDF before storage
  Scope: src/auth.py
  Accept: stored value is not plaintext and verifies via the KDF check
- [ ] T004 Build dashboard page for FR-002 in src/ui.py
<!-- speckitext
id: T004
kind: task
satisfies: FR-002
verified_by: VER-002
affects_component: COMP-002
feature: 001-demo
-->
  Objective: Dashboard page renders for an authenticated user
  Scope: src/ui.py
  Accept: authenticated request renders dashboard; anonymous request redirects to login
- [ ] T005 Export reports as CSV for FR-003 in src/reports.py
<!-- speckitext
id: T005
kind: task
satisfies: FR-003
verified_by: VER-001
feature: 001-demo
-->
  Objective: Reports export downloads a CSV of the current report
  Scope: src/reports.py
  Accept: export returns text/csv with header row and one row per record
"""


def write_project(root: Path) -> Path:
    (root / ".specify" / "memory").mkdir(parents=True, exist_ok=True)
    (root / "specs" / "001-demo").mkdir(parents=True, exist_ok=True)
    (root / ".specify" / "memory" / "constitution.md").write_text(CONSTITUTION, encoding="utf-8")
    (root / "specs" / "001-demo" / "spec.md").write_text(SPEC, encoding="utf-8")
    (root / "specs" / "001-demo" / "plan.md").write_text(PLAN, encoding="utf-8")
    (root / "specs" / "001-demo" / "tasks.md").write_text(TASKS, encoding="utf-8")
    return root


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    return write_project(tmp_path / "proj")
