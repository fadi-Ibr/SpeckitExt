"""Governance applicability: GLOBAL / SCOPED / CONDITIONAL.

Conditions are a small deterministic expression language, evaluated without
an LLM and without keyword similarity:

    component == COMP-001      feature == 001-auth
    tag in [auth, security]    has_component(COMP-001)
    <expr> and|or <expr>       not <expr>      ( <expr> )

An unparsable or unresolvable condition is a validation error (UNRESOLVED_CONDITION),
never a silent false.
"""
from __future__ import annotations

import re

from .graph import Graph
from .schema import Diagnostic


class ConditionError(ValueError):
    pass


_TOKEN_RE = re.compile(r"\s*(\(|\)|,|\[|\]|==|!=|[A-Za-z_][\w.-]*|'[^']*'|\"[^\"]*\")")


def _tokenize(expr: str) -> list[str]:
    tokens, pos = [], 0
    while pos < len(expr):
        m = _TOKEN_RE.match(expr, pos)
        if not m:
            raise ConditionError(f"unsupported token at {expr[pos:pos + 12]!r}")
        tokens.append(m.group(1)); pos = m.end()
    return tokens


class _Parser:
    def __init__(self, tokens: list[str], ctx: dict):
        self.toks, self.i, self.ctx = tokens, 0, ctx

    def peek(self) -> str | None:
        return self.toks[self.i] if self.i < len(self.toks) else None

    def next(self) -> str:
        tok = self.peek(); self.i += 1
        return tok or ""

    def parse(self) -> bool:
        value = self.parse_or()
        if self.i != len(self.toks):
            raise ConditionError("trailing tokens in condition")
        return value

    def parse_or(self) -> bool:
        value = self.parse_and()
        while (self.peek() or "").lower() == "or":
            self.next(); value = self.parse_and() or value
        return value

    def parse_and(self) -> bool:
        value = self.parse_not()
        while (self.peek() or "").lower() == "and":
            self.next(); value = self.parse_not() and value
        return value

    def parse_not(self) -> bool:
        if (self.peek() or "").lower() == "not":
            self.next(); return not self.parse_not()
        return self.parse_atom()

    def parse_atom(self) -> bool:
        tok = self.next()
        if tok == "(":
            value = self.parse_or()
            if self.next() != ")":
                raise ConditionError("missing closing parenthesis")
            return value
        if tok.lower().startswith("has_component"):
            # has_component(COMP-001) arrives as separate tokens.
            raise ConditionError("has_component must be written has_component(COMP-001) without spaces")
        if tok.startswith("has_component("):
            raise ConditionError("malformed has_component")
        # field op value
        field = tok
        if field not in self.ctx and field not in ("component", "feature", "tag", "kind"):
            raise ConditionError(f"unknown condition field {field!r}")
        op = self.next()
        if op == "in":
            if self.next() != "[":
                raise ConditionError("expected '[' after 'in'")
            values = []
            while True:
                v = self.next()
                if v == "]":
                    break
                if v != ",":
                    values.append(v.strip("'\""))
            actual = self.ctx.get(field, [])
            actual_list = actual if isinstance(actual, (list, set)) else [actual]
            return any(v in actual_list for v in values)
        if op not in ("==", "!="):
            raise ConditionError(f"unsupported operator {op!r}")
        raw = self.next().strip("'\"")
        actual = self.ctx.get(field, "")
        if isinstance(actual, (list, set)):
            result = raw in actual
        else:
            result = str(actual) == raw
        return result if op == "==" else not result


def evaluate_condition(expr: str, ctx: dict) -> bool:
    expr = expr.strip()
    if not expr:
        raise ConditionError("empty condition")
    # Support has_component(COMP-001) written without spaces as a single token form.
    expr = re.sub(r"has_component\(\s*([A-Za-z0-9-]+)\s*\)",
                  r"component == \1", expr)
    return _Parser(_tokenize(expr), ctx).parse()


def unresolved_conditions(graph: Graph) -> list[Diagnostic]:
    diags: list[Diagnostic] = []
    for sec in graph.nodes.values():
        if sec.kind != "constitution":
            continue
        if str(sec.meta.get("applicability", "GLOBAL")).upper() == "CONDITIONAL":
            cond = str(sec.meta.get("condition", "")).strip()
            if not cond:
                diags.append(Diagnostic("UNRESOLVED_CONDITION",
                    "CONDITIONAL rule declares no condition", sec.node_id, sec.path))
                continue
            try:
                evaluate_condition(cond, {"component": [], "feature": "", "tag": [], "kind": ""})
            except ConditionError as exc:
                diags.append(Diagnostic("UNRESOLVED_CONDITION",
                    f"condition cannot be evaluated deterministically: {exc}",
                    sec.node_id, sec.path))
    return diags


def resolve_governance(graph: Graph, selected_components: list[str],
                       features: list[str], tags: list[str]) -> tuple[list[dict], list[dict]]:
    """Return (included, excluded) traces for every constitution rule."""
    included: list[dict] = []
    excluded: list[dict] = []
    ctx = {"component": list(selected_components), "feature": features[0] if features else "",
           "features": list(features), "tag": list(tags), "kind": "task"}
    ctx["feature"] = list(features)  # feature comparisons accept any selected feature
    for sec in sorted((s for s in graph.nodes.values() if s.kind == "constitution"),
                      key=lambda s: s.node_id):
        applicability = str(sec.meta.get("applicability", "GLOBAL")).upper()
        if applicability == "GLOBAL":
            included.append({"id": sec.node_id, "applicability": "GLOBAL",
                             "reason": "GLOBAL: always included"})
        elif applicability == "SCOPED":
            scope = [str(x) for x in (sec.meta.get("scope", []) or [])]
            hit = [c for c in scope if c in selected_components]
            if hit:
                included.append({"id": sec.node_id, "applicability": "SCOPED",
                                 "reason": f"SCOPED: scope intersects {', '.join(hit)}"})
            else:
                excluded.append({"id": sec.node_id, "applicability": "SCOPED",
                                 "reason": f"scope {scope} does not intersect selected components {selected_components}"})
        elif applicability == "CONDITIONAL":
            cond = str(sec.meta.get("condition", "")).strip()
            try:
                result = evaluate_condition(cond, ctx)
            except ConditionError as exc:
                excluded.append({"id": sec.node_id, "applicability": "CONDITIONAL",
                                 "reason": f"UNRESOLVED: {exc}"})
                continue
            if result:
                included.append({"id": sec.node_id, "applicability": "CONDITIONAL",
                                 "reason": f"CONDITIONAL: condition true: {cond}"})
            else:
                excluded.append({"id": sec.node_id, "applicability": "CONDITIONAL",
                                 "reason": f"condition false: {cond}"})
        else:
            excluded.append({"id": sec.node_id, "applicability": applicability,
                             "reason": "unknown applicability category"})
    return included, excluded
