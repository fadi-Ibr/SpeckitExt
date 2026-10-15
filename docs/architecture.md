# SpeckitExt Architecture

Upstream baseline verified 2026-10-15: github/spec-kit `main` at
`3238fa9285694dc539aeb9829b337bfd6aed7317`, package version `1.2.1.dev0`
(pyproject.toml); locally installed `specify` CLI is 1.0.10. Preset/extension
contracts below were confirmed against upstream `presets/README.md`,
`presets/ARCHITECTURE.md`, `presets/scaffold/preset.yml`,
`extensions/EXTENSION-DEVELOPMENT-GUIDE.md`,
`extensions/EXTENSION-API-REFERENCE.md`, `extensions/agent-context/extension.yml`,
and `bundles/bugfix/bundle.yml`, not from older documentation alone.

## Components

| Component | Path | Role |
|---|---|---|
| Traceability preset | `preset/` | Templates + command overrides for constitution→implement |
| Context extension | `extension/` | Agent-facing `speckit.traceability.*` commands + `after_tasks` gate |
| Joint bundle | `bundle/bundle.yml` | One-shot joint install where the catalog resolves both components |
| Compiler package | `src/speckitext/` | Deterministic engine and `speckitext` CLI (Python ≥3.11, stdlib only) |

## Module map (`src/speckitext/`)

| Module | Contract |
|---|---|
| `schema.py` | Versioned ID namespaces, typed relations and direction rules, diagnostics |
| `parsing.py` | Markdown sections, `<!-- speckitext -->` metadata, bullet IDs, task checkboxes; resolves an ID to file, anchor, line range, content |
| `project.py` | Canonical Spec Kit artifact discovery (`.specify/memory`, `specs/*/…`) |
| `graph.py` | Node/edge graph, dependency closure, topological order, cycle detection, reverse dependents |
| `governance.py` | GLOBAL/SCOPED/CONDITIONAL applicability with a deterministic condition evaluator; explainable include/exclude traces |
| `validate.py` | All graph gates; any `error` diagnostic makes the graph not implementation-ready |
| `fingerprint.py` | SHA-256 source revision fingerprints over normalized section text |
| `compiler.py` | Scoped context compilation, package provenance/staleness, deterministic expansion |
| `batch.py` | Dependency-aware coherent batch planner |
| `impact.py` | Reverse-closure change-impact analysis |
| `migration.py` | Full all-or-nothing migration transactions (staging, journal, activation, rollback) |
| `cli.py` | `speckitext` CLI adapter (argparse; no LLM, no network, no embeddings) |

Canonical data ownership: the authored Markdown artifacts remain the only
source of truth. The graph and every context package are derived, reproducible
views; packages embed per-section fingerprints so staleness is detectable
without trusting any stored index. No database, daemon, or vector store.

## ID and relation schema

See `schema.py` for the normative table. IDs (`CON/FR/SC/DEC/COMP/CTR/DM/T/VER/RES`)
are stable: completion flips a task checkbox only; insertions append new IDs;
clarifications edit text in place under the same ID. Relations are typed and
direction-checked (`governed_by`, `satisfies`, `implements`, `depends_on`,
`constrained_by`, `affects_component`, `verified_by`).

## Context compilation contract

`compile` validates the graph first and refuses invalid/stale input. The
package contains, in deterministic kind order: applicable governing rules
(GLOBAL always; SCOPED on component intersection; CONDITIONAL on a
deterministically evaluated condition), linked requirements, decisions,
components, contracts, data-model/research sections, verification obligations,
prerequisite tasks (marked completed vs blocked), and the selected tasks in
topological order. Shared sections are deduplicated. Unrelated sections are
never included; a whole document is included only when every section is
required, and the provenance table records the reason per section. Package
metadata (selected IDs, fingerprints, inclusion reasons, compiler/schema
versions, validation status) is embedded as a JSON HTML comment, making
packages auditable and staleness-checkable via
`validate --package`.

