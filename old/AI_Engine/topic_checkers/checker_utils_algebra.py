#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
checker_utils_algebra.py

Specialized verification functions for "Algebra & Functions" topic:
  1) Factorization check
  2) Polynomial expansion check
  3) Solving polynomial (or other) equations
  4) Partial fraction decomposition
  5) Verifying sums of sequences/series
  6) (Optional) general 'equivalence' checks

Author: WALMA Project
"""

import logging
import sympy
from sympy.parsing.sympy_parser import (
    parse_expr,
    standard_transformations,
    implicit_multiplication_application
)
from sympy import Symbol, simplify, expand, factor, apart, solve, summation

import numpy as np  # for optional numeric fallback


# -----------------------------------------------------------------------------
# 1) Factorization Check
# -----------------------------------------------------------------------------
def verify_factorization(original_expr: str, proposed_factorized_expr: str, var_list=None) -> bool:
    """
    Check if proposed_factorized_expr is indeed a factorization of original_expr.
    - We can compare by factoring the original_expr (using sympy.factor) and seeing
      if it simplifies to the same expression as proposed_factorized_expr.
    - Alternatively, we can parse both expressions, expand the factorized one,
      and see if it matches the original.
    """

    if not original_expr.strip() or not proposed_factorized_expr.strip():
        return False

    if var_list is None:
        var_list = ["x"]  # default

    transformations = (standard_transformations + (implicit_multiplication_application,))
    try:
        syms = {var: sympy.Symbol(var) for var in var_list}

        # Parse
        expr_orig = parse_expr(original_expr, local_dict=syms, transformations=transformations)
        expr_prop = parse_expr(proposed_factorized_expr, local_dict=syms, transformations=transformations)

        # Compare by expanding the proposed factorization and see if it matches the original
        expanded_prop = expand(expr_prop)
        # Compare if expand(expr_orig) - expanded_prop == 0
        diff_simpl = simplify(expand(expr_orig) - expanded_prop)
        return diff_simpl == 0

    except Exception as e:
        logging.error(f"verify_factorization error: {e}")
        return False


# -----------------------------------------------------------------------------
# 2) Polynomial Expansion Check
# -----------------------------------------------------------------------------
def verify_expansion(original_factorized_expr: str, proposed_expanded_expr: str, var_list=None) -> bool:
    """
    Check if proposed_expanded_expr is the correct expanded form of original_factorized_expr.
    Essentially the inverse of factorization.
    """
    if not original_factorized_expr.strip() or not proposed_expanded_expr.strip():
        return False

    if var_list is None:
        var_list = ["x"]

    transformations = (standard_transformations + (implicit_multiplication_application,))
    try:
        syms = {var: sympy.Symbol(var) for var in var_list}

        expr_orig = parse_expr(original_factorized_expr, local_dict=syms, transformations=transformations)
        expr_prop = parse_expr(proposed_expanded_expr, local_dict=syms, transformations=transformations)

        # Expand the original expression
        expanded_orig = expand(expr_orig)
        # Check if difference with proposed is zero
        diff_simpl = simplify(expanded_orig - expr_prop)
        return diff_simpl == 0

    except Exception as e:
        logging.error(f"verify_expansion error: {e}")
        return False


# -----------------------------------------------------------------------------
# 3) Solving Polynomial/Algebraic Equations
#    (Also see a more generic verify_equation_solution in other modules)
# -----------------------------------------------------------------------------
def verify_polynomial_solution(poly_expr: str, proposed_roots_str: str, var="x") -> bool:
    """
    Specifically checks solutions (roots) of a polynomial expression = 0.
    Example:
      poly_expr = "x^2 - 4"
      proposed_roots_str = "2, -2"

    Implementation:
      1) Solve poly_expr = 0 symbolically for 'var'.
      2) Compare the set of solutions with the proposed roots.
    """
    if not poly_expr.strip() or not proposed_roots_str.strip():
        return False

    transformations = (standard_transformations + (implicit_multiplication_application,))
    try:
        x = sympy.Symbol(var)
        # Parse the polynomial expression
        polynomial = parse_expr(poly_expr, local_dict={var: x}, transformations=transformations)

        # Solve polynomial = 0
        sol_sympy = sympy.solve(sympy.Eq(polynomial, 0), x)
        # e.g. for x^2 - 4 = 0 => sol_sympy = [-2, 2]

        # Parse proposed roots
        # e.g. proposed_roots_str = "2, -2" or "x=2, x=-2"
        sanitized = proposed_roots_str.replace(f"{var}=", "").replace(" ", "")
        proposed_list = sanitized.split(',')
        proposed_solutions = [parse_expr(s) for s in proposed_list if s.strip()]

        # Compare sets
        found_vals = {sympy.simplify(r) for r in sol_sympy}
        proposed_vals = {sympy.simplify(r) for r in proposed_solutions}

        return found_vals == proposed_vals

    except Exception as e:
        logging.error(f"verify_polynomial_solution error: {e}")
        return False


# -----------------------------------------------------------------------------
# 4) Partial Fraction Decomposition
# -----------------------------------------------------------------------------
def verify_partial_fraction(original_expr: str, proposed_decomposition: str, var="x") -> bool:
    """
    Check if proposed_decomposition is the correct partial fraction decomposition of original_expr.
    Implementation approach:
      1) Parse the original expression as a rational function.
      2) Sympy's `apart(original_expr)` gives partial fraction form.
      3) Compare that to the user-proposed expression by checking equivalence.
    """
    if not original_expr.strip() or not proposed_decomposition.strip():
        return False

    transformations = (standard_transformations + (implicit_multiplication_application,))
    try:
        x = sympy.Symbol(var)
        expr_orig = parse_expr(original_expr, local_dict={var: x}, transformations=transformations)
        expr_prop = parse_expr(proposed_decomposition, local_dict={var: x}, transformations=transformations)

        # Get partial fraction of original
        pf_orig = apart(expr_orig)

        # Compare with the proposed decomposition by checking difference
        diff_simpl = simplify(pf_orig - expr_prop)
        return diff_simpl == 0

    except Exception as e:
        logging.error(f"verify_partial_fraction error: {e}")
        return False


# -----------------------------------------------------------------------------
# 5) Verifying Sums of Sequences/Series
# -----------------------------------------------------------------------------
def verify_series_sum(
    term_expr: str,
    proposed_sum_expr: str,
    index_var: str = "n",
    lower_limit=1,
    upper_limit="N"  # Could be a symbol or integer
) -> bool:
    """
    Check if the proposed_sum_expr is indeed the sum of term_expr
    from index_var = lower_limit to index_var = upper_limit.
    Example: verify that sum_{k=1 to n} of k = n(n+1)/2.

    Implementation:
      1) Parse the term expression.
      2) Use sympy.summation(...) with symbolic upper limit if it's a symbol (like "n") or numeric if integer.
      3) Compare to parse_expr(proposed_sum_expr).
    """

    if not term_expr.strip() or not proposed_sum_expr.strip():
        return False

    try:
        # Build local dict for index_var and possible other variables
        sym_index = sympy.Symbol(index_var, integer=True)

        # If upper_limit is a string like "N", parse that as well
        if isinstance(upper_limit, str):
            sym_upper = sympy.Symbol(upper_limit, positive=True)  # or nonnegative, etc.
        else:
            # assume it's an integer
            sym_upper = upper_limit

        expr_term = parse_expr(term_expr, local_dict={index_var: sym_index})
        expr_proposed_sum = parse_expr(proposed_sum_expr, local_dict={index_var: sym_index})

        # Perform symbolic summation
        sum_expr = sympy.summation(expr_term, (sym_index, lower_limit, sym_upper))

        # Check equivalence of sum_expr and expr_proposed_sum
        diff_simpl = simplify(sum_expr - expr_proposed_sum)
        return diff_simpl == 0

    except Exception as e:
        logging.error(f"verify_series_sum error: {e}")
        return False


# -----------------------------------------------------------------------------
# ADDITIONAL / OPTIONAL:
#  - verifying domain restrictions
#  - verifying inverse functions
#  - verifying function transformations
# -----------------------------------------------------------------------------

def verify_inverse_function(f_expr: str, f_inv_expr: str, var="x") -> bool:
    """
    Check if f_inv_expr is indeed the inverse function of f_expr by verifying f(f_inv(x)) = x
    and f_inv(f(x)) = x (optionally).
    """
    if not f_expr.strip() or not f_inv_expr.strip():
        return False
    try:
        x = sympy.Symbol(var)
        f = parse_expr(f_expr, local_dict={var: x})
        g = parse_expr(f_inv_expr, local_dict={var: x})

        # Check if f(g(x)) simplifies to x
        comp1 = simplify(f.subs(x, g))
        # Check if g(f(x)) simplifies to x (optional but recommended)
        comp2 = simplify(g.subs(x, f))

        return (comp1 - x).simplify() == 0 and (comp2 - x).simplify() == 0
    except Exception as e:
        logging.error(f"verify_inverse_function error: {e}")
        return False

# -----------------------------------------------------------------------------
# (END)
# -----------------------------------------------------------------------------
