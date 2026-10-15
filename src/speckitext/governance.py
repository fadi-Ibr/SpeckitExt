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
from .identity import is_canonical, split_canonical
from .schema import Diagnostic, local_part


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


class _ComponentSet(list):
    """Selected canonical components with canonical-aware membership.

    Exact canonical membership always matches. A bare local ID matches only
    when exactly one selected component carries that local ID (unambiguous
    in the applicable selection context); otherwise it matches nothing, so
    a local name cannot leak across features."""
    def __contains__(self, item):
        if super().__contains__(item):
            return True
        if not isinstance(item, str) or "::" in item:
            return False
        return sum(1 for c in self if local_part(str(c)) == item) == 1


def _component_candidates(graph, ref):
    if graph.resolver is None:
        return []
    return [c for c in graph.resolver.candidates_for_local(ref)
            if c in graph.nodes and graph.nodes[c].kind == "component"]


def _resolve_scope_entry(graph, entry, rule, selected_set):
    """(canonical_or_None, error_or_None) for one scope entry."""
    entry = str(entry).strip()
    if is_canonical(entry):
        if entry not in graph.nodes:
            return None, f"scope reference {entry!r} does not exist"
        return entry, None
    cands = _component_candidates(graph, entry)
    if not cands:
        return None, f"scope reference {entry!r} does not exist"
    rule_feat = getattr(rule, "feature_id", "") or ""
    if rule_feat and rule_feat not in ("", "shared", "global"):
        scoped = [c for c in cands if split_canonical(c)[0] == rule_feat]
        if len(scoped) == 1:
            return scoped[0], None
        if len(scoped) > 1:
            return None, f"ambiguous scope reference {entry!r}; candidates: {', '.join(sorted(scoped))}; qualify as <feature>::<id>"
    selected = [c for c in cands if c in selected_set]
    if len(cands) == 1:
        return cands[0], None
    if len(selected) == 1:
        return selected[0], None
    if len(selected) > 1:
        return None, f"ambiguous scope reference {entry!r}; candidates: {', '.join(sorted(selected))}; qualify as <feature>::<id>"
    # Not selected, but globally ambiguous: inclusion is a non-hit; validation
    # (governance_diagnostics) reports the ambiguity as an error.
    return None, None


def governance_diagnostics(graph) -> list:
    """Scope integrity: qualified scopes must exist exactly; unqualified
    scopes must be unambiguous in the project (a global constitution rule
    has no feature context to disambiguate a repeated local ID)."""
    diags: list = []
    for sec in sorted((s for s in graph.nodes.values() if s.kind == "constitution"),
                      key=lambda s: s.node_id):
        if str(sec.meta.get("applicability", "GLOBAL")).upper() != "SCOPED":
            continue
        for entry in [str(x) for x in (sec.meta.get("scope", []) or [])]:
            if is_canonical(entry):
                if entry not in graph.nodes:
                    diags.append(Diagnostic("UNRESOLVED_SCOPE",
                        f"scope reference {entry!r} does not exist; qualify an existing component as <feature>::<id>",
                        sec.node_id, sec.path))
                continue
            cands = _component_candidates(graph, entry)
            if not cands:
                # A bare local scope naming no existing component is a
                # visible warning (the rule can never apply), not a silent
                # pass; an explicitly qualified missing scope is an error
                # above because its intended entity is unambiguous.
                diags.append(Diagnostic("UNRESOLVED_SCOPE",
                    f"scope reference {entry!r} does not exist", sec.node_id, sec.path,
                    severity="warning"))
                continue
            rule_feat = getattr(sec, "feature_id", "") or ""
            pool = cands
            if rule_feat and rule_feat not in ("", "shared", "global"):
                scoped = [c for c in cands if split_canonical(c)[0] == rule_feat]
                if len(scoped) == 1:
                    continue
                pool = scoped or cands
            if len(pool) > 1:
                diags.append(Diagnostic("AMBIGUOUS_SCOPE",
                    f"unqualified scope reference {entry!r} is ambiguous; candidates: {', '.join(sorted(pool))}; qualify as <feature>::<id>",
                    sec.node_id, sec.path))
    return diags


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
    _comps = _ComponentSet(selected_components)
    ctx = {"component": _comps, "feature": features[0] if features else "",
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
            _sel = set(selected_components)
            hit: list[str] = []
            errors: list[str] = []
            for entry in scope:
                canon, err = _resolve_scope_entry(graph, entry, sec, _sel)
                if err:
                    errors.append(err)
                elif canon is not None and canon in _sel:
                    hit.append(entry)
            if errors:
                excluded.append({"id": sec.node_id, "applicability": "SCOPED",
                                 "reason": f"UNRESOLVED: {'; '.join(errors)}"})
            elif hit:
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
