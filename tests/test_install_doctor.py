import json
from pathlib import Path

from speckitext.compat import classify_specify_version
from speckitext.install import global_status, install_global, uninstall_global


def test_version_classification_distinct_states():
    assert classify_specify_version("1.0.10") == "tested-compatible"
    assert classify_specify_version("1.1.0") == "untested"
    assert classify_specify_version("0.5.0") == "unsupported"
    assert classify_specify_version(None) == "unknown"
    assert classify_specify_version("not-a-version") == "unknown"


def test_global_install_uninstall_cycle_is_owned_and_idempotent(tmp_path):
    home = tmp_path / "home"
    r1 = install_global(home)
    assert r1["status"] == "installed" and len(r1["installed"]) == 3  # claude, kimi, shared codex+muse
    status = global_status(home)
    assert status["agents"]["claude"]["installed"]
    assert status["agents"]["codex"]["skill_file"] == status["agents"]["muse"]["skill_file"]
    # Existing unrelated user skill is untouched.
    other = home / ".claude/skills/my-skill/SKILL.md"
    other.parent.mkdir(parents=True, exist_ok=True)
    other.write_text("mine", encoding="utf-8")
    r2 = install_global(home)
    assert r2["status"] == "installed" and not r2["installed"]  # idempotent
    manifest = json.loads((home / ".speckitext/install.json").read_text(encoding="utf-8"))
    assert all(e["sha256"].startswith("sha256:") for e in manifest["files"])
    out = uninstall_global(home)
    assert out["status"] == "uninstalled"
    assert other.read_text(encoding="utf-8") == "mine"  # preserved
    assert global_status(home)["agents"]["claude"]["installed"] is False


def test_global_install_refuses_unowned_collision(tmp_path):
    home = tmp_path / "home"
    victim = home / ".claude/skills/speckitext/SKILL.md"
    victim.parent.mkdir(parents=True, exist_ok=True)
    victim.write_text("user's own skill", encoding="utf-8")
    r = install_global(home)
    assert r["status"] == "conflict"
    assert victim.read_text(encoding="utf-8") == "user's own skill"


def test_uninstall_keeps_user_modified_owned_file(tmp_path):
    home = tmp_path / "home"
    install_global(home)
    owned = home / ".kimi-code/skills/speckitext/SKILL.md"
    owned.write_text(owned.read_text(encoding="utf-8") + "\nuser edit\n", encoding="utf-8")
    out = uninstall_global(home)
    assert out["status"] == "partial"
    assert owned.is_file()
    out2 = uninstall_global(home, force=True)
    assert out2["status"] == "uninstalled" and not owned.is_file()


def test_doctor_json_shape(tmp_path, capsys):
    from speckitext.cli import main
    assert main(["doctor", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["specify"]["classification"] in (
        "tested-compatible", "untested", "unsupported", "unknown")
    assert report["speckitext"]["schema_version"] == "1.0"
    assert set(report["agents"]) == {"claude", "codex", "kimi", "muse"}
