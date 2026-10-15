# Global Installation and Multi-Agent Model

SpeckitExt has four distinct layers. Confusing them produces false claims, so
each is reported separately by `speckitext doctor`:

| Layer | What it is | Command |
|---|---|---|
| Global runtime | The installed `speckitext` Python package + CLI (one canonical copy) | `python -m pip install -e ".[test]"` from a SpeckitExt checkout |
| User-level skill discovery | One lightweight `speckitext` SKILL.md adapter per agent skill directory, delegating to the runtime | `speckitext install --global` |
| Project-level activation | Native Spec Kit preset + extension installed into ONE new project, registered per integration | `speckitext bootstrap --project <path>` |
| Effective override precedence | Which `speckit-implement` body an agent will actually load in that project | `speckitext doctor --project .` |

## Global install

```bash
speckitext install --global     # writes only installer-owned, hash-tracked files
speckitext doctor --global      # per-agent installed/discoverable status
speckitext uninstall --global   # removes exactly the owned files (keeps user-modified ones unless --force)
```

Verified user skill directories (inspected on this machine, 2026-10-15):

| Agent | Directory | Notes |
|---|---|---|
| Claude Code | `~/.claude/skills/` | Existing user skills preserved |
| Codex CLI | `~/.agents/skills/` | Codex enumerates skills from here (observed in `codex debug prompt-input` for pre-existing skills); `~/.codex/skills` is its legacy home and is not written |
| Kimi Code | `~/.kimi-code/skills/` | Kimi also accepts `--skills-dir` per session |
| Muse Code | `~/.agents/skills/` | Verified: `muse skills list --source user` reports paths under `$HOME/.agents/skills` |

Codex and Muse therefore share one physical adapter file; the installer
writes it once and doctor reports it for both agents. Installation is
idempotent, refuses to overwrite unowned files (name collisions) or
user-modified owned files, and tracks every written file with its SHA-256 in
`~/.speckitext/install.json`. Uninstall removes only owned, unmodified files
and restores nothing it did not write — unrelated skills are never touched.

Discovery vs override: a user-level skill makes SpeckitExt *discoverable* in
new sessions, but a project-local skill of the same name takes precedence in
every supported agent. A project-local upstream `speckit-implement` therefore
shadows the global skill; `speckitext doctor --project .` detects this and
reports `upstream`/`conflict` with an explicit diagnostic instead of claiming
success.

## Project activation (new projects only)

```bash
speckitext bootstrap --project path/to/new-project
speckitext bootstrap --project path/to/new-project --integrations claude,codex
```

Bootstrap uses only upstream APIs, in the order verified against specify-cli
1.0.10: `specify init` (first integration), `integration install` for the rest
(`--force` fallback where upstream requires it), `preset add --dev`,
`extension add --dev`, then `integration use <each>` to re-register the preset
and extension commands for every integration (upstream registers overrides
only into the current default integration), restoring the original default at
the end. It then verifies the effective `speckit-implement` body per
integration and writes `.specify/speckitext.json`.

Bootstrap refuses established projects (authored specs, existing SpeckitExt
installation, prior bootstrap). Existing Spec Kit projects still require the
full, all-or-nothing migration (`speckitext migrate --dry-run` review, then
`--apply`) before entering traceability mode; bootstrap never migrates.

## What cannot be guaranteed

- Agent skill enumeration may be cached by a running agent process; a freshly
  installed skill is guaranteed on disk in the verified directory, and each
  agent picks it up on its next session/skill refresh. SpeckitExt reports
  `installed` separately from CLI-verified `discoverable` and from
  project-level `override_active`; only the levels actually observed are
  claimed.
- Codex has no non-destructive user-skill listing command; its discovery is
  verified by directory convention plus observed skill enumeration in
  `codex debug prompt-input`, not by a dedicated list API.

## Installer integrity (1.1.1)

A corrupt `~/.speckitext/install.json` is preserved and reported (`manifest_corrupt`); install/uninstall refuse to act rather than discarding ownership and replacing or removing files destructively. Bootstrap into an existing nonempty directory requires a new/empty directory, an empty Git repository, an established Spec Kit shape, or explicit `--allow-existing` authorization.