## Batch algorithm

Ready tasks (dependencies done or co-scheduled) are unioned only when they
share a traceability target (requirement, decision, component) or a dependency
edge. Groups are topologically ordered, split deterministically at
`--max-tasks`/`--max-context-chars`, and reported with grouping reasons,
shared context, and `blocked_by` external prerequisites. Unrelated tasks are
never merged to fill capacity. User-selected task lists are validated and
ordered, never silently extended.

## Migration transaction architecture

`migrate --apply` builds a transaction under `.speckitext/migrations/<txn>/`
with byte-exact `backup/` copies and fully transformed `staged/` copies of the
complete artifact inventory. The staged tree must pass full graph validation
before activation; findings (relationships without textual evidence) refuse
activation outright — migration never fabricates history. Activation replaces
files one by one via temp-file + `os.replace`, journaling each step in
`journal.json`; any failure restores every touched file from backup and marks
the transaction `failed`. `--rollback` restores an activated transaction.
Re-running `--apply` on a migrated, valid project is a no-op. There is no
partial or gradual mode, and scoped implementation stays gated on validation.

## Readiness, registration, compatibility, deployment (1.1.0)

- `readiness.py` adds implementation-readiness validation on top of graph
  integrity: every task needs `Objective:`/`Scope:`/`Accept:` lines, no
  unresolved placeholders, and a `verified_by` target naming an executable
  check. `validate` and `compile` enforce graph + readiness; migration's
  staged gate intentionally remains graph-only (readiness is then enforced at
  validate/compile time). Deterministic checks reject mechanical failures;
  semantic specificity remains an authoring obligation in the tasks command.
- `registration.py` classifies the *actually registered* `speckit-implement`
  per integration (speckitext / upstream / unknown / missing / conflict) from
  the files an agent will load, including project-local shadowing detection.
  The implementation command self-checks via doctor and stops rather than
  falling back to upstream's broad-loading outline.
- `compat.py` powers `speckitext doctor`: tested-compatible / untested /
  unsupported / unknown Spec Kit classification derived from actual
  integration tests (never from the manifest range), multi-executable
  detection, agent CLI inventory, and per-project metadata from
  `.specify/speckitext.json`. See docs/compatibility.md.
- `install.py` is the user-level installer: one canonical runtime plus
  hash-tracked SKILL.md adapters in verified per-agent skill directories
  (Codex and Muse share `~/.agents/skills`). It never overwrites unowned or
  user-modified files. See docs/global-installation.md.
- `bootstrap.py` activates SpeckitExt in NEW projects through upstream APIs
  only, cycling `integration use` so every requested integration receives the
  registered override, and refuses established projects.

## Compatibility and security

- Uses only upstream-supported preset composition (`wrap` with
  `{CORE_TEMPLATE}` for planning commands, `replace` for `speckit.implement`)
  and extension command/hook registration; no fork, no custom agent framework.
- Agent portability comes from upstream command registration, not hardcoded
  per-agent syntax.
- Compiler is deterministic, offline, and stdlib-only; condition evaluation is
  a small parser (no `eval`), and activation writes are journaled and
  reversible. Paths are normalized to POSIX form for Windows/POSIX parity.
- Constitution handling follows upstream: installing the preset never rewrites
  an authored `.specify/memory/constitution.md`; the structured template only
  seeds/composes at constitution-authoring time.

## Corrective contracts (1.1.1)

Freshness and compilation share `resolve_inclusion()` in `compiler.py`; do not duplicate graph-selection logic elsewhere. Expansion is compilation with approved non-task `extra_ids`, rendered once. Migration journal schema 2 records per-file backup/staged SHA-256 hashes and fsyncs journal advances; recovery reconciles by hash because a crash can land between replacement and journal update. Filesystem replacement is not multi-file atomic -- recoverable logical atomicity plus blocking partial state is the contract. Readiness applies to pending tasks only; done tasks are historical graph records.
