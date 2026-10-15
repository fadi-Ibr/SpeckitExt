# Implementation Plan: Demo

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
