from pathlib import Path

from speckitext.registration import classify_implement_body, registration_status

REPO = Path(__file__).resolve().parent.parent
UPSTREAM_SNIPPET = """# Implement
3. Load and analyze the implementation context:
   - **REQUIRED**: Read tasks.md for the complete task list and execution plan
   - **REQUIRED**: Read plan.md for tech stack, architecture, and file structure
   - **IF EXISTS**: Read /memory/constitution.md for governance constraints
"""


def _write(proj: Path, rel: str, body: str) -> None:
    p = proj / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")


def test_classify_signatures():
    ours = (REPO / "preset/commands/speckit.implement.md").read_text(encoding="utf-8")
    assert classify_implement_body(ours) == "speckitext"
    assert classify_implement_body(UPSTREAM_SNIPPET) == "upstream"
    assert classify_implement_body("# anything else") == "unknown"
    # Our override must never contain upstream broad-loading instructions.
    for marker in ("Read tasks.md for the complete task list",
                   "Load and analyze the implementation context"):
        assert marker not in ours


def test_upstream_project_local_skill_detected_as_shadow(tmp_path):
    _write(tmp_path, ".claude/skills/speckit-implement/SKILL.md", UPSTREAM_SNIPPET)
    status = registration_status(tmp_path)
    assert status["integrations"]["claude"]["state"] == "upstream"
    assert status["integrations"]["claude"]["override_active"] is False
    assert "do not silently" in status["integrations"]["claude"]["diagnostic"]


def test_speckitext_registration_active(tmp_path):
    ours = (REPO / "preset/commands/speckit.implement.md").read_text(encoding="utf-8")
    _write(tmp_path, ".agents/skills/speckit-implement/SKILL.md", ours)
    status = registration_status(tmp_path)
    for key in ("codex", "muse"):  # shared .agents/skills directory
        assert status["integrations"][key]["state"] == "speckitext"
        assert status["integrations"][key]["override_active"] is True
    assert status["integrations"]["claude"]["state"] == "missing"


def test_conflicting_registrations_flagged(tmp_path):
    ours = (REPO / "preset/commands/speckit.implement.md").read_text(encoding="utf-8")
    _write(tmp_path, ".claude/skills/speckit-implement/SKILL.md", ours)
    _write(tmp_path, ".claude/commands/speckit.implement.md", UPSTREAM_SNIPPET)
    status = registration_status(tmp_path)
    assert status["integrations"]["claude"]["state"] == "conflict"
    assert status["integrations"]["claude"]["override_active"] is False
