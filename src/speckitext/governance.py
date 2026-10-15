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


_TOKEN_RE = re.compile(r"\s*(\(|\)|,|\[|\]|==|!=|[A-Za-z0-9][\w.-]*::[A-Za-z0-9][\w-]*|[A-Za-z0-9_][\w.-]*|'[^']*'|\"[^\"]*\")")


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

    def _resolve_component(self, raw: str) -> str:
        resolver = self.ctx.get("_resolve_component")
        if resolver is None:
            return raw
        return resolver(raw)

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
        if field.startswith("_") or (field not in self.ctx and field not in ("component", "feature", "tag", "kind")):
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
            if field == "component":
                values = [self._resolve_component(v) for v in values]
            actual = self.ctx.get(field, [])
            actual_list = actual if isinstance(actual, (list, set)) else [actual]
            return any(v in actual_list for v in values)
        if op not in ("==", "!="):
            raise ConditionError(f"unsupported operator {op!r}")
        raw = self.next().strip("'\"")
        if field == "component":
            raw = self._resolve_component(raw)
        actual = self.ctx.get(field, "")
        if field == "component" and "_resolve_component" not in self.ctx \
                and isinstance(actual, (list, set)):
            actual = _ComponentSet(actual)  # legacy graph-less fallback only
        if isinstance(actual, (list, set)):
            result = raw in actual
        else:
            result = str(actual) == raw
        return result if op == "==" else not result


def evaluate_condition(expr: str, ctx: dict) -> bool:
    expr = expr.strip()
    if not expr:
        raise ConditionError("empty condition")
    # Support has_component(COMP-001) / has_component(feat::COMP-001) written
    # without spaces as a single token form.
    expr = re.sub(r"has_component\(\s*([A-Za-z0-9][\w.-]*(?:::[A-Za-z0-9][\w-]*)?)\s*\)",
                  r"component == \1", expr)
    return _Parser(_tokenize(expr), ctx).parse()


class _ComponentSet(list):
    """Graph-less fallback membership for direct evaluate_condition callers
    that supply no resolver. Production paths (validation, compilation,
    freshness, expansion) always resolve component references through
    resolve_component_ref instead, so selection coincidence never decides
    a real package."""
    def __contains__(self, item):
        if super().__contains__(item):
            return True
        if not isinstance(item, str) or "::" in item:
            return False
        return sum(1 for c in self if local_part(str(c)) == item) == 1


def resolve_component_ref(graph, ref, source_feature=""):
    """The one component-reference contract shared by SCOPED and
    CONDITIONAL governance: (canonical, None) or (None, error).

    A qualified ``feat::ID`` must exist exactly, be a component, and agree
    with its feature ownership. A bare local ID resolves inside
    ``source_feature`` when the rule has one, otherwise only when it names
    exactly one component in the whole project. Missing, wrong-kind, and
    ambiguous references are errors, never a silent non-match. Resolution
    never depends on which components happen to be selected."""
    ref = str(ref).strip()
    if not ref:
        return None, "empty component reference"
    if is_canonical(ref):
        node = graph.nodes.get(ref)
        if node is None or node.node_id != ref:
            return None, f"component reference {ref!r} does not exist"
        if node.kind != "component":
            return None, f"component reference {ref!r} resolves to {node.node_id!r} (kind {node.kind!r}), not a component"
        feat, _ = split_canonical(ref)
        if feat and node.feature_id and node.feature_id != feat:
            return None, f"component reference {ref!r} contradicts feature ownership {node.feature_id!r}"
        return ref, None
    if graph.resolver is None:
        return None, f"component reference {ref!r} cannot be resolved (no identity resolver)"
    all_cands = graph.resolver.candidates_for_local(ref)
    comp_cands = [c for c in all_cands
                  if (n := graph.nodes.get(c)) is not None and n.kind == "component"]
    if not comp_cands:
        if all_cands:
            kinds = ", ".join(sorted({graph.nodes[c].kind for c in all_cands if graph.nodes.get(c)}))
            return None, f"component reference {ref!r} resolves to a non-component entity (kind {kinds}); scope/conditions must name a component"
        return None, f"component reference {ref!r} does not exist"
    if source_feature and source_feature not in ("", "shared", "global"):
        scoped = [c for c in comp_cands if split_canonical(c)[0] == source_feature]
        if len(scoped) == 1:
            return scoped[0], None
        if len(scoped) > 1:
            return None, f"ambiguous component reference {ref!r}; candidates: {', '.join(sorted(scoped))}; qualify as <feature>::<id>"
        return None, f"component reference {ref!r} does not resolve to a component in feature {source_feature!r}; qualify a cross-feature component as <feature>::<id>"
    if len(comp_cands) == 1:
        return comp_cands[0], None
    return None, f"ambiguous component reference {ref!r}; candidates: {', '.join(sorted(comp_cands))}; qualify as <feature>::<id>"


def _component_candidates(graph, ref):
    if graph.resolver is None:
        return []
    return [c for c in graph.resolver.candidates_for_local(ref)
            if (n := graph.nodes.get(c)) is not None and n.kind == "component"]


def _resolve_scope_entry(graph, entry, rule, selected_set=None):
    """(canonical_or_None, error_or_None) for one scope entry. Selection
    never disambiguates: the shared contract decides."""
    return resolve_component_ref(graph, entry, getattr(rule, "feature_id", "") or "")


def _condition_resolver(graph, source_feature=""):
    def _resolve(raw):
        canon, err = resolve_component_ref(graph, raw, source_feature)
        if err:
            raise ConditionError(err)
        return canon
    return _resolve


def governance_diagnostics(graph) -> list:
    """Scope integrity, fail-closed: every SCOPED entry must resolve through
    the shared component contract to exactly one existing component.
    Missing, wrong-kind, ambiguous, and ownership-contradictory scopes are
    blocking errors; an invalid rule is never silently excluded."""
    diags: list = []
    for sec in sorted((s for s in graph.nodes.values() if s.kind == "constitution"),
                      key=lambda s: s.node_id):
        if str(sec.meta.get("applicability", "GLOBAL")).upper() != "SCOPED":
            continue
        for entry in [str(x) for x in (sec.meta.get("scope", []) or [])]:
            _canon, err = _resolve_scope_entry(graph, entry, sec)
            if err:
                code = "AMBIGUOUS_SCOPE" if err.startswith("ambiguous") else "UNRESOLVED_SCOPE"
                diags.append(Diagnostic(code, err.replace("component reference", "scope reference", 1),
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
                evaluate_condition(cond, {"component": [], "feature": [], "tag": [], "kind": "",
                                          "_resolve_component": _condition_resolver(
                                              graph, getattr(sec, "feature_id", "") or "")})
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
    ctx = {"component": list(selected_components),
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
            ctx["_resolve_component"] = _condition_resolver(
                graph, getattr(sec, "feature_id", "") or "")
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
