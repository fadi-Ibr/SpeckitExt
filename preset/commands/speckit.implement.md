---
description: Implement a selected task or coherent batch from a deterministic SpeckitExt context package
---

## User Input

```text
$ARGUMENTS
```

You **MUST** consider the user input before proceeding (if not empty). The input
names the task ID(s) to implement (e.g. `T003` or `T003,T004`), or is empty to
request a suggested batch.

## Registration Self-Check (before anything else)

Run `speckitext doctor --project . --json` and confirm
`registration.<this agent>.override_active` is `true`. If it is not — the
effective speckit-implement is missing, unknown, or the upstream version, or a
project-local skill shadows this one — STOP and report that diagnostic to the
user verbatim. Never fall back to the upstream implementation workflow
(whole-document loading) on your own initiative.

## Pre-Execution Checks

**Check for extension hooks (before implementation)**:
- Check if `.specify/extensions.yml` exists in the project root.
- If it exists, read it and look for entries under the `hooks.before_implement` key.
- If the YAML cannot be parsed, tell the user (include the parser error) that no
  hooks were checked, including mandatory ones, then continue normally.
- Filter out hooks where `enabled` is explicitly `false`.
- For optional hooks, present them and let the user choose. For mandatory hooks
  (`optional: false`), emit the `EXECUTE_COMMAND: {command}` block and actually
  invoke the hook and wait for it before continuing.

**Checklists**: if `checklists/` exists under the feature directory, scan
checkbox state and report the status table. Treat checklist markers as a
read-only gate: do NOT modify checklist files, and ask before proceeding when
any checklist is incomplete.

## Outline

1. **Resolve the selection.** If the user input names task IDs, use exactly
   those. Otherwise run `speckitext batch suggest --project .` and present the
   first unblocked suggested batch for confirmation. Never silently add
   unrelated tasks to a user selection.

2. **Validate and compile (deterministic; no manual document loading).** Run:

   ```text
   speckitext validate --project .
   speckitext compile --project . --tasks <ID[,ID...]> --output .specify/context/<selection>.md
   ```

   If validation fails or compilation rejects a stale/invalid graph, STOP and
   report the diagnostics. Never work around a failed gate by reading the
   planning documents directly.

3. **Load ONLY the compiled context package** from step 2. It contains the
   selected tasks, applicable governing rules (with inclusion reasons),
   requirements, decisions, contracts, prerequisites, and verification
   criteria, each with source path, anchor, and fingerprint. Do NOT load the
   full constitution.md, plan.md, spec.md, or tasks.md, and do not read other
   features' artifacts. Whole documents appear in the package only when every
   section was legitimately required, and the package records that reason.

4. **Check staleness before editing code.** Run
   `speckitext validate --project . --package .specify/context/<selection>.md`.
   If the package is stale, recompile (step 2) instead of proceeding.

5. **Inspect the real code** named by the package's component/source hints.
   Agents may inspect source files, tests, and supporting documents when
   implementation reveals a genuine information gap. If a needed planning
   section is missing from the package, run
   `speckitext expand --project . --package .specify/context/<selection>.md --ids <ID[,ID...]> --reason "<why it was needed>"`
   rather than loading a whole planning document.

6. **Implement in dependency order** (the package orders tasks topologically).
   Completed prerequisites are context, not work. Blocked prerequisites
   (listed in the package) must be reported, not silently implemented unless
   they are part of the confirmed selection.

7. **Verify.** Run the focused checks named by the package's VER-xxx
   obligations per task, then the consolidated batch-level verification once.
   Do not run broad unrelated test suites after every individual task.

8. **Record completion safely.** Flip only the implemented tasks' checkboxes
   in tasks.md from `[ ]` to `[x]`; never renumber or reformat other tasks.
   Re-run `speckitext validate --project .` after the edit.

9. **Report** implemented task IDs, changed files, checks run and their
   results, any expansions performed (with reasons), and any blocked or
   remaining prerequisites.
