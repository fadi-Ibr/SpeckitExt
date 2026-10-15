# Multi-Agent Verification (2026-10-15, this machine)

Five distinct levels are reported per agent — never inferred from one another:
**installed** (adapter file present, hash-tracked), **discoverable** (the
agent's own tooling enumerates it), **override active** (project-level
`speckit-implement` is SpeckitExt's), **compilation functional** (scoped
packages compile in that project's layout), and **agent-driven execution**
(a real agent ran the workflow).

Environment: specify-cli 1.0.10 (uv tool), Claude Code 2.1.300, Codex 0.162.1,
Kimi Code 2.1.1, Muse Code 1.4.8. All project tests used newly created
disposable projects; no existing repository was touched.

| Level | Claude | Codex | Kimi | Muse |
|---|---|---|---|---|
| Global skill installed | Yes — `~/.claude/skills/speckitext/SKILL.md` | Yes — shared `~/.agents/skills/speckitext/SKILL.md` | Yes — `~/.kimi-code/skills/speckitext/SKILL.md` | Yes — shared `~/.agents/skills/speckitext/SKILL.md` |
| Global skill discoverable | Yes — verified in a real `claude -p` session's skill list | Yes — `codex debug prompt-input` enumerates `speckitext: SpeckitExt…` from `~/.agents/skills` | Directory convention only (no non-LLM listing command exists) | Yes — `muse skills list --source user --json` reports `speckitext` |
| Project override active | Yes — bootstrap E2E (`.claude/skills/speckit-implement` = SpeckitExt body) | Yes — bootstrap E2E (`.agents/skills/speckit-implement` = SpeckitExt body) | Yes — bootstrap E2E (`.kimi-code/skills/speckit-implement` = SpeckitExt body) | Yes — bootstrap E2E (shares `.agents/skills` with Codex; registered once, no collision) |
| Scoped compilation functional | Yes — real CLI compile in the bootstrapped layout (test_e2e_specify, test_bootstrap) | Layout verified; compilation is agent-independent (same CLI) | Layout verified; compilation is agent-independent (same CLI) | Layout verified; compilation is agent-independent (same CLI) |
| Agent-driven execution | Yes — gated real-agent E2E (tests/test_agent_authoring_e2e.py, SPECKITEXT_AGENT_E2E=1): **1 passed in 561s on 2026-10-15**; Claude authored constitution→specify→plan→tasks in sequential stage prompts, the graph validated clean, and an ID-only assignment ("Implement <first pending task ID> using SpeckitExt") executed with the compiled package excluding unrelated sections | Not executed (no separate Codex-driven run performed) | **Not executed** — provider returned 403 monthly-quota error on 2026-10-15; reported as unexecuted, not passing | Not executed as the authoring driver (no separate muse-driven run claimed) |

Notes:

- Project-local precedence: a project-local upstream `speckit-implement`
  shadows global skills. `speckitext doctor --project .` detects and reports
  this (`upstream`/`conflict`) with a remediation diagnostic; the installer
  never rewrites project files.
- Shared-directory safety: Codex and Muse consume the same
  `.agents/skills` files at both user and project level. Bootstrap registers
  once and both classifications read the same file; no duplicate or collision
  was observed.
- Global uninstall/reinstall restoration is covered by unit tests with an
  isolated home directory (owned files removed, unrelated and user-modified
  files preserved), and the live install on this machine preserved all
  pre-existing user skills (find-skills, frontend-design, playwright, .system).

## Authoritative E2E acceptance (1.1.1)

The gated real-agent test (`SPECKITEXT_AGENT_E2E=1`) selects greet work by requirement/component traceability, asserts expected source/test files exist, executes the greeting behavior and pytest, requires selected tasks done and unrelated tasks pending, and revalidates the graph. Absent files, absent tests, incomplete tasks, or a zero-exit no-op agent all fail; `tests/test_e2e_acceptance_negative.py` proves a no-op cannot pass in normal CI. Registration checks require the full scoped contract (doctor+validate+compile+expand, no broad loading); merely mentioning `speckitext compile` classifies as `partial`. Installed/discoverable/active-override/execution-verified remain distinct levels; no Kimi live execution is claimed without provider access.
