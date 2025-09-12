import os
import json
import logging

# ---------------------------------------------------------
# Example: Import from your "checker_utils_algebra.py" file
# ---------------------------------------------------------
from topic_checkers.checker_utils_algebra import (
    verify_factorization,
    verify_expansion,
    verify_polynomial_solution,
    verify_partial_fraction,
    verify_series_sum,
    verify_inverse_function
)

# (Later, you can also import from your other topic files, e.g.:
# from checker_utils_calculus import verify_derivative, verify_integral, ...
# from checker_utils_linear import verify_matrix_equivalence, ...
# etc.)

# -----------------------------------------------------------------------------
# Configure Logging
# -----------------------------------------------------------------------------
logging.basicConfig(
    filename='checker.log',
    filemode='a',
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# -----------------------------------------------------------------------------
# Main Checker Logic
# -----------------------------------------------------------------------------
def main():
    input_dir = "levels"
    output_dir = "levels_check"
    os.makedirs(output_dir, exist_ok=True)

    all_results = []

    for fname in os.listdir(input_dir):
        # Skip anything not JSON
        if not fname.endswith(".json"):
            continue

        fpath = os.path.join(input_dir, fname)
        try:
            with open(fpath, "r", encoding="utf-8") as fin:
                questions = json.load(fin)
        except Exception as e:
            logging.error(f"Failed to load {fpath}: {e}")
            continue

        # Each file should be a list of question objects
        if not isinstance(questions, list):
            logging.error(f"File {fname} does not contain a list of question objects.")
            continue

        file_results = {
            "source_file": fname,
            "questions_checked": []
        }

        for q_idx, qobj in enumerate(questions):
            qtext = qobj.get("question_text", "")
            difficulty = qobj.get("difficulty", "unknown")
            steps = qobj.get("solution_steps", [])

            question_passed = True
            step_verifications = []

            # Evaluate each step
            for s_idx, step in enumerate(steps):
                stype = step.get("step_type", "").lower()  # e.g. "factor", "expand", ...
                input_expr = step.get("input_expr", "")
                output_expr = step.get("output_expr", "")
                explanation = step.get("explanation", "")

                step_passed = True  # default

                # -------------------------------------
                # Decide how to check based on stype
                # -------------------------------------
                # Algebra checks (from checker_utils_algebra)
                if "factor" in stype:
                    step_passed = verify_factorization(input_expr, output_expr, var_list=["x"])
                
                elif "expand" in stype:
                    step_passed = verify_expansion(input_expr, output_expr, var_list=["x"])

                elif "solve polynomial" in stype or "poly solve" in stype:
                    # If we expect something like x^2 - 4 = 0, or just x^2 - 4,
                    # and the user gives "2, -2" as roots
                    step_passed = verify_polynomial_solution(input_expr, output_expr, var="x")

                elif "partial fraction" in stype:
                    step_passed = verify_partial_fraction(input_expr, output_expr, var="x")

                elif "series sum" in stype:
                    # e.g. if we define a step that says "Sum from n=1 to n of n -> n(n+1)/2"
                    # we might store input_expr as the term ("n") plus some notation for limits
                    # For now, let's assume the user sets them in a consistent format or that
                    # your pipeline extracts the lower/upper in separate fields
                    # Just do a naive example here:
                    step_passed = verify_series_sum(
                        term_expr=input_expr,
                        proposed_sum_expr=output_expr,
                        index_var="n",
                        lower_limit=1,
                        upper_limit="n"
                    )

                elif "inverse function" in stype:
                    # e.g. input_expr = "x^3", output_expr = "x^(1/3)"
                    step_passed = verify_inverse_function(input_expr, output_expr, var="x")

                # -------------
                # (In the future) Calculus checks
                # elif "derivative" in stype or "differentiat" in stype:
                #     step_passed = verify_derivative(input_expr, output_expr, var="x")

                # -------------
                # (In the future) Linear algebra checks
                # elif "matrix" in stype:
                #     step_passed = verify_matrix_equivalence(input_expr, output_expr)
                
                else:
                    # If we don't have a specialized check, we skip symbolic verification
                    step_passed = True

                # If step fails, log it
                if not step_passed:
                    question_passed = False
                    logging.error(
                        f"[{fname}] Q#{q_idx+1} step#{s_idx+1} (type={stype}) FAILED. "
                        f"Input='{input_expr}' -> Output='{output_expr}'"
                    )

                # Append step verification info
                step_verifications.append({
                    "step_type": stype,
                    "input_expr": input_expr,
                    "output_expr": output_expr,
                    "explanation": explanation,
                    "passed": step_passed
                })

            # Summarize results for this question
            file_results["questions_checked"].append({
                "question_index": q_idx + 1,
                "question_text": qtext,
                "difficulty": difficulty,
                "steps_verified": step_verifications,
                "verified": question_passed
            })

        # After processing all questions in this file, add to all_results
        all_results.append(file_results)

        # Write a *_check.json file
        outname = fname.replace(".json", "_check.json")
        outpath = os.path.join(output_dir, outname)
        with open(outpath, "w", encoding="utf-8") as fout:
            json.dump(file_results, fout, indent=2)
        print(f"Checked {fname} -> {outname}")

    # Optionally, write a single aggregated results file
    aggregated_path = os.path.join(output_dir, "ALL_CHECK_RESULTS.json")
    with open(aggregated_path, "w", encoding="utf-8") as fout:
        json.dump(all_results, fout, indent=2)

    print("✅ Checker complete. See 'checker.log' and 'levels_check/' for verification outputs.")


if __name__ == "__main__":
    main()
