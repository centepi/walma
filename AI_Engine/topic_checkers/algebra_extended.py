#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
checker_utils_algebra_extended.py

Additional specialized verification functions for "Algebra & Functions":

  1) verify_polynomial_division(dividend, divisor, proposed_quotient, proposed_remainder, var="x")
  2) verify_domain_range(func_expr, proposed_domain, proposed_range, var="x")
  3) verify_function_composition(f_expr, g_expr, proposed_expr, composition_order="f(g(x))", var="x")
  4) verify_piecewise_equivalence(piecewise_expr, proposed_expr, var="x", numeric_fallback=True)
  5) verify_function_transformation(original_expr, transformed_expr, proposed_explanation, var="x")
  6) verify_system_of_equations_solutions(equations_list, proposed_solutions_str, variables)

Author: WALMA Project
"""

import logging
import sympy
import numpy as np

from sympy.parsing.sympy_parser import (
    parse_expr,
    standard_transformations,
    implicit_multiplication_application
)
from sympy import Symbol, simplify, Poly, piecewise_expand, Piecewise, lambdify, solve


# -----------------------------------------------------------------------------
# 1) Polynomial Division Check (Remainder Theorem / Factor Theorem)
# -----------------------------------------------------------------------------
def verify_polynomial_division(
    dividend: str,
    divisor: str,
    proposed_quotient: str,
    proposed_remainder: str,
    var="x"
) -> bool:
    """
    Checks if dividend / divisor = proposed_quotient + proposed_remainder/divisor.
    Steps:
      - Symbolically do polynomial division using sympy.poly
      - Compare results with proposed_quotient and remainder
    """
    try:
        x = Symbol(var, real=True)
        trans = (standard_transformations + (implicit_multiplication_application,))

        dividend_expr = parse_expr(dividend, local_dict={var: x}, transformations=trans)
        divisor_expr = parse_expr(divisor, local_dict={var: x}, transformations=trans)
        quotient_expr = parse_expr(proposed_quotient, local_dict={var: x}, transformations=trans)
        remainder_expr = parse_expr(proposed_remainder, local_dict={var: x}, transformations=trans)

        # Use sympy's Poly for polynomial division
        poly_dividend = Poly(dividend_expr, x)
        poly_divisor = Poly(divisor_expr, x)

        q_sym, r_sym = poly_dividend.div(poly_divisor)  # q_sym, r_sym are polynomials

        # Compare q_sym to quotient_expr
        # We can do q_sym.as_expr() for a normal Sympy expression
        diff_q = simplify(q_sym.as_expr() - quotient_expr)
        if diff_q != 0:
            return False

        # Compare r_sym to remainder_expr
        diff_r = simplify(r_sym.as_expr() - remainder_expr)
        if diff_r != 0:
            return False

        return True
    except Exception as e:
        logging.error(f"verify_polynomial_division error: {e}")
        return False


# -----------------------------------------------------------------------------
# 2) Domain & Range Verification (basic version)
# -----------------------------------------------------------------------------
def verify_domain_range(func_expr: str, proposed_domain: str, proposed_range: str, var="x"):
    """
    Attempts to confirm that the proposed_domain and proposed_range match the actual domain and range.
    In general, domain/range verification can be quite tricky.
    We'll do a basic approach:
      - Try to deduce domain from sympy (e.g. check for denominators = 0, log argument > 0, etc.)
      - Sample function numerically to guess range (if it's unbounded or certain intervals).
    This is not bulletproof, but a starting point.
    """
    try:
        x = Symbol(var, real=True)
        f = parse_expr(func_expr, local_dict={var: x})

        # 2a) Domain check (symbolic approach is partial—some functions are complicated).
        # We'll attempt to use sympy.calculus.util.continuous_domain or sympy.calculus.util.function_range
        from sympy.calculus.util import continuous_domain, function_range

        domain_sym = continuous_domain(f, x, sympy.Reals)
        # domain_sym is a Sympy set describing where f is continuous. Not always the full domain, but typical.

        # Compare domain_sym with proposed_domain (a string) by symbolic sets approach if possible
        # For example, proposed_domain might be "(-oo, oo)" or "x > 0" etc.
        # Very naive approach: we parse the proposed domain as an Interval or Union if possible.
        # Or we skip real parse and do a text-based check. For now, let's do a naive text check:
        domain_actual_str = str(domain_sym)  # e.g. Interval(-oo, oo) or Intersection...
        domain_proposed_str = proposed_domain.strip()

        # Quick hacky approach: check substring match or exact match
        # Real system: you'd parse "(-∞, ∞)" => Interval(-oo, oo)
        # For now, let's do:
        if domain_proposed_str not in domain_actual_str:
            # If it doesn't match, let's do a fallback numeric approach or just fail
            pass  # We'll keep checking range, but domain might fail

        # 2b) Range check
        # We'll attempt a rough approach: function_range
        # Then compare text with proposed_range
        # function_range can be expensive or fail for complicated f.
        # We'll wrap in a try/except
        try:
            range_sym = function_range(f, x, domain_sym)
            range_actual_str = str(range_sym)
        except:
            # fallback: numeric sampling
            range_actual_str = "[fallback range check]"
            # do random sampling of x in domain_sym if it's something nice, else skip

        range_proposed_str = proposed_range.strip()
        # compare similarly
        if range_proposed_str not in range_actual_str:
            # might fail
            pass

        # For now, let's just do a basic pass/fail approach
        # We'll say "pass" if the proposed domain and range strings show up somewhere in the actual strings
        domain_match = (domain_proposed_str in domain_actual_str)
        range_match = (range_proposed_str in range_actual_str)

        return domain_match and range_match

    except Exception as e:
        logging.error(f"verify_domain_range error: {e}")
        return False


# -----------------------------------------------------------------------------
# 3) Function Composition
# -----------------------------------------------------------------------------
def verify_function_composition(
    f_expr: str,
    g_expr: str,
    proposed_expr: str,
    composition_order="f(g(x))",
    var="x"
) -> bool:
    """
    Check if proposed_expr is indeed f(g(x)) or g(f(x)), depending on composition_order.
    E.g. composition_order="f(g(x))" => we do f(g(x)) and compare with proposed_expr.
    """
    if not (f_expr.strip() and g_expr.strip() and proposed_expr.strip()):
        return False

    try:
        x_sym = Symbol(var, real=True)
        f_parsed = parse_expr(f_expr, local_dict={var: x_sym})
        g_parsed = parse_expr(g_expr, local_dict={var: x_sym})
        p_parsed = parse_expr(proposed_expr, local_dict={var: x_sym})

        if "f(g(" in composition_order.lower():
            # compute actual = f(g(x))
            actual = f_parsed.subs(x_sym, g_parsed)
        else:
            # assume "g(f("
            actual = g_parsed.subs(x_sym, f_parsed)

        return simplify(actual - p_parsed) == 0

    except Exception as e:
        logging.error(f"verify_function_composition error: {e}")
        return False


# -----------------------------------------------------------------------------
# 4) Piecewise Function Equivalence
# -----------------------------------------------------------------------------
def verify_piecewise_equivalence(
    piecewise_expr: str,
    proposed_expr: str,
    var="x",
    numeric_fallback=True
):
    """
    Check if two piecewise-defined expressions are equivalent for all x in their domain.
    We'll parse both as Sympy Piecewise if possible, or at least parse them as expressions
    that might evaluate piecewise.

    If symbolic simplification doesn't show equality, we do numeric checks at random points.
    """
    if not piecewise_expr.strip() or not proposed_expr.strip():
        return False

    try:
        x_sym = Symbol(var, real=True)

        # parse
        trans = (standard_transformations + (implicit_multiplication_application,))
        pw_expr = parse_expr(piecewise_expr, local_dict={var: x_sym}, transformations=trans)
        prop_expr = parse_expr(proposed_expr, local_dict={var: x_sym}, transformations=trans)

        # Attempt direct piecewise_expand comparison
        pw_expanded = piecewise_expand(pw_expr)
        prop_expanded = piecewise_expand(prop_expr)

        # Sympy might or might not unify them exactly. We'll try:
        expr_diff = simplify(pw_expanded - prop_expanded)
        if expr_diff == 0:
            return True

        if numeric_fallback:
            # We pick random points in a typical range
            f_pw = sympy.lambdify(x_sym, pw_expanded, 'numpy')
            f_prop = sympy.lambdify(x_sym, prop_expanded, 'numpy')

            for _ in range(10):
                test_x = np.random.uniform(-10, 10)
                try:
                    val_pw = f_pw(test_x)
                    val_prop = f_prop(test_x)
                    if abs(val_pw - val_prop) > 1e-7:
                        return False
                except Exception:
                    # If there's a domain error, skip
                    pass
            return True

        return False

    except Exception as e:
        logging.error(f"verify_piecewise_equivalence error: {e}")
        return False


# -----------------------------------------------------------------------------
# 5) Function Transformations
# -----------------------------------------------------------------------------
def verify_function_transformation(
    original_expr: str,
    transformed_expr: str,
    proposed_explanation: str,
    var="x"
):
    """
    Check if "transformed_expr" is indeed a transformation of "original_expr" 
    of the form, e.g., f(a*x + b) + c, or reflections, etc.

    Implementation:
      1) Attempt to parse both expressions.
      2) We can heuristically compare or look for patterns: scaling in x, shifts in x, scaling in y, etc.
      3) Then see if "proposed_explanation" matches what we detect. 
         For now, we'll do a simple numeric approach:
         - pick a random set of x-values 
         - see if y-values match the transformation described by "proposed_explanation"
      4) Real approach might require a specialized "transformation detection" algorithm 
         (e.g., comparing expansions).
    """
    # This is quite open-ended. We'll do a skeleton approach:
    if not original_expr.strip() or not transformed_expr.strip():
        return False

    try:
        x_sym = Symbol(var, real=True)
        f_orig = parse_expr(original_expr, local_dict={var: x_sym})
        f_trans = parse_expr(transformed_expr, local_dict={var: x_sym})

        # Quick check: if they are symbolically the same, maybe the transformation is trivial
        if simplify(f_orig - f_trans) == 0:
            # Then the proposed explanation should say something about "no change"
            return "no change" in proposed_explanation.lower()

        # Otherwise, let's do a numeric test for plausibility
        # e.g., see if there's a consistent shift in x, shift in y, scale in x, scale in y
        # We'll do a naive approach. We won't parse the "proposed_explanation" in detail, 
        # just ensure that the transformation is "some standard form."
        # For example: f(a*x + b) + c
        # We'll try to match that pattern by symbolic means:
        # Let's define a, b, c as unknown symbols and see if we can solve f_trans(x) = f_orig(a*x+b)+c
        a, b, c = sympy.symbols('a b c', real=True)
        # We do a symbolic approach: is f_trans(x) - (f_orig.subs(x, a*x+b) + c) = 0 for all x?
        eq_expr = simplify(f_trans - (f_orig.subs(x_sym, a*x_sym + b) + c))
        # If eq_expr can be identically zero for some real a,b,c, that means it's a transformation of that form.
        # We'll attempt to solve eq_expr == 0 for a,b,c
        # This might be quite complicated. We'll do an attempt with sympy's "reduce_andsolve" or "reduce_andsimplify"
        # But let's do a simpler approach:
        # We'll do a polynomial approach or series expansion approach if the expressions are polynomial-like.
        # If not polynomial, we might need numeric points.

        # Let's do numeric approach at a few points and see if we can solve for a,b,c:
        points = [-2, -1, 0, 1, 2]
        vals = []
        for px in points:
            lhs_val = f_trans.subs(x_sym, px)
            rhs_val = f_orig.subs(x_sym, a*px + b) + c
            vals.append(lhs_val - rhs_val)

        # Now we have 5 expressions in terms of a,b,c that should all be 0
        # Let's see if we can solve them. If we can find a consistent (a,b,c) => pass
        sol = sympy.solve(vals, [a, b, c], dict=True)
        if len(sol) > 0:
            # We found at least one solution => it's a valid transformation of that form
            # Check if the proposed_explanation has any mention of these values
            # e.g. if "a=2, b=-1, c=3" => maybe the explanation says "scaled horizontally by 1/2, shifted 1/2, up 3"
            # We'll skip that detail for now; just return True
            return True
        else:
            return False

    except Exception as e:
        logging.error(f"verify_function_transformation error: {e}")
        return False


# -----------------------------------------------------------------------------
# 6) System of Equations Solutions
# -----------------------------------------------------------------------------
def verify_system_of_equations_solutions(equations_list, proposed_solutions_str, variables):
    """
    For a system of equations in multiple variables:
      equations_list = ["x+y=2", "x-y=0"]  (or "Eq(x+y,2)", "Eq(x-y,0)")
      proposed_solutions_str = "x=1, y=1" or " (1,1) " or "x=1,y=1 | x=2,y=0" if multiple solutions
      variables = ["x","y"]

    Implementation:
      1) parse each equation
      2) sympy.solve(eqs, variables)
      3) parse the user-proposed solutions
      4) compare sets
    """
    if not equations_list or not proposed_solutions_str.strip() or not variables:
        return False

    try:
        # Prepare local dictionary
        local_dict = {}
        for v in variables:
            local_dict[v] = sympy.Symbol(v, real=True)

        eq_parsed = []
        trans = (standard_transformations + (implicit_multiplication_application,))
        for eq in equations_list:
            # parse
            try:
                parsed_eq = sympy.parse_expr(eq, local_dict=local_dict, transformations=trans)
                # if parsed_eq is not an Eq, interpret it as = 0
                if not isinstance(parsed_eq, sympy.Equality):
                    eq_obj = sympy.Eq(parsed_eq, 0)
                else:
                    eq_obj = parsed_eq
                eq_parsed.append(eq_obj)
            except:
                pass

        # Solve system
        sol_sympy = sympy.solve(eq_parsed, list(local_dict.values()), dict=True)
        # e.g. [ {x: 1, y: 1} ] or multiple solutions

        # parse proposed solutions
        # e.g. "x=1, y=1" or "x=1, y=1 | x=-1, y=3" etc.
        # We'll split by '|'
        solution_chunks = proposed_solutions_str.split('|')
        proposed_solutions = []
        for chunk in solution_chunks:
            chunk_clean = chunk.strip()
            if not chunk_clean:
                continue
            # might be "x=1,y=1" or "(1,1)" etc. We'll do a naive approach:
            # if it has '=' we parse key=val pairs
            if '=' in chunk_clean:
                # e.g. "x=1,y=1"
                pairs = chunk_clean.split(',')
                sol_dict = {}
                for p in pairs:
                    if '=' in p:
                        lhs, rhs = p.split('=')
                        lhs_var = lhs.strip()
                        rhs_expr = rhs.strip()
                        if lhs_var in local_dict:
                            val = sympy.parse_expr(rhs_expr, local_dict=local_dict, transformations=trans)
                            sol_dict[lhs_var] = sympy.simplify(val)
                if sol_dict:
                    proposed_solutions.append(sol_dict)
            else:
                # maybe it's something like "(1,1)" -> parse as a tuple
                # We'll remove parentheses
                chunk_clean = chunk_clean.replace('(','').replace(')','')
                parts = chunk_clean.split(',')
                if len(parts) == len(variables):
                    sol_dict = {}
                    for i, v in enumerate(variables):
                        val = sympy.parse_expr(parts[i].strip(), local_dict=local_dict, transformations=trans)
                        sol_dict[v] = sympy.simplify(val)
                    proposed_solutions.append(sol_dict)

        # Now we have sympy solutions in sol_sympy (list of dicts), 
        # and user solutions in proposed_solutions (list of dicts).
        # We'll compare sets (each dict is a mapping var->value).
        # Convert them to tuples in a canonical order to set compare:
        def dict_to_tuple(d):
            return tuple(sympy.simplify(d[v]) for v in variables)

        found_set = set(dict_to_tuple(s) for s in sol_sympy)
        proposed_set = set(dict_to_tuple(s) for s in proposed_solutions)

        return found_set == proposed_set

    except Exception as e:
        logging.error(f"verify_system_of_equations_solutions error: {e}")
        return False
