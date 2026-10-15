# Examples

A small end-to-end example project lives in [`project/`](project/): a
structured constitution, a linked specification and plan, and three related
implementation tasks (plus two unrelated ones that must be excluded).

From the repository root, after `python -m pip install -e ".[test]"`:

```bash
speckitext validate --project examples/project
speckitext batch suggest --project examples/project
speckitext compile --project examples/project --tasks T002,T003 --output examples/compiled-batch.md
speckitext compile --project examples/project --tasks T002 --output examples/compiled-single.md
speckitext impact --project examples/project --ids FR-001
```

`examples/compiled-single.md` and `examples/compiled-batch.md` are generated
outputs of the two compile commands above (regenerate them the same way; do
not hand-edit). `examples/migration/` shows a synthetic legacy fixture, the
dry-run diff (metadata blocks added from textual evidence only), and the
ambiguity finding produced when a task has no evidence-based link.
