# SpeckitExt

Traceability-aware planning and deterministic, task/batch-scoped implementation
context for [GitHub Spec Kit](https://github.com/github/spec-kit).

## Problem addressed

Standard Spec Kit tells implementation agents to load broad planning artifacts
(constitution, spec, plan, tasks) even for a single small task. SpeckitExt moves
the relationship-discovery work into specification and planning: artifacts are
authored with stable IDs and explicit typed relationships from day one, and a
deterministic compiler (no LLM, no embeddings, no daemon) assembles exactly the
context a selected task or coherent batch needs — applicable governing rules,
linked requirements, decisions, contracts, prerequisites, and verification
criteria, each with source provenance and revision fingerprints.

Planning may cost extra tokens. That is an intentional trade: pay once at
authoring time, save on every repeated implementation run.

## Components

- **Traceability preset** (`preset/`) — structured templates and command
  overrides (`wrap` around upstream planning commands; `replace` for
  `speckit.implement`) installed through `specify preset add`.
- **Context extension** (`extension/`) — `speckit.traceability.*` agent
  commands and a mandatory `after_tasks` validation gate, installed through
  `specify extension add`.
- **`speckitext` CLI** (`src/speckitext/`) — graph validation, batch planning,
  context compilation/expansion, impact analysis, and full migration.
- **Joint bundle** (`bundle/bundle.yml`) — installs both components together
  where the bundle catalog resolves them (see Installation).

Architecture, schema, and contracts: [docs/architecture.md](docs/architecture.md).
Worked example: [examples/](examples/README.md).

## What's new in 1.1.0

- **Implementation-readiness gate**: tasks must carry `Objective:`/`Scope:`/
  `Accept:` lines, no placeholders, and executable verification checks —
  `speckitext validate` and `compile` enforce it, so "Implement T042 using
  SpeckitExt" is a sufficient assignment.
- **Registered-override proof**: `speckitext doctor --project .` classifies the
  `speckit-implement` each agent will actually load (SpeckitExt / upstream /
  conflict / missing), including project-local shadowing detection. The
  implementation command self-checks and stops rather than falling back to
  upstream's whole-document loading.
- **Compatibility doctor**: `speckitext doctor --json` reports tested /
  untested / unsupported / unknown Spec Kit versions (from real integration
  tests, not version ranges), installed agents, and per-project metadata.
  See [docs/compatibility.md](docs/compatibility.md).
- **Global multi-agent deployment**: `speckitext install --global` installs
  hash-tracked skill adapters for Claude Code, Codex, Kimi Code, and Muse
  Code; `speckitext bootstrap --project <new>` activates the preset+extension
  for all four integrations in a new project. See
  [docs/global-installation.md](docs/global-installation.md).

## Installation

Requires Python ≥ 3.11 and a Spec Kit installation (`specify` CLI ≥ 0.9.0).

```bash
# 1. Install the compiler CLI
git clone https://github.com/fadi-Ibr/SpeckitExt.git
cd SpeckitExt
python -m pip install -e ".[test]"

# 2. Create a fresh Spec Kit project (example uses the Claude integration;
#    any supported agent works the same way)
specify init my-project --integration claude --non-interactive
cd my-project

# 3. Install the preset and extension from the local SpeckitExt checkout
specify preset add --dev /path/to/SpeckitExt/preset
specify extension add --dev /path/to/SpeckitExt/extension

# Joint alternative, where catalog resolution is available:
specify bundle validate --path /path/to/SpeckitExt/bundle
specify bundle install speckitext
```

Installing the preset never rewrites an authored
`.specify/memory/constitution.md` (upstream guarantee); the structured
constitution template takes effect the next time the constitution command runs.

Uninstall/reinstall is symmetric and safe:

```bash
specify preset remove traceability
specify extension remove traceability
specify preset add --dev /path/to/SpeckitExt/preset
specify extension add --dev /path/to/SpeckitExt/extension
```

## Fresh project usage

Run the normal Spec Kit lifecycle (`/speckit.constitution` → `specify` →
`clarify` → `plan` → `tasks` → `analyze` → `implement`). The preset makes each
stage author stable IDs (`CON/FR/SC/DEC/COMP/CTR/DM/T/VER/RES`) and typed
relationships (`governed_by`, `satisfies`, `implements`, `depends_on`,
`constrained_by`, `affects_component`, `verified_by`) in
`<!-- speckitext -->` metadata blocks, and enforces a validation gate after
task generation:

```bash
speckitext validate --project .
```

## Context compiler workflow

```bash
# One task
speckitext compile --project . --tasks T002 --output .specify/context/T002.md

# An explicit batch
speckitext compile --project . --tasks T002,T003 --output .specify/context/batch-auth.md

# Detect a stale package after sources change
speckitext validate --project . --package .specify/context/T002.md

# Deterministically add a genuinely needed section (reason is recorded)
speckitext expand --project . --package .specify/context/T002.md --ids FR-002 --reason "redirect target after login"

# Impact of changing a requirement
speckitext impact --project . --ids FR-001
```

The overridden `speckit.implement` command resolves the selection, runs
validation/compilation, loads only the compiled package (never the full
constitution/plan/tasks), checks staleness, implements in dependency order,
runs the focused `VER-xxx` checks plus one consolidated batch verification, and
flips only the implemented tasks' checkboxes.

## Batch selection

```bash
speckitext batch suggest --project .
```

Batches group only tasks that share requirements, decisions, components, or
dependency edges — never unrelated tasks to fill capacity. Each suggestion
reports grouping reasons, shared context, and blocked external prerequisites.
Limits: `--max-tasks` (default 5) and `--max-context-chars` (default 60000).

## Migration

Migration of an existing legacy Spec Kit project is FULL and all-or-nothing
(there is no gradual or mixed mode), and scoped implementation stays gated
until the migrated graph validates:

```bash
speckitext migrate --project . --dry-run    # inventory, proposed diff, findings; writes nothing
speckitext migrate --project . --apply      # staged, validated, journaled activation
speckitext migrate --project . --recover    # restore an interrupted migration to its originals
speckitext migrate --project . --rollback   # restore the activated transaction's backups
```

While a migration transaction is incomplete (interrupted activation, an
interrupted rollback, or corrupt transaction evidence), `validate`,
`compile`, `batch suggest`, `expand`, and `impact` all refuse with a
recovery-required diagnostic and write no generated output; `--dry-run`,
`--recover`, `--rollback`, and `doctor` stay available for diagnosis and
resolution. Recovery preflights the whole transaction before touching any
file: each destination must still match its original or staged hash,
otherwise recovery reports a **recovery conflict**, preserves every file
(including edits made after the interruption), and waits for explicit
resolution — restore the conflicted file to its original/staged content
(or from the transaction `backup/`) and re-run `--recover`. Rollback
likewise preflights journal, backups, and destination state before
restoring, tracks progress so an interrupted rollback can be resumed by
`--rollback` or completed by `--recover`, and reports `rolled-back` only
after every restored file verifies against its original hash. A
successful recovery means every affected file is byte-identical to its
pre-migration original; a successful rollback means the same for the
activated transaction.

Relationships are derived only from textual evidence; anything ambiguous is a
blocking finding, never an invented link. See
[examples/migration/](examples/migration/) for a synthetic fixture, dry-run
output, and diff.

## Supported environments

Windows and POSIX; Python 3.11+; Spec Kit ≥ 0.9.0 with any supported coding
agent (command registration is upstream's portable mechanism). The compiler is
stdlib-only and works offline.

## Global deployment and diagnosis

```bash
speckitext install --global     # user-level skill adapters for Claude/Codex/Kimi/Muse
speckitext doctor --global      # per-agent installed status
speckitext doctor --json        # machine-readable compatibility report
speckitext bootstrap --project path/to/NEW-project   # per-project activation, all integrations
speckitext doctor --project path/to/project          # effective override per integration
speckitext uninstall --global   # remove exactly the installer-owned files
```

Global skill discovery, project-level activation, and effective
implementation-command precedence are different layers; see
[docs/global-installation.md](docs/global-installation.md) for what each
guarantees and what it cannot.

## Verification

```bash
python -m pip install -e ".[test]"
python -m compileall -q src
python -m pytest -q
python -m speckitext --help
speckitext doctor --json
speckitext doctor --global
git diff --check
```

Migration was verified only against synthetic legacy fixtures in disposable
directories. **No existing real project was migrated or used for migration
testing.**

## 1.1.1 corrective guarantees

- **Package freshness** is checked against the context resolved from the *current* graph (selection, dependency closure, applicable GLOBAL/SCOPED/CONDITIONAL governance, traceability/contract/verification closure, source fingerprints, compiler/schema versions, approved expansions) plus the package's own content fingerprint. A new applicable rule or changed relationship invalidates old packages; malformed/incompatible packages make `speckitext validate --package` exit nonzero.
- **Expansion** (`speckitext expand`) re-renders through the canonical compiler, records deduplicated reasons, never adds tasks as executable work, and refuses stale/corrupt packages.
- **Migration** is a durable transaction (prepared -> staged -> activating -> activated; rollback passes through rolling-back; `--recover` restores byte-exact originals after interruption). Recovery never overwrites a destination that matches neither its original nor staged hash — that is a recovery conflict requiring explicit resolution. Rollback preflights backups and destination state, refuses post-activation edits unless `--force-rollback`, and reports success only after verified restoration. Incomplete migrations block validate/compile/batch/expand/impact. Pending tasks must be implementation-ready; completed tasks remain historical traceability.
- **Bootstrap** refuses existing nonempty non-Spec-Kit directories by default, never uses `--force` on init, stops at the first failed mandatory step, and reports `partial` (nonzero exit) unless every requested integration has a verified scoped override. Doctor requires *every recorded* integration to be active and only calls tested-compatible Spec Kit versions verified.
