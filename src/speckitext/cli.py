"""speckitext CLI: validate | compile | batch suggest | impact | expand | migrate."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .batch import suggest_batches
from .compiler import CompileError, compile_context, expand_context, package_staleness, read_package_meta
from .graph import Graph
from .impact import impact_for_files, impact_for_ids
from .migration import Migration
from .validate import is_valid, validate_all, validate_graph


def cmd_doctor(args) -> int:
    from .compat import agent_info, project_metadata, speckitext_info, specify_info
    from .install import global_status
    from .registration import registration_status
    report: dict = {"speckitext": speckitext_info(), "specify": specify_info(),
                    "agents": agent_info()}
    healthy = report["specify"]["classification"] in ("tested-compatible", "untested")
    if args.global_scope:
        report["global"] = global_status(Path(args.home) if args.home else None)
    if args.project:
        report["project"] = project_metadata(Path(args.project))
        report["registration"] = registration_status(Path(args.project))["integrations"]
        if not any(v["override_active"] for v in report["registration"].values()):
            healthy = False
    report["healthy"] = healthy
    if args.json:
        _print(report, True)
    else:
        s = report["specify"]
        print(f"speckitext {report['speckitext']['package_version']} "
              f"(schema {report['speckitext']['schema_version']}, "
              f"compiler {report['speckitext']['compiler_version']})")
        print(f"specify: {s['distribution_version'] or 'not found'} "
              f"[{s['classification']}] via {s['active_executable'] or '-'} "
              f"({s['installation_source']})")
        print(f"tested specify versions: {', '.join(s['tested_versions'])}; "
              f"upstream reference {s['upstream_reference']['commit'][:12]} "
              f"(source {s['upstream_reference']['source_version']})")
        for key, a in report["agents"].items():
            print(f"agent {key}: {'available ' + str(a['version']) if a['available'] else 'NOT FOUND'}")
        if "global" in report:
            for key, g in report["global"]["agents"].items():
                print(f"global {key}: skill {'installed' if g['installed'] else 'not installed'} "
                      f"at {g['skill_file']}")
        if "registration" in report:
            for key, r in report["registration"].items():
                print(f"registration {key}: {r['state']} — {r['diagnostic']}")
        print("status:", "OK" if healthy else "ATTENTION (see diagnostics)")
    return 0 if healthy else 1


def cmd_install(args) -> int:
    from .install import install_global
    result = install_global(Path(args.home) if args.home else None, force=args.force)
    _print(result, True)
    return 0 if result["status"] == "installed" else 1


def cmd_uninstall(args) -> int:
    from .install import uninstall_global
    result = uninstall_global(Path(args.home) if args.home else None, force=args.force)
    _print(result, True)
    return 0 if result["status"] == "uninstalled" else 1


def cmd_bootstrap(args) -> int:
    from .bootstrap import DEFAULT_INTEGRATIONS, bootstrap_project
    integrations = tuple(x.strip() for x in args.integrations.split(",") if x.strip()) \
        if args.integrations else DEFAULT_INTEGRATIONS
    try:
        result = bootstrap_project(Path(args.project), integrations,
                                   args.preset_dir, args.extension_dir)
    except (ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr); return 2
    _print(result, True)
    return 0 if result["status"].startswith("bootstrapped") else 1


def _graph(args) -> Graph:
    return Graph.build(Path(args.project))


def _print(data, as_json: bool) -> None:
    print(json.dumps(data, indent=2, sort_keys=True) if as_json else data
          if isinstance(data, str) else json.dumps(data, indent=2, sort_keys=True))


def cmd_validate(args) -> int:
    graph = _graph(args)
    diags = validate_graph(graph) if args.graph_only else validate_all(graph)
    payload = {"project": str(args.project), "nodes": len(graph.nodes),
               "valid": is_valid(diags), "diagnostics": [d.to_dict() for d in diags]}
    if args.package:
        try:
            stale = package_staleness(graph, Path(args.package))
            payload["package_stale"] = stale
            payload["package_fresh"] = not stale
        except CompileError as exc:
            payload["package_error"] = str(exc)
    _print(payload, True)
    return 0 if payload["valid"] and payload.get("package_fresh", True) else 1


def cmd_compile(args) -> int:
    graph = _graph(args)
    ids = [x.strip() for x in args.tasks.split(",") if x.strip()]
    try:
        result = compile_context(graph, Path(args.project), ids)
    except CompileError as exc:
        print(f"error: {exc}", file=sys.stderr); return 1
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(result["text"], encoding="utf-8")
    print(json.dumps({"output": str(out), "selected": ids,
                      "included": result["meta"]["included_ids"],
                      "blocked_prerequisites": result["blocked"],
                      "package_fingerprint": result["meta"]["package_fingerprint"],
                      "chars": len(result["text"])}, indent=2))
    return 0


def cmd_batch(args) -> int:
    graph = _graph(args)
    diags = validate_all(graph)
    if not is_valid(diags):
        print("error: graph not implementation-ready; run `speckitext validate` for diagnostics", file=sys.stderr)
        return 1
    batches = suggest_batches(graph, max_tasks=args.max_tasks,
                              max_context_chars=args.max_context_chars)
    _print({"batches": batches}, True)
    return 0


def cmd_impact(args) -> int:
    graph = _graph(args)
    if args.files:
        result = impact_for_files(graph, Path(args.project),
                                  [x.strip() for x in args.files.split(",") if x.strip()])
    else:
        ids = [x.strip() for x in (args.ids or "").split(",") if x.strip()]
        if not ids:
            print("error: impact requires --ids or --files", file=sys.stderr); return 2
        result = impact_for_ids(graph, ids)
    _print(result, True)
    return 0


def cmd_expand(args) -> int:
    graph = _graph(args)
    ids = [x.strip() for x in args.ids.split(",") if x.strip()]
    try:
        result = expand_context(graph, Path(args.project), Path(args.package), ids,
                                args.reason)
    except CompileError as exc:
        print(f"error: {exc}", file=sys.stderr); return 1
    out = Path(args.output or args.package)
    out.write_text(result["text"], encoding="utf-8")
    print(json.dumps({"output": str(out), "expanded": ids, "reason": args.reason}, indent=2))
    return 0


def cmd_migrate(args) -> int:
    mig = Migration(Path(args.project))
    if args.dry_run:
        plan = mig.plan()
        _print({"mode": "dry-run", "already_migrated": plan["already_migrated"],
                "inventory": plan["inventory"], "findings": plan["findings"],
                "files_would_change": sorted(plan["transforms"])}, True)
        return 0 if not plan["findings"] else 1
    if args.rollback:
        result = mig.rollback(args.txn)
        _print(result, True)
        return 0 if result["status"] in ("rolled-back",) else 1
    result = mig.apply(fail_after=args.fail_after)
    _print(result, True)
    return 0 if result["status"] in ("activated", "noop") else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="speckitext",
                                description="Traceability-aware scoped context for Spec Kit")
    p.add_argument("--version", action="version", version=f"speckitext {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    v = sub.add_parser("validate", help="validate the traceability graph")
    v.add_argument("--project", required=True)
    v.add_argument("--package", help="also check a compiled package for staleness")
    v.add_argument("--graph-only", action="store_true",
                   help="graph integrity only; skip implementation-readiness checks")
    v.set_defaults(fn=cmd_validate)

    c = sub.add_parser("compile", help="compile a task/batch-scoped context package")
    c.add_argument("--project", required=True)
    c.add_argument("--tasks", required=True, help="comma-separated task IDs")
    c.add_argument("--output", required=True)
    c.set_defaults(fn=cmd_compile)

    b = sub.add_parser("batch", help="batch planning")
    bsub = b.add_subparsers(dest="batch_command", required=True)
    bs = bsub.add_parser("suggest", help="suggest coherent batches")
    bs.add_argument("--project", required=True)
    bs.add_argument("--max-tasks", type=int, default=5)
    bs.add_argument("--max-context-chars", type=int, default=60000)
    bs.set_defaults(fn=cmd_batch)

    im = sub.add_parser("impact", help="change-impact analysis")
    im.add_argument("--project", required=True)
    im.add_argument("--ids", help="comma-separated changed node IDs")
    im.add_argument("--files", help="comma-separated changed project-relative files")
    im.set_defaults(fn=cmd_impact)

    ex = sub.add_parser("expand", help="deterministically expand a context package")
    ex.add_argument("--project", required=True)
    ex.add_argument("--package", required=True)
    ex.add_argument("--ids", required=True, help="comma-separated section IDs to add")
    ex.add_argument("--reason", default="manual expansion during implementation")
    ex.add_argument("--output", help="defaults to overwriting --package")
    ex.set_defaults(fn=cmd_expand)

    mg = sub.add_parser("migrate", help="full all-or-nothing migration of a legacy project")
    mg.add_argument("--project", required=True)
    mg.add_argument("--dry-run", action="store_true")
    mg.add_argument("--apply", action="store_true")
    mg.add_argument("--rollback", action="store_true")
    mg.add_argument("--txn", help="transaction id for rollback")
    mg.add_argument("--fail-after", type=int, help=argparse.SUPPRESS)
    mg.set_defaults(fn=cmd_migrate)

    doc = sub.add_parser("doctor", help="compatibility and registration diagnosis")
    doc.add_argument("--json", action="store_true")
    doc.add_argument("--global", dest="global_scope", action="store_true",
                     help="include user-level (global) installation status")
    doc.add_argument("--project", help="include project registration/metadata status")
    doc.add_argument("--home", help=argparse.SUPPRESS)
    doc.set_defaults(fn=cmd_doctor)

    ins = sub.add_parser("install", help="user-level (global) SpeckitExt skill installation")
    ins.add_argument("--global", dest="global_scope", action="store_true", required=True)
    ins.add_argument("--force", action="store_true")
    ins.add_argument("--home", help=argparse.SUPPRESS)
    ins.set_defaults(fn=cmd_install)

    un = sub.add_parser("uninstall", help="remove user-level SpeckitExt-owned skill files")
    un.add_argument("--global", dest="global_scope", action="store_true", required=True)
    un.add_argument("--force", action="store_true")
    un.add_argument("--home", help=argparse.SUPPRESS)
    un.set_defaults(fn=cmd_uninstall)

    bo = sub.add_parser("bootstrap", help="activate SpeckitExt in a NEW Spec Kit project")
    bo.add_argument("--project", required=True)
    bo.add_argument("--integrations", help="comma-separated: claude,codex,kimi,muse")
    bo.add_argument("--preset-dir")
    bo.add_argument("--extension-dir")
    bo.set_defaults(fn=cmd_bootstrap)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if getattr(args, "command", None) == "migrate" and not (args.dry_run or args.apply or args.rollback):
        print("error: migrate requires one of --dry-run, --apply, --rollback", file=sys.stderr)
        return 2
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
