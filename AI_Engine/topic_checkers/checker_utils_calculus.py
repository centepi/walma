#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
checker_utils_calculus.py

Collection of specialized verification functions for Calculus topics:

  1) verify_derivative(original_expr, proposed_expr, var="x")
  2) verify_partial_derivative(expr, proposed_expr, wrt="x", variables=None)
  3) verify_implicit_derivative(equation, proposed_derivative, wrt="x")
  4) verify_nth_derivative(original_expr, proposed_expr, var="x", n=2)
  5) verify_integral(integrand, proposed_integral, var="x")
  6) verify_definite_integral(integrand, lower, upper, proposed_value, var="x")
  7) verify_parametric_derivative(x_of_t, y_of_t, proposed_expr, t="t")
  8) verify_parametric_integral(x_of_t, y_of_t, proposed_expr, t="t", mode="area" or "arc_length")
  9) verify_taylor_series(expr, center, order, proposed_series, var="x")
  10) verify_ode_solution(ode_expr, proposed_solution, var="x")

Author: WALMA Project
"""

import logging
import sympy
from sympy import Symbol, Function, simplify, diff, integrate, oo, Eq, dsolve, expand
from sympy.parsing.sympy_parser import (
    parse_expr,
    standard_transformations,
    implicit_multiplication_application
)

import numpy as np  # for optional numeric fallback


# -----------------------------------------------------------------------------
# 1) Basic Derivative Check
# -----------------------------------------------------------------------------
def verify_derivative(original_expr: str, proposed_expr: str, var="x") -> bool:
    """
    Checks if proposed_expr is d/d(var) of original_expr (standard single-variable derivative).
    """
    if not original_expr.strip() or not proposed_expr.strip():
        return False
    try:
        x = Symbol(var)
        f_orig = parse_expr(original_expr, local_dict={var: x})
        fprime_expected = f_orig.diff(x)

        f_proposed = parse_expr(proposed_expr, local_dict={var: x})

        return simplify(fprime_expected - f_proposed) == 0
    except Exception as e:
        logging.error(f"verify_derivative error: {e}")
        return False


# -----------------------------------------------------------------------------
# 2) Partial Derivative Check
# -----------------------------------------------------------------------------
def verify_partial_derivative(expr: str, proposed_expr: str, wrt="x", variables=None) -> bool:
    """
    Checks if proposed_expr is the partial derivative of expr w.r.t. variable 'wrt'.
    E.g., expr="x^2 + 3xy + y^2", wrt="x" => partial derivative = "2x + 3y".
    variables can be something like ["x", "y"] if needed.
    """
    if not expr.strip() or not proposed_expr.strip():
        return False
    if variables is None:
        variables = ["x", "y"]  # default
    try:
        syms = {v: sympy.Symbol(v) for v in variables}
        f_expr = parse_expr(expr, local_dict=syms)
        partial_var = syms[wrt]  # the symbol we differentiate with respect to
        fprime_expected = f_expr.diff(partial_var)

        f_proposed = parse_expr(proposed_expr, local_dict=syms)
        return simplify(fprime_expected - f_proposed) == 0
    except Exception as e:
        logging.error(f"verify_partial_derivative error: {e}")
        return False


# -----------------------------------------------------------------------------
# 3) Implicit Derivative Check
# -----------------------------------------------------------------------------
def verify_implicit_derivative(equation: str, proposed_derivative: str, wrt="x", dep_var="y"):
    """
    Checks if proposed_derivative is dy/dx for an implicitly defined function F(x, y) = 0.

    Example:
      equation = "x^2 + y^2 - 1"
      proposed_derivative = "-x/y"  (which is dy/dx from F=0 => dF/dx = 0 => 2x + 2y*y' = 0 => y'=-x/y)
    """
    if not equation.strip() or not proposed_derivative.strip():
        return False
    try:
        x = Symbol(wrt)
        y = Symbol(dep_var)
        # parse eq
        eq_expr = parse_expr(equation, local_dict={wrt: x, dep_var: y})

        # Differentiate implicitly
        # d/dx of eq_expr = 0 => solve for dy/dx
        # eq_expr.diff(x) = partial w.r.t x + partial w.r.t y * dy/dx
        dF_dx = eq_expr.diff(x) + eq_expr.diff(y)*sympy.Symbol("y'", real=True)
        # i.e. dF_dx = 0 => eq => solve for y'
        # but we can't just call solve(...) with Symbol("y'") unless we do a trick
        # We'll do it symbolically:

        yprime = sympy.Symbol("yprime", real=True)  # some dummy symbol
        dF_dx_sub = eq_expr.diff(x) + eq_expr.diff(y)*yprime
        # solve dF_dx_sub=0 for yprime
        solution = sympy.solve(sympy.Eq(dF_dx_sub, 0), yprime)
        # solution might be a list

        if not solution:
            return False
        # Usually we expect exactly one solution for y'
        # But in degenerate cases, might have multiple. We'll just compare with the first
        implicit_deriv_expected = simplify(solution[0])

        # parse proposed derivative
        proposed_expr = parse_expr(proposed_derivative, local_dict={wrt: x, dep_var: y})
        return simplify(implicit_deriv_expected - proposed_expr) == 0

    except Exception as e:
        logging.error(f"verify_implicit_derivative error: {e}")
        return False


# -----------------------------------------------------------------------------
# 4) nth Derivative Check
# -----------------------------------------------------------------------------
def verify_nth_derivative(original_expr: str, proposed_expr: str, var="x", n=2) -> bool:
    """
    Checks if proposed_expr is the nth derivative of original_expr w.r.t var.
    For example, if n=2, we check second derivative.
    """
    if not original_expr.strip() or not proposed_expr.strip():
        return False
    try:
        x = Symbol(var)
        f_orig = parse_expr(original_expr, local_dict={var: x})
        nth_deriv_expected = f_orig
        for _ in range(n):
            nth_deriv_expected = nth_deriv_expected.diff(x)

        f_proposed = parse_expr(proposed_expr, local_dict={var: x})
        return simplify(nth_deriv_expected - f_proposed) == 0
    except Exception as e:
        logging.error(f"verify_nth_derivative error: {e}")
        return False


# -----------------------------------------------------------------------------
# 5) Indefinite Integral Check
# -----------------------------------------------------------------------------
def verify_integral(integrand: str, proposed_integral: str, var="x") -> bool:
    """
    Check if proposed_integral is a valid indefinite integral of integrand (up to a constant).
    i.e. derivative of proposed_integral == integrand
    """
    if not integrand.strip() or not proposed_integral.strip():
        return False
    try:
        x = Symbol(var)
        f_expr = parse_expr(integrand, local_dict={var: x})
        F_prop = parse_expr(proposed_integral, local_dict={var: x})

        # Check derivative
        diff_expr = simplify(F_prop.diff(x) - f_expr)
        return diff_expr == 0
    except Exception as e:
        logging.error(f"verify_integral error: {e}")
        return False


# -----------------------------------------------------------------------------
# 6) Definite Integral Check
# -----------------------------------------------------------------------------
def verify_definite_integral(
    integrand: str,
    lower: str,
    upper: str,
    proposed_value: str,
    var="x",
    numeric_fallback=True
) -> bool:
    """
    Check if the definite integral of integrand from lower to upper equals proposed_value.
    Steps:
      1) Symbolically integrate integrand from lower->upper using sympy.integrate.
      2) Compare with parse(proposed_value).
      3) If symbolic check fails or is inconclusive, optionally use numeric fallback.
    """
    if not (integrand.strip() and lower.strip() and upper.strip() and proposed_value.strip()):
        return False

    try:
        x = Symbol(var, real=True)
        transformations = (standard_transformations + (implicit_multiplication_application,))

        f_expr = parse_expr(integrand, local_dict={var: x}, transformations=transformations)
        lower_val = parse_expr(lower, local_dict={var: x}, transformations=transformations)
        upper_val = parse_expr(upper, local_dict={var: x}, transformations=transformations)
        proposed_val_expr = parse_expr(proposed_value, local_dict={var: x}, transformations=transformations)

        # Symbolic definite integral
        integral_expr = integrate(f_expr, (x, lower_val, upper_val))
        # Compare symbolic difference
        diff_simpl = simplify(integral_expr - proposed_val_expr)
        if diff_simpl == 0:
            return True

        # If that fails or doesn't simplify to 0, we can do numeric fallback
        if numeric_fallback:
            # We'll turn the difference into a lambda and evaluate
            diff_lambda = sympy.lambdify([], diff_simpl, 'numpy')
            # If it doesn't depend on x (it shouldn't, it's a constant difference),
            # we just check if it's near 0
            val = diff_lambda()
            return abs(val) < 1e-7

        return False

    except Exception as e:
        logging.error(f"verify_definite_integral error: {e}")
        return False


# -----------------------------------------------------------------------------
# 7) Parametric Derivative: dy/dx when x(t) and y(t) given
# -----------------------------------------------------------------------------
def verify_parametric_derivative(
    x_of_t: str,
    y_of_t: str,
    proposed_expr: str,
    t="t"
) -> bool:
    """
    Checks if proposed_expr is the derivative dy/dx for parametric equations:
      x = x(t), y = y(t)
    Then dy/dx = (dy/dt) / (dx/dt).

    Example:
      x(t) = "cos(t)"
      y(t) = "sin(t)"
      dy/dx = "-(tan(t))" or "dy/dx = -(sin(t))/cos(t)" => depends on simplification.
    """
    if not (x_of_t.strip() and y_of_t.strip() and proposed_expr.strip()):
        return False
    try:
        param = Symbol(t, real=True)
        x_expr = parse_expr(x_of_t, local_dict={t: param})
        y_expr = parse_expr(y_of_t, local_dict={t: param})

        dxdt = x_expr.diff(param)
        dydt = y_expr.diff(param)

        # Actual dy/dx:
        # (dy/dt) / (dx/dt) assuming dx/dt != 0
        with sympy.evaluate(False):
            actual_dydx = simplify(dydt / dxdt)

        prop_expr = parse_expr(proposed_expr, local_dict={t: param})

        return simplify(actual_dydx - prop_expr) == 0

    except Exception as e:
        logging.error(f"verify_parametric_derivative error: {e}")
        return False


# -----------------------------------------------------------------------------
# 8) Parametric Integral
# -----------------------------------------------------------------------------
def verify_parametric_integral(
    x_of_t: str,
    y_of_t: str,
    proposed_expr: str,
    t="t",
    mode="area",
    lower=None,
    upper=None
):
    """
    Example "area" integral: ∫ y(t)* x'(t) dt
    Or "arc_length" integral: ∫ sqrt( (dx/dt)^2 + (dy/dt)^2 ) dt
    Could be indefinite or definite (if lower,upper provided).
    In the indefinite case, we check derivative. In the definite case, we compare numeric/symbolic result.

    mode can be:
      - "area": tries ∫ y(t)*dx = ∫ y(t)*x'(t) dt
      - "arc_length": ∫ sqrt( (dx/dt)^2 + (dy/dt)^2 ) dt
      (You can add more modes if you wish, e.g. param. surface area, etc.)

    If definite (lower,upper not None), we compare numeric or symbolic result to proposed_expr.
    If indefinite, we check derivative or do equivalence check.
    """
    if not (x_of_t.strip() and y_of_t.strip() and proposed_expr.strip()):
        return False

    try:
        param = Symbol(t, real=True)
        x_expr = parse_expr(x_of_t, local_dict={t: param})
        y_expr = parse_expr(y_of_t, local_dict={t: param})
        dxdt = x_expr.diff(param)
        dydt = y_expr.diff(param)

        if mode.lower() == "area":
            integrand = y_expr * dxdt
        elif mode.lower() == "arc_length":
            integrand = sympy.sqrt(dxdt**2 + dydt**2)
        else:
            logging.error(f"Unknown parametric_integral mode: {mode}")
            return False

        # Parse proposed expression
        prop_expr = parse_expr(proposed_expr, local_dict={t: param})

        # Check indefinite or definite
        if lower is None or upper is None:
            # Indefinite integral check: derivative of prop_expr should be integrand
            diff_expr = simplify(prop_expr.diff(param) - integrand)
            return diff_expr == 0
        else:
            # Definite integral check
            lower_expr = parse_expr(lower, local_dict={t: param})
            upper_expr = parse_expr(upper, local_dict={t: param})
            actual_val = sympy.integrate(integrand, (param, lower_expr, upper_expr))

            # Compare difference
            diff_simpl = simplify(actual_val - prop_expr)
            if diff_simpl == 0:
                return True
            # numeric fallback
            f_diff = sympy.lambdify([], diff_simpl, 'numpy')
            val = f_diff()
            return abs(val) < 1e-7

    except Exception as e:
        logging.error(f"verify_parametric_integral error: {e}")
        return False


# -----------------------------------------------------------------------------
# 9) Taylor/Maclaurin Series
# -----------------------------------------------------------------------------
def verify_taylor_series(
    expr: str,
    center: str,
    order: int,
    proposed_series: str,
    var="x",
    numeric_fallback=True
):
    """
    Checks if proposed_series is the correct Taylor expansion of expr about x=center, up to "order" terms.
    Steps:
      1) parse expr
      2) use sympy.series(expr, (x, center_val, order+1)) or .expand() style approach
      3) compare to proposed_series by symbolic difference or numeric sampling
    """
    if not (expr.strip() and center.strip() and proposed_series.strip()):
        return False

    try:
        x = Symbol(var, real=True)
        center_val = parse_expr(center, local_dict={var: x})

        # parse original expression
        f_expr = parse_expr(expr, local_dict={var: x})

        # get actual series up to (order-1)th power (the truncated polynomial part).
        # Sympy's .series(...) includes terms up to order-1 plus big-O notation.
        # E.g., f_expr.series(x, center_val, order+1).removeO() might do it,
        # but we might also build it manually.
        actual_series = f_expr.series(x, center_val, order+1).removeO()

        # parse proposed series
        prop_expr = parse_expr(proposed_series, local_dict={var: x})

        # The .series(...) returns an expression with possible remainder terms removed
        # after calling .removeO(). Let's simplify the difference.
        diff_simpl = simplify(actual_series - prop_expr)
        if diff_simpl == 0:
            return True

        if numeric_fallback:
            # Test at random points near the center
            f_diff = sympy.lambdify(x, diff_simpl, 'numpy')
            for _ in range(5):
                # choose a small random offset from center
                # (since expansions might be best near the center)
                offset = np.random.uniform(-1, 1)
                test_val = float(center_val) + offset
                try:
                    val = f_diff(test_val)
                    if abs(val) > 1e-7:
                        return False
                except ZeroDivisionError:
                    pass
            return True

        return False

    except Exception as e:
        logging.error(f"verify_taylor_series error: {e}")
        return False


# -----------------------------------------------------------------------------
# 10) ODE Solution Verification
# -----------------------------------------------------------------------------
def verify_ode_solution(
    ode_expr: str,
    proposed_solution: str,
    var="x",
    dependent_var="y"
):
    """
    Checks if proposed_solution is indeed a solution to the ODE given by ode_expr = 0.
    Example:
      ode_expr = "Eq(y'(x), x*y(x))"  or "y'(x) - x*y(x) = 0"
      proposed_solution = "C1*exp(x^2/2)"
    We'll parse the ODE, parse proposed_solution as y(x), then substitute y(x) into ODE_expr and check if = 0.

    Implementation approach:
      1) parse the ODE expression as an equality or standard form
      2) parse proposed_solution as a function y(x)
      3) substitute y and its derivatives into the ODE
      4) simplify => 0?
    """
    if not (ode_expr.strip() and proposed_solution.strip()):
        return False

    try:
        x_sym = Symbol(var, real=True)
        y = Function(dependent_var)(x_sym)  # y(x)

        # We'll do a somewhat flexible parse. If ode_expr is "y'(x) - x*y(x)", we'll interpret it = 0
        # Or if it's "Eq(y'(x), x*y(x))", we parse that directly with sympy.
        # First try parse as Eq(...). If that fails, we'll treat it as "left side = 0".
        transformations = (standard_transformations + (implicit_multiplication_application,))

        # define local dict so "y(x_sym)" can be recognized
        local_d = {
            var: x_sym,
            dependent_var: y
        }
        # we might also need y'(x_sym)
        # But let's see if we can do it in a simpler way.

        # We'll replace "y" with "y(x)" if not present
        # This is somewhat naive. A robust pipeline might store the ODE in a more structured way.

        # Attempt direct parse
        try:
            parsed_ode = parse_expr(ode_expr, local_dict=local_d, transformations=transformations)
        except:
            # If that fails, we try "Eq(expr, 0)" approach:
            # so if the ODE is "y'(x) - x*y(x)", we parse that as an expression
            # and interpret it eq to 0.
            left_side = parse_expr(ode_expr, local_dict=local_d, transformations=transformations)
            parsed_ode = sympy.Eq(left_side, 0)

        # parse proposed solution as y_sol(x)
        # e.g. proposed_solution = "C1*exp(x^2/2)"
        # We can define a symbol 'C1' as a constant
        C1 = sympy.Symbol('C1', real=True)
        # Additional constants if needed:
        C2 = sympy.Symbol('C2', real=True)
        local_d.update({'C1': C1, 'C2': C2})

        y_sol_expr = parse_expr(proposed_solution, local_dict=local_d, transformations=transformations)
        # We'll define y_sol as a sympy Function
        # But simpler is to do direct substitution: whenever we see y(x), we replace it with y_sol_expr
        # and y'(x) with derivative of y_sol_expr, etc.

        # Create a symbolic derivative of y_sol_expr
        y_sol_deriv = y_sol_expr.diff(x_sym)

        # We'll do a naive approach: parse_ode might be an Eq(...) or an expression.
        # If it's Eq(left, right), we do left_sub - right_sub => check if 0
        # If it's an expression f(...) => we interpret that as f(...)=0 => check if 0
        if isinstance(parsed_ode, sympy.Eq):
            # substitute y -> y_sol_expr, y'(x) -> derivative
            left_sub = parsed_ode.lhs
            right_sub = parsed_ode.rhs

            # We do a replacement for y(x_sym) => y_sol_expr, y'(x_sym) => y_sol_deriv
            # in sympy, we can do .subs({y: y_sol_expr, y.diff(x_sym): y_sol_deriv}), but we have to be careful
            # since y is a Function. We'll do a direct approach:

            # For y(x_sym):
            # We'll create a pattern y(x_sym) to replace with y_sol_expr
            left_sub = left_sub.subs(y, y_sol_expr)
            left_sub = left_sub.subs(y.diff(x_sym), y_sol_deriv)

            right_sub = right_sub.subs(y, y_sol_expr)
            right_sub = right_sub.subs(y.diff(x_sym), y_sol_deriv)

            # Now check left_sub - right_sub => 0
            ode_check = simplify(left_sub - right_sub)
            return ode_check == 0

        else:
            # treat parsed_ode as an expression => interpret =0
            expr_sub = parsed_ode.subs(y, y_sol_expr)
            expr_sub = expr_sub.subs(y.diff(x_sym), y_sol_deriv)

            ode_check = simplify(expr_sub)
            return ode_check == 0

    except Exception as e:
        logging.error(f"verify_ode_solution error: {e}")
        return False
