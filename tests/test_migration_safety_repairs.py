"""Final safety repairs: recovery conflicts, rollback integrity, and the
centralized incomplete-migration CLI guard. Synthetic fixtures only."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import speckitext.migration as migration_module
from speckitext.cli import main
from speckitext.migration import Migration, MigrationCrash, incomplete_migrations
from tests.test_migration import write_legacy


def _txn_root(root: Path) -> Path:
    return sorted((root / ".speckitext/migrations").glob("*"))[-1]


def _journal(root: Path) -> dict:
    return json.loads((_txn_root(root) / "journal.json").read_text(encoding="utf-8"))


def _dests(root: Path) -> dict[str, bytes]:
    return {rel: (root / rel).read_bytes() for rel in _journal(root)["files"]}


def _interrupted(tmp_path, crash_after=1):
    root = write_legacy(tmp_path / "legacy")
    originals = {p: p.read_bytes() for p in root.rglob("*.md")
                 if ".speckitext" not in p.parts}
    with pytest.raises(MigrationCrash):
        Migration(root).apply(crash_after=crash_after)
    return root, originals


def _activated(tmp_path):
    root = write_legacy(tmp_path / "legacy")
    originals = {p: p.read_bytes() for p in root.rglob("*.md")
                 if ".speckitext" not in p.parts}
    assert Migration(root).apply()["status"] == "activated"
    return root, originals


# ---- recovery conflicts (§2) -------------------------------------------------

def test_recovery_accepts_staged_destinations(tmp_path):
    # Every destination replaced, journal advance never landed for the last.
    root, originals = _interrupted(tmp_path, crash_after=3)
    txn = _txn_root(root)
    for rel in _journal(root)["files"]:
        assert (root / rel).read_bytes() == (txn / "staged" / rel).read_bytes()
    assert Migration(root).recover()["status"] == "recovered"
    for p, data in originals.items():
        assert p.read_bytes() == data
    assert Migration(root).recover()["status"] == "nothing-to-recover"
    assert Migration(root).apply()["status"] == "activated"


def test_recovery_conflict_preserves_every_file(tmp_path):
    root, _ = _interrupted(tmp_path, crash_after=2)
    journal = _journal(root)
    later = journal["files"][-1]  # untouched (original) or staged, then edited
    edited = (root / later).read_bytes() + b"\nUser edit after interruption.\n"
    (root / later).write_bytes(edited)
    before = _dests(root)
    result = Migration(root).recover()
    assert result["status"] == "recovery-conflict"
    conflict = next(c for c in result["conflicts"] if c["path"] == later)
    assert conflict["observed_sha256"] and len(conflict["expected"]) == 2
    assert _dests(root) == before  # later-file conflict: nothing restored first
    assert incomplete_migrations(root)  # still blocked
    # Explicit resolution: put the file back to a transaction state.
    backup = _txn_root(root) / "backup" / later
    (root / later).write_bytes(backup.read_bytes())
    assert Migration(root).recover()["status"] == "recovered"


def test_recovery_conflict_via_subprocess(tmp_path):
    root, _ = _interrupted(tmp_path, crash_after=1)
    rel = _journal(root)["files"][0]
    edited = (root / rel).read_bytes() + b"\nPost-interruption work.\n"
    (root / rel).write_bytes(edited)
    rec = subprocess.run([sys.executable, "-m", "speckitext", "migrate",
                          "--project", str(root), "--recover"],
                         capture_output=True, text=True)
    assert rec.returncode == 1
    assert json.loads(rec.stdout)["status"] == "recovery-conflict"
    assert (root / rel).read_bytes() == edited


# ---- rollback integrity (§3) -------------------------------------------------

def test_rollback_missing_backup_refuses_without_touching_files(tmp_path):
    root, originals = _activated(tmp_path)
    backup = _txn_root(root) / "backup" / _journal(root)["files"][0]
    saved = backup.read_bytes()
    before = _dests(root)
    backup.unlink()
    result = Migration(root).rollback()
    assert result["status"] == "rollback-refused"
    assert _dests(root) == before and _journal(root)["state"] == "activated"
    backup.write_bytes(saved)  # repair evidence, then rollback verifies fully
    assert Migration(root).rollback()["status"] == "rolled-back"
    for p, data in originals.items():
        assert p.read_bytes() == data


def test_rollback_corrupt_backup_and_legacy_journal_refuse(tmp_path):
    root, _ = _activated(tmp_path)
    backup = _txn_root(root) / "backup" / _journal(root)["files"][0]
    before = _dests(root)
    backup.write_bytes(b"corrupted backup")
    assert Migration(root).rollback()["status"] == "rollback-refused"
    assert _dests(root) == before

    root2, _ = _activated(tmp_path / "second")
    journal_path = _txn_root(root2) / "journal.json"
    journal = _journal(root2)
    journal["file_records"] = []  # legacy/corrupt: no verifiable hashes
    journal_path.write_text(json.dumps(journal), encoding="utf-8")
    before2 = _dests(root2)
    assert Migration(root2).rollback()["status"] == "rollback-refused"
    assert _dests(root2) == before2


def test_rollback_missing_destination_conflict_then_forced(tmp_path):
    root, originals = _activated(tmp_path)
    missing = _journal(root)["files"][0]
    (root / missing).unlink()
    before = {rel: (root / rel).read_bytes()
              for rel in _journal(root)["files"] if rel != missing}
    result = Migration(root).rollback()
    assert result["status"] == "rollback-conflict"
    assert {r: (root / r).read_bytes() for r in before} == before
    assert Migration(root).rollback(force=True)["status"] == "rolled-back"
    for p, data in originals.items():
        assert p.read_bytes() == data


def _flaky_backup_copy(monkeypatch, fail_on, exc=OSError):
    real_copyfile = shutil.copyfile
    calls = {"n": 0}

    def flaky(src, dst, *a, **kw):
        if "backup" in Path(src).parts:
            calls["n"] += 1
            if calls["n"] == fail_on:
                raise exc("injected restoration failure")
        return real_copyfile(src, dst, *a, **kw)

    monkeypatch.setattr(migration_module.shutil, "copyfile", flaky)
    return calls


def test_rollback_failure_after_first_file_is_resumable(tmp_path, monkeypatch):
    root, originals = _activated(tmp_path)
    _flaky_backup_copy(monkeypatch, fail_on=2)
    result = Migration(root).rollback()
    assert result["status"] == "recovery-required"  # never a false success
    journal = _journal(root)
    assert journal["state"] == "rolling-back" and len(journal["rollback_completed"]) == 1
    assert incomplete_migrations(root)
    monkeypatch.undo()
    assert Migration(root).rollback()["status"] == "rolled-back"  # resume
    for p, data in originals.items():
        assert p.read_bytes() == data


def test_interrupted_rollback_completed_by_recovery(tmp_path, monkeypatch):
    root, originals = _activated(tmp_path)
    _flaky_backup_copy(monkeypatch, fail_on=2, exc=MigrationCrash)
    with pytest.raises(MigrationCrash):
        Migration(root).rollback()
    assert _journal(root)["state"] == "rolling-back"
    monkeypatch.undo()
    assert Migration(root).recover()["status"] == "recovered"
    assert _journal(root)["state"] == "rolled-back"
    assert not incomplete_migrations(root)
    for p, data in originals.items():
        assert p.read_bytes() == data


# ---- centralized CLI guard (§4) ----------------------------------------------

def test_all_traceability_operations_blocked_until_recovery(tmp_path, capsys):
    root, _ = _interrupted(tmp_path, crash_after=1)
    out_pkg = tmp_path / "pkg.md"
    sentinel = tmp_path / "expand-pkg.md"
    sentinel.write_text("do not overwrite", encoding="utf-8")
    calls = [
        ["validate", "--project", str(root)],
        ["compile", "--project", str(root), "--tasks", "T002",
         "--output", str(out_pkg)],
        ["batch", "suggest", "--project", str(root)],
        ["expand", "--project", str(root), "--package", str(sentinel),
         "--ids", "FR-001"],
        ["impact", "--project", str(root), "--ids", "FR-001"],
    ]
    for argv in calls:
        assert main(argv) == 1, argv
        captured = capsys.readouterr()
        combined = captured.out + captured.err
        assert "recover" in combined.lower()
        assert "--recover" in combined
    assert not out_pkg.exists()  # no generated output while blocked
    assert sentinel.read_text(encoding="utf-8") == "do not overwrite"
    # Recovery itself is never blocked by the guard, and unblocks the rest.
    assert main(["migrate", "--project", str(root), "--recover"]) == 0
    capsys.readouterr()
    assert main(["migrate", "--project", str(root), "--apply"]) == 0
    capsys.readouterr()
    assert main(["validate", "--project", str(root)]) == 0
    capsys.readouterr()
    assert main(["batch", "suggest", "--project", str(root)]) == 0
