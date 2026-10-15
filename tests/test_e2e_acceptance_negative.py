"""Negative control: a no-op implementation cannot pass E2E acceptance."""
from pathlib import Path

import pytest

from test_agent_authoring_e2e import assert_implementation_outcome


def test_noop_implementation_fails_acceptance(tmp_path):
    proj = tmp_path / "noop"
    proj.mkdir()
    with pytest.raises(AssertionError):
        assert_implementation_outcome(proj, ["T001"], ["T009"])


def test_planning_only_implementation_fails_acceptance(tmp_path):
    proj = tmp_path / "planning-only"
    (proj / "specs").mkdir(parents=True)
    (proj / "specs" / "plan.md").write_text("# plan only\n", encoding="utf-8")
    with pytest.raises(AssertionError):
        assert_implementation_outcome(proj, ["T001"], [])
