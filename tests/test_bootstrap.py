"""Four-agent bootstrap/registration E2E on disposable NEW projects only.

Skipped when the real `specify` CLI is unavailable.
"""
import shutil
import subprocess
from pathlib import Path

import pytest

from speckitext.bootstrap import bootstrap_project
from speckitext.registration import registration_status

REPO = Path(__file__).resolve().parent.parent
pytestmark = pytest.mark.skipif(shutil.which("specify") is None,
                                reason="specify CLI not installed")


def test_bootstrap_all_four_integrations(tmp_path):
    proj = tmp_path / "fresh-proj"
    result = bootstrap_project(proj, ("claude", "codex", "kimi", "muse"),
                               str(REPO / "preset"), str(REPO / "extension"))
    assert result["status"] == "bootstrapped", result
    status = registration_status(proj)
    for key in ("claude", "codex", "kimi", "muse"):
        entry = status["integrations"][key]
        assert entry["state"] == "speckitext", (key, entry)
        assert entry["override_active"] is True
        for f in entry["files"]:
            body = (proj / f["path"]).read_text(encoding="utf-8")
            assert "speckitext compile" in body
            assert "Read tasks.md for the complete task list" not in body
    # Compatibility metadata recorded in the project.
    assert (proj / ".specify/speckitext.json").is_file()
    # Shared Codex/Muse directory registered exactly once per file.
    agents_files = [f["path"] for f in status["integrations"]["codex"]["files"]]
    muse_files = [f["path"] for f in status["integrations"]["muse"]["files"]]
    assert agents_files == muse_files and agents_files


def test_bootstrap_refuses_established_project(tmp_path):
    proj = tmp_path / "established"
    (proj / "specs/001-x").mkdir(parents=True)
    (proj / "specs/001-x/spec.md").write_text("# authored spec", encoding="utf-8")
    (proj / ".specify").mkdir()
    result = bootstrap_project(proj, ("claude",), str(REPO / "preset"), str(REPO / "extension"))
    assert result["status"] == "refused"


def test_bootstrap_subset_integrations(tmp_path):
    proj = tmp_path / "claude-only"
    result = bootstrap_project(proj, ("claude",), str(REPO / "preset"), str(REPO / "extension"))
    assert result["status"] == "bootstrapped", result
    status = registration_status(proj)
    assert status["integrations"]["claude"]["override_active"] is True
    assert status["integrations"]["kimi"]["state"] == "missing"
