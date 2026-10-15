"""Scaled-corpus efficiency: scoped packages stay ~constant while the full
planning corpus an upstream implement run loads grows with every feature."""
from pathlib import Path

from speckitext.compiler import compile_context
from speckitext.graph import Graph
from tests.conftest import CONSTITUTION, PLAN, SPEC, TASKS


def _scaled(root: Path, features: int) -> Path:
    (root / ".specify/memory").mkdir(parents=True, exist_ok=True)
    (root / ".specify/memory/constitution.md").write_text(CONSTITUTION, encoding="utf-8")
    for i in range(1, features + 1):
        d = root / f"specs/{i:03d}-f{i}"
        d.mkdir(parents=True, exist_ok=True)
        spec = SPEC.replace("FR-00", f"FR-{i}0").replace("001-demo", f"{i:03d}-f{i}")
        plan = PLAN.replace("DEC-001", f"DEC-{i}01").replace("COMP-001", f"COMP-{i}01") \
                   .replace("COMP-002", f"COMP-{i}02").replace("CTR-001", f"CTR-{i}01") \
                   .replace("FR-001", f"FR-{i}01")
        tasks = TASKS.replace("VER-001", f"VER-{i}01").replace("VER-002", f"VER-{i}02") \
                     .replace("FR-001", f"FR-{i}01").replace("FR-002", f"FR-{i}02") \
                     .replace("FR-003", f"FR-{i}03").replace("DEC-001", f"DEC-{i}01") \
                     .replace("CTR-001", f"CTR-{i}01").replace("COMP-001", f"COMP-{i}01") \
                     .replace("COMP-002", f"COMP-{i}02").replace("001-demo", f"{i:03d}-f{i}")
        # Task IDs stay T00x per feature directory (IDs are namespaced per feature file
        # only if unique project-wide, so prefix tasks per feature instead).
        tasks = tasks.replace("T001", f"T{i}01").replace("T002", f"T{i}02") \
                     .replace("T003", f"T{i}03").replace("T004", f"T{i}04").replace("T005", f"T{i}05")
        (d / "spec.md").write_text(spec, encoding="utf-8")
        (d / "plan.md").write_text(plan, encoding="utf-8")
        (d / "tasks.md").write_text(tasks, encoding="utf-8")
    return root


def test_scoped_context_beats_scaled_baseline(tmp_path):
    root = _scaled(tmp_path / "scaled", features=8)
    g = Graph.build(root)
    baseline = sum(len(p.read_text(encoding="utf-8"))
                   for p in root.rglob("*.md") if ".specify/memory" in str(p) or "specs" in str(p))
    single = compile_context(g, root, ["T102"])["text"]
    assert len(single) < baseline / 2
    # Unrelated features contribute nothing to the package.
    assert "FR-801" not in single and "T805" not in single
