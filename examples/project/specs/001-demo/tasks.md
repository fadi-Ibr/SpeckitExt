# Tasks: Demo

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
- [ ] T004 Build dashboard page for FR-002 in src/ui.py
<!-- speckitext
id: T004
kind: task
satisfies: FR-002
verified_by: VER-002
affects_component: COMP-002
feature: 001-demo
-->
- [ ] T005 Export reports as CSV for FR-003 in src/reports.py
<!-- speckitext
id: T005
kind: task
satisfies: FR-003
verified_by: VER-001
feature: 001-demo
-->
