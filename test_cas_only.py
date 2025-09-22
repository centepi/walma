# test_cas_only.py
"""
Minimal offline unit tests for CAS validation.
- No network calls
- No Firebase
- Just exercises pipeline_scripts/cas_validator.validate()

How to run:
    python test_cas_only.py
"""

import os
import sys
from pprint import pprint

# --- Ensure A_Level is on sys.path so `pipeline_scripts` can be imported ---
HERE = os.path.dirname(os.path.abspath(__file__))
A_LEVEL_DIR = os.path.join(HERE, "A_Level")
if os.path.isdir(A_LEVEL_DIR) and A_LEVEL_DIR not in sys.path:
    sys.path.insert(0, A_LEVEL_DIR)

try:
    from pipeline_scripts import cas_validator as cas
except Exception as e:
    print("ERROR: Could not import 'pipeline_scripts.cas_validator'.")
    print("Tip: place this file at your project root (one level above 'A_Level').")
    print(f"Underlying import error: {e}")
    sys.exit(1)


def run_case(name, answer_spec, expected_ok):
    """Run a single CAS validation case."""
    ok, report = cas.validate({"answer_spec": answer_spec})
    passed = (ok == expected_ok)
    status = "PASS" if passed else "FAIL"
    print(f"[{status}] {name:30} -> ok={ok} expected={expected_ok}")
    if not passed:
        print("    spec   :", answer_spec)
        print("    report :", report)
    return passed


def main():
    total = 0
    passed = 0

    cases = [
        # --- PASS cases ---
        ("roots simple (pass)",
         {"kind":"roots","expr":"x**2 - 5*x + 6","solutions":["2","3"]},
         True),

        ("value at point (pass)",
         {"kind":"value","expr":"x**2 - 5*x + 6","at":{"x":"2"},"value":"0"},
         True),

        ("expression_equiv (pass)",
         {"kind":"expression_equiv","lhs":"(x-2)*(x-3)","rhs":"x**2 - 5*x + 6"},
         True),

        ("derivative symbolic (pass)",
         {"kind":"derivative","of":"x**3","result":"3*x**2","order":1},
         True),

        ("derivative numeric (pass)",
         {"kind":"derivative","of":"sin(x)","at":{"x":"0"},"value":"1","order":1},
         True),

        ("antiderivative (pass)",
         {"kind":"antiderivative","of":"3*x**2","result":"x**3 + 7"},
         True),

        ("limit finite (pass)",
         {"kind":"limit","expr":"(x**2-1)/(x-1)","approaches":"1","value":"2"},
         True),

        ("limit to +infinity (pass)",
         {"kind":"limit","expr":"(2*x+1)/x","approaches":"oo","value":"2"},
         True),

        ("stationary_point min (pass)",
         {"kind":"stationary_point","of":"x**2","point":{"x":"0","y":"0"},"nature":"min"},
         True),

        ("interval 4-item (pass)",
         {"kind":"interval",
          "condition":"x**2 - 4 >= 0",
          "intervals":[["[","-oo","-2",")"],["(","2","oo","]"]]},
         True),

        ("interval 3-item shorthand (pass)",
         {"kind":"interval",
          "condition":"x**2 - 4 >= 0",
          "intervals":[["-oo","-2",")"],["(","2","oo"]]},
         True),

        ("system solve (pass)",
         {"kind":"system_solve",
          "equations":["x + y - 3 = 0","2*x - y = 0"],
          "solution":{"x":"1","y":"2"}},
         True),

        ("unicode & bars normalization (pass)",
         {"kind":"expression_equiv",
          "lhs":"|x|", "rhs":"Abs(x)"},
         True),

        ("unicode product/minus/sqrt/pi (pass)",
         {"kind":"expression_equiv",
          "lhs":"(x−2)×(x−3)", "rhs":"x^2 − 5x + 6"},
         True),

        # --- FAIL cases ---
        ("roots wrong value (fail)",
         {"kind":"roots","expr":"x**2 - 5*x + 6","solutions":["2","4"]},
         False),

        ("derivative wrong (fail)",
         {"kind":"derivative","of":"x**3","result":"6*x","order":1},
         False),

        ("expression_equiv wrong (fail)",
         {"kind":"expression_equiv","lhs":"(x-2)*(x-4)","rhs":"x**2 - 5*x + 6"},
         False),
    ]

    for name, spec, expected in cases:
        total += 1
        if run_case(name, spec, expected):
            passed += 1

    print("\n--- Summary ---")
    print(f"Passed {passed}/{total} cases")
    if passed != total:
        sys.exit(1)


if __name__ == "__main__":
    main()