# cas_validator.py
"""
CAS validation for generated math questions.

Usage:
    ok, report = validate(question_object)

Expected schema on the question object:
    question_object["answer_spec"] = {
        "kind": "...",                 # one of: roots, value, expression_equiv, derivative,
                                       # antiderivative, limit, stationary_point, interval, system_solve
        "variables": ["x", "y"],       # optional; defaults to ["x"]
        ... kind-specific fields ...
    }

Kind-specific fields (MVP contract):
- roots:
    { "kind":"roots", "expr":"x**2 - 5*x + 6", "solutions":["2","3"], "constraints":["x!=0"]? }
- value:
    { "kind":"value", "expr":"x**2 - 5*x + 6", "at":{"x":"2"}, "value":"0" }
- expression_equiv:
    { "kind":"expression_equiv", "lhs":"(x-2)*(x-3)", "rhs":"x**2 - 5*x + 6" }
- derivative:
    { "kind":"derivative", "of":"x**3", "result":"3*x**2", "order":1 }            # symbolic form
  OR
    { "kind":"derivative", "of":"x**3", "at":{"x":"2"}, "value":"12", "order":1 } # numeric at a point
- antiderivative:
    { "kind":"antiderivative", "of":"3*x**2", "result":"x**3 + 7" }               # const ignored
- limit:
    { "kind":"limit", "expr":"(x**2-1)/(x-1)", "approaches":"1", "direction":"+" } # direction optional
- stationary_point:
    { "kind":"stationary_point", "of":"x**2", "point":{"x":"0","y":"0"}, "nature":"min" } # nature optional
- interval:
    { "kind":"interval", "condition":"x**2 - 4 >= 0",
      "intervals":[["[","-oo","-2",")"], ["(","2","oo","]"]] }  # mid-point checks
- system_solve:
    { "kind":"system_solve",
      "equations":["x + y - 3 = 0", "2*x - y = 0"],
      "solution":{"x":"1","y":"2"} }

Notes:
- Numeric tolerance is controlled by settings.CAS_NUMERIC_TOL (default 1e-6).
- Strings like "f(x)=..." or "y=..." are normalized.
- Implicit multiplication like "2x" becomes "2*x"; '^' becomes '**'.
"""

from __future__ import annotations

import math
import re
from typing import Dict, Tuple, Any, List, Optional

import sympy as sp

from config import settings
from . import utils

logger = utils.setup_logger(__name__)
TOL = getattr(settings, "CAS_NUMERIC_TOL", 1e-6)

# Known function names so we don't break them when inserting implicit '*'
_FUNCTION_NAMES = {
    "sin", "cos", "tan", "sec", "csc", "cot",
    "asin", "acos", "atan",
    "sinh", "cosh", "tanh", "asinh", "acosh", "atanh",
    "log", "ln", "exp", "sqrt", "Abs", "abs",
    "floor", "ceil",
}

# ---------- Parsing / normalization helpers ----------

def _normalize_unicode_ops(s: str) -> str:
    """Normalize common unicode math glyphs to ASCII equivalents."""
    if not s:
        return s
    rep = {
        "−": "-",  # minus
        "–": "-",  # en dash
        "—": "-",  # em dash
        "×": "*",
        "∙": "*",
        "·": "*",
        "•": "*",
        "÷": "/",
        "√": "sqrt",
        "π": "pi",
        "∞": "oo",
        "≤": "<=",
        "≥": ">=",
        "≠": "!=",
    }
    for k, v in rep.items():
        s = s.replace(k, v)
    return s


def _replace_abs_bars(s: str) -> str:
    """
    Convert |x| into Abs(x). Repeats until no bars remain (handles simple nesting).
    This is intentionally simple and covers the majority of A-level style inputs.
    """
    prev = None
    cur = s
    pat = re.compile(r"\|([^|]+)\|")
    while prev != cur:
        prev = cur
        cur = pat.sub(r"Abs(\1)", cur)
    return cur


def _insert_implicit_multiplication(s: str) -> str:
    """
    Insert '*' where it's unambiguous, without breaking function names like 'sin('.
    We avoid any letter-letter insertion to keep 'sin', 'cos', ... intact.
    """
    # number followed by variable or '('    : 2x -> 2*x, 3(x+1) -> 3*(x+1)
    s = re.sub(r"(\d)\s*([A-Za-z(])", r"\1*\2", s)
    # closing ')' followed by variable/number or '(' : (x+1)2 -> (x+1)*2, (x+1)y -> (x+1)*y, (x+1)(x+2) -> (x+1)*(x+2)
    s = re.sub(r"(\))\s*([A-Za-z0-9(])", r"\1*\2", s)
    # variable followed by number           : x2 -> x*2
    s = re.sub(r"([A-Za-z])\s*(\d)", r"\1*\2", s)

    # word before '(' — add '*' only if it's a single-letter variable; keep multi-letter function calls
    def _fix_word_paren(m: re.Match) -> str:
        word = m.group(1)
        if word in _FUNCTION_NAMES:
            return f"{word}("
        if len(word) == 1:
            return f"{word}*("
        return f"{word}("

    s = re.sub(r"\b([A-Za-z]+)\s*\(", _fix_word_paren, s)
    return s


def _normalize_expr_string(s: str) -> str:
    if s is None:
        return ""
    s = s.strip()
    s = _normalize_unicode_ops(s)

    # Strip leading labels like f(x)= ... or y = ...
    m_fx = re.match(r'^[a-zA-Z]\s*\(\s*[a-zA-Z]\s*\)\s*=\s*(.+)$', s)
    m_y  = re.match(r'^[yY]\s*=\s*(.+)$', s)
    if m_fx:
        s = m_fx.group(1).strip()
    elif m_y:
        s = m_y.group(1).strip()

    # Normal algebraic cleanups
    s = s.replace("^", "**")
    s = s.replace("ln", "log")

    # |x| → Abs(x)
    s = _replace_abs_bars(s)

    # Insert implicit '*', carefully
    s = _insert_implicit_multiplication(s)

    return s


def _symbols_from_list(vars_list: Optional[List[str]]) -> List[sp.Symbol]:
    if not vars_list:
        return [sp.Symbol("x")]
    symbols: List[sp.Symbol] = []
    for name in vars_list:
        name = (name or "").strip()
        if not name:
            continue
        symbols.append(sp.Symbol(name))
    return symbols or [sp.Symbol("x")]


def _sympify(s: str) -> sp.Expr:
    return sp.sympify(_normalize_expr_string(s))


def _to_float(val: Any) -> float:
    try:
        if isinstance(val, (int, float)):
            return float(val)
        if isinstance(val, sp.Expr):
            return float(val.evalf())
        return float(str(val))
    except Exception:
        raise


def _is_close(a: Any, b: Any, tol: float = TOL) -> bool:
    try:
        af = _to_float(a)
        bf = _to_float(b)
        if math.isinf(af) or math.isinf(bf):
            return af == bf
        return abs(af - bf) <= tol * max(1.0, max(abs(af), abs(bf)))
    except Exception:
        return False


def _subs_all(expr: sp.Expr, subs_map: Dict[str, Any]) -> sp.Expr:
    if not subs_map:
        return expr
    pairs = []
    for k, v in subs_map.items():
        try:
            pairs.append((sp.Symbol(k), _sympify(str(v))))
        except Exception:
            pairs.append((sp.Symbol(k), sp.sympify(v)))
    return expr.subs(pairs)


def _apply_constraints(constraints: Optional[List[str]], subs_map: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Evaluate relational constraints like 'x>0', 'x!=2' at provided substitution values."""
    if not constraints:
        return True, []
    failures: List[str] = []
    for c in constraints:
        try:
            rel = sp.sympify(_normalize_expr_string(str(c)))
            ok = bool(rel.subs({sp.Symbol(k): _sympify(str(v)) for k, v in subs_map.items()}))
            if not ok:
                failures.append(str(c))
        except Exception as e:
            failures.append(f"{c} (parse error: {e})")
    return len(failures) == 0, failures


def _simplify_zero(expr: sp.Expr) -> bool:
    try:
        return sp.simplify(expr) == 0
    except Exception:
        return False


# ---------- Validators ----------

def _validate_roots(spec: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    expr = _sympify(spec.get("expr", "0"))
    vars_ = _symbols_from_list(spec.get("variables"))
    if not vars_:
        return False, {"reason": "no variable"}
    x = vars_[0]

    sols = spec.get("solutions") or []
    if not isinstance(sols, list) or not sols:
        return False, {"reason": "solutions missing or empty"}

    bad: List[str] = []
    good_count = 0
    for s in sols:
        try:
            r = _sympify(str(s))
            val = expr.subs(x, r)
            if _is_close(val, 0.0):
                ok_constraints, fails = _apply_constraints(spec.get("constraints"), {"x": r})
                if ok_constraints:
                    good_count += 1
                else:
                    bad.append(f"{s} violates constraints: {fails}")
            else:
                bad.append(f"{s} not a root (f({s})={val})")
        except Exception as e:
            bad.append(f"{s} parse/eval error: {e}")

    completeness_note = "skipped"
    try:
        poly = sp.Poly(expr, x)
        if poly.total_degree() <= 4:
            real_roots = [rr for rr in sp.nroots(poly) if abs(rr.as_real_imag()[1]) <= TOL]
            completeness_note = f"expected≈{len(real_roots)} real roots by nroots"
            if len(real_roots) != len(sols):
                bad.append(f"root count differs (claimed={len(sols)}, approx_real={len(real_roots)})")
    except Exception:
        pass

    ok = (len(bad) == 0)
    return ok, {"checked": good_count, "failures": bad, "completeness": completeness_note}


def _validate_value(spec: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    expr = _sympify(spec.get("expr", "0"))
    at = spec.get("at") or {}
    value = spec.get("value", None)
    if value is None:
        return False, {"reason": "value missing"}
    try:
        got = _subs_all(expr, at)
        ok = _is_close(got, _sympify(str(value)))
        return ok, {"got": str(got), "expected": str(value)}
    except Exception as e:
        return False, {"reason": f"evaluation error: {e}"}


def _validate_expression_equiv(spec: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    lhs = spec.get("lhs") or spec.get("expr")
    rhs = spec.get("rhs") or spec.get("equiv_to") or spec.get("target")
    if not lhs or not rhs:
        return False, {"reason": "lhs/rhs missing"}
    try:
        a = _sympify(lhs)
        b = _sympify(rhs)
        if _simplify_zero(a - b):
            return True, {"method": "symbolic"}
        vars_ = sorted(list(a.free_symbols.union(b.free_symbols)), key=lambda s: s.name)
        if not vars_:
            return _is_close(a, b), {"method": "numeric-const"}
        samples = [{str(vars_[0]): v} for v in (-2, -1, 0, 1, 2)]
        ok_all = True
        for subs in samples:
            try:
                av = _subs_all(a, subs)
                bv = _subs_all(b, subs)
                if not _is_close(av, bv):
                    ok_all = False
                    break
            except Exception:
                ok_all = False
                break
        return ok_all, {"method": "numeric-samples", "vars": [str(v) for v in vars_]}
    except Exception as e:
        return False, {"reason": f"parse error: {e}"}


def _validate_derivative(spec: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    of = spec.get("of")
    order = int(spec.get("order", 1) or 1)
    if not of:
        return False, {"reason": "'of' missing"}
    try:
        f = _sympify(of)
        x = next(iter(f.free_symbols), sp.Symbol("x"))
        df = sp.diff(f, x, order)

        if "result" in spec and spec["result"] not in (None, ""):
            res = _sympify(spec["result"])
            ok = _simplify_zero(df - res)
            return ok, {"mode": "symbolic", "order": order}
        elif "at" in spec and "value" in spec:
            val = _sympify(str(spec["value"]))
            subs = {str(k): v for k, v in (spec.get("at") or {}).items()}
            got = _subs_all(df, subs)
            ok = _is_close(got, val)
            return ok, {"mode": "numeric", "order": order, "got": str(got)}
        else:
            return False, {"reason": "provide 'result' or ('at' and 'value')"}
    except Exception as e:
        return False, {"reason": f"diff error: {e}"}


def _validate_antiderivative(spec: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    of = spec.get("of")
    result = spec.get("result")
    if not of or not result:
        return False, {"reason": "'of' and 'result' required"}
    try:
        F = _sympify(result)
        f = _sympify(of)
        x = next(iter((F.free_symbols or f.free_symbols)), sp.Symbol("x"))
        ok = _simplify_zero(sp.diff(F, x) - f)
        return ok, {"note": "constant of integration ignored"}
    except Exception as e:
        return False, {"reason": f"antiderivative check failed: {e}"}


def _validate_limit(spec: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    expr = _sympify(spec.get("expr", "0"))
    a = spec.get("approaches", None)
    direction = spec.get("direction", None)  # "+", "-", or None
    if a is None:
        return False, {"reason": "'approaches' required"}
    try:
        x = next(iter(expr.free_symbols), sp.Symbol("x"))
        if isinstance(a, str) and a.lower() in {"oo", "inf", "+inf", "infinity"}:
            lim = sp.limit(expr, x, sp.oo, dir=direction or "+")
        elif isinstance(a, str) and a.lower() in {"-oo", "-inf"}:
            lim = sp.limit(expr, x, -sp.oo, dir=direction or "-")
        else:
            lim = sp.limit(expr, x, _sympify(str(a)), dir=direction or "+")
        val = spec.get("value", None)
        if val is None:
            return (getattr(lim, "is_finite", None) is True or sp.simplify(lim) in (sp.oo, -sp.oo)), {"got": str(lim)}
        ok = _is_close(lim, _sympify(str(val)))
        return ok, {"got": str(lim), "expected": str(val)}
    except Exception as e:
        return False, {"reason": f"limit error: {e}"}


def _validate_stationary_point(spec: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    of = spec.get("of")
    pt = spec.get("point") or {}
    if not of or "x" not in pt or "y" not in pt:
        return False, {"reason": "'of' and point{x,y} required"}
    try:
        f = _sympify(of)
        x = next(iter(f.free_symbols), sp.Symbol("x"))
        x0 = _sympify(str(pt["x"]))
        y0 = _sympify(str(pt["y"]))
        fprime = sp.diff(f, x)
        f2 = sp.diff(fprime, x)
        zero = _is_close(_subs_all(fprime, {"x": x0}), 0.0)
        ymatch = _is_close(_subs_all(f, {"x": x0}), y0)
        nature = spec.get("nature", None)
        nature_ok = True
        nature_msg = "n/a"
        if nature:
            s = _subs_all(f2, {"x": x0})
            if nature == "min":
                nature_ok = _to_float(s) > 0
                nature_msg = f"f''(x0)={s} > 0 required"
            elif nature == "max":
                nature_ok = _to_float(s) < 0
                nature_msg = f"f''(x0)={s} < 0 required"
            elif nature == "saddle":
                nature_ok = _is_close(s, 0.0)
                nature_msg = f"f''(x0)≈0 required"
        ok = bool(zero and ymatch and nature_ok)
        return ok, {"f'(x0)=0": zero, "f(x0)=y0": ymatch, "nature": nature_msg}
    except Exception as e:
        return False, {"reason": f"stationary point check failed: {e}"}


def _midpoint(a: float, b: float) -> float:
    return (a + b) / 2.0


def _parse_bound(s: str) -> float:
    s = str(s).strip()
    if s in {"-inf", "(-inf)", "-oo"}:
        return float("-inf")
    if s in {"inf", "(inf)", "+inf", "oo"}:
        return float("inf")
    return _to_float(_sympify(s))


def _is_lbr(x: Any) -> bool:
    return str(x) in {"[", "("}


def _is_rbr(x: Any) -> bool:
    return str(x) in {"]", ")"}


def _validate_interval(spec: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """
    Validates solution intervals for a one-variable inequality.
    Accepts 4-item form [l, a, b, r] and two 3-item shorthands:
      - [a, b, r]       (default left bracket '[')
      - [l, a, b]       (default right bracket ']')
    Bounds may be 'oo'/'-oo'.
    """
    cond_s = spec.get("condition", "")
    intervals = spec.get("intervals") or []
    if not cond_s or not intervals:
        return False, {"reason": "condition or intervals missing"}

    try:
        cond = sp.sympify(_normalize_expr_string(cond_s))
        is_rel = bool(getattr(cond, "is_Relational", False))
        is_bool = bool(getattr(cond, "is_Boolean", False))
        if not (is_rel or is_bool):
            return False, {"reason": "condition not a relational/boolean expression"}

        failures: List[str] = []
        any_ok = False

        for itv in intervals:
            if not isinstance(itv, (list, tuple)):
                failures.append(f"bad interval format (not list/tuple): {itv}")
                continue

            l = "["
            r = "]"
            a = None
            b = None

            if len(itv) == 4:
                l, a, b, r = itv
            elif len(itv) == 3:
                first, mid, last = itv
                if _is_lbr(first):         # form: [l, a, b]   -> default right bracket
                    l, a, b = first, mid, last
                    r = "]"
                elif _is_rbr(last):        # form: [a, b, r]   -> default left bracket
                    a, b, r = first, mid, last
                    l = "["
                else:                       # fallback: treat as [a, b, r] and hope 'r' is bracket-like
                    a, b, r = first, mid, last
                    l = "["
            else:
                failures.append(f"bad interval length {len(itv)}: {itv}")
                continue

            try:
                a_v = _parse_bound(a)
                b_v = _parse_bound(b)
            except Exception as e:
                failures.append(f"bound parse error: {itv} ({e})")
                continue

            if math.isinf(a_v) and math.isinf(b_v):
                failures.append("interval cannot be both -inf and +inf")
                continue

            if math.isinf(a_v):
                m = b_v - 1.0
            elif math.isinf(b_v):
                m = a_v + 1.0
            else:
                m = _midpoint(a_v, b_v)

            try:
                ok_here = bool(cond.subs({sp.Symbol("x"): m}))
                any_ok = any_ok or ok_here
                if not ok_here:
                    failures.append(f"midpoint {m} does not satisfy condition")
            except Exception as e:
                failures.append(f"midpoint eval error: {e}")

        return len(failures) == 0 and any_ok, {"failures": failures}
    except Exception as e:
        return False, {"reason": f"interval check failed: {e}"}


def _validate_system_solve(spec: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    eqs = spec.get("equations") or []
    sol = spec.get("solution") or {}
    if not eqs or not sol:
        return False, {"reason": "equations or solution missing"}
    failures: List[str] = []
    try:
        subs = {sp.Symbol(k): _sympify(str(v)) for k, v in sol.items()}
        for e in eqs:
            s = _normalize_expr_string(str(e))
            if "=" in s:
                L, R = s.split("=", 1)
                expr = _sympify(L) - _sympify(R)
            else:
                expr = _sympify(s)
            val = expr.subs(subs)
            if not _is_close(val, 0.0):
                failures.append(f"{e} -> {val} != 0")
        return len(failures) == 0, {"failures": failures}
    except Exception as e:
        return False, {"reason": f"system check failed: {e}"}


# ---------- Public API ----------

_KIND_MAP = {
    "roots": _validate_roots,
    "value": _validate_value,
    "expression_equiv": _validate_expression_equiv,
    "derivative": _validate_derivative,
    "antiderivative": _validate_antiderivative,
    "limit": _validate_limit,
    "stationary_point": _validate_stationary_point,
    "interval": _validate_interval,
    "system_solve": _validate_system_solve,
}

def validate(question_object: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """
    Validate a generated question using its answer_spec.

    Returns:
        (ok: bool, report: dict)
    The report always contains at least: {"kind": <kind>, "details": <dict> or "reason": <str>}
    """
    spec = (question_object or {}).get("answer_spec")
    if not isinstance(spec, dict):
        return False, {"kind": "unknown", "reason": "answer_spec missing or not an object"}

    kind = (spec.get("kind") or "").strip().lower()
    if kind not in _KIND_MAP:
        return False, {"kind": kind or "unknown", "reason": f"unsupported kind. supported={sorted(_KIND_MAP.keys())}"}

    try:
        ok, details = _KIND_MAP[kind](spec)
        return bool(ok), {"kind": kind, "details": details}
    except Exception as e:
        logger.error("CAS: validator error for kind '%s' — %s", kind, e)
        return False, {"kind": kind, "reason": f"internal error: {e}"}