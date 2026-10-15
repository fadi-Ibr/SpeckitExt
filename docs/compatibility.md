# Compatibility and Version Policy

SpeckitExt never treats a broad version-range declaration as evidence that a
Spec Kit version works. Compatibility states are distinct and machine-readable
via `speckitext doctor --json`:

| State | Meaning |
|---|---|
| `tested-compatible` | Exercised by this repo's integration tests (real `specify` init/preset/extension/integration/bootstrap runs) |
| `untested` | At/above the manifest floor but never integration-tested here; reported distinctly, never silently asserted |
| `unsupported` | Below the preset/extension manifest floor (`>=0.9.0`) |
| `unknown` | Version undetectable or unparseable |

## Recorded provenance (this release)

| Item | Value |
|---|---|
| SpeckitExt package | 1.1.0 |
| Traceability schema | 1.0 |
| Compiler | 1.1.0 |
| Preset / extension | 1.1.0 / 1.1.0 |
| Tested `specify` (installed) | **1.0.10**, `C:\Users\Fadi\.local\bin\specify.exe`, installed via `uv tool` (`specify-cli`) |
| Upstream source reference | github/spec-kit `main` @ `3238fa9285694dc539aeb9829b337bfd6aed7317`, source version `1.2.1.dev0`, source-inspected 2026-10-15 for preset/extension/integration APIs |
| Agent CLIs present | Claude Code 2.1.300, Codex 0.162.1, Kimi Code 2.1.1, Muse Code 1.4.8 |

Per-project state is recorded in `.specify/speckitext.json` at bootstrap time
(SpeckitExt + specify versions, integrations, effective registration state,
timestamp). Diagnosis records and reports; it never upgrades, downgrades, or
otherwise modifies the user's Spec Kit installation.

## Safe upgrade procedure for Spec Kit

1. Note the current state: `speckitext doctor --json` (record
   `specify.classification`).
2. Upgrade Spec Kit by its own mechanism (for uv-tool installs:
   `uv tool upgrade specify-cli`) — never as a side effect of SpeckitExt.
3. Re-run `speckitext doctor --json`. If the new version is `untested`, treat
   compatibility as unverified until the integration suite passes against it:
   `python -m pytest -q` in a SpeckitExt checkout (the bootstrap/E2E tests
   exercise the real CLI).
4. In each project, re-check effective overrides with
   `speckitext doctor --project .`; re-run `speckitext bootstrap` only on NEW
   projects, and review established projects individually.
5. Roll back by reinstalling the previously tested Spec Kit version with the
   same tool that installed it.

## Failing safely

When classification is `unsupported`, or a project's effective
`speckit-implement` is missing/upstream/conflicting, SpeckitExt doctor reports
the precise diagnostic and exits non-zero; the implementation command instructs
agents to stop and report rather than fall back to upstream's broad-loading
workflow.

## Version policy (1.1.1)

Only versions in `TESTED_SPECIFY_VERSIONS` (currently specify-cli 1.0.10) are *verified*. Untested/unknown versions permit read-only `speckitext doctor` diagnosis but bootstrap/registration refuses them without explicit `--allow-untested-specify` confirmation; below-floor versions are refused outright. Doctor exits nonzero when any recorded project integration lacks a verified scoped override, or the global install manifest is corrupt.
