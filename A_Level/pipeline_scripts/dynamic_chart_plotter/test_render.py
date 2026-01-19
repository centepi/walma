# pipeline_scripts/dynamic_chart_plotter/test_render.py
"""
test_render.py — Tiny local renderer for JSON visual configs.

What it does:
- Loads every *.json in sample_visual_data/
- Calls dynamic_chart_plotter(config)
- Saves a PNG per file into render_out/
- Prints a pass/fail summary (and exits non-zero if any fail)

Run:
  python -m pipeline_scripts.dynamic_chart_plotter.test_render

Optional:
  python -m pipeline_scripts.dynamic_chart_plotter.test_render --in sample_visual_data --out render_out
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any, Dict, List, Tuple

# Force headless backend before importing pyplot anywhere
os.environ.setdefault("MPLBACKEND", "Agg")

import matplotlib  # noqa: E402

matplotlib.use("Agg")  # extra safety


def _load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise TypeError(f"Top-level JSON must be an object/dict: {path.name}")
    return data


def _safe_slug(name: str) -> str:
    keep = []
    for ch in name:
        if ch.isalnum() or ch in ("-", "_", "."):
            keep.append(ch)
        else:
            keep.append("_")
    return "".join(keep)


def _render_one(in_path: Path, out_dir: Path, dpi: int) -> Tuple[bool, str]:
    """
    Returns (ok, message). Always closes the figure.
    """
    fig = None
    try:
        config = _load_json(in_path)

        # Import here so MPLBACKEND is set first.
        from .plotter import dynamic_chart_plotter  # type: ignore

        fig = dynamic_chart_plotter(config)

        out_name = _safe_slug(in_path.stem) + ".png"
        out_path = out_dir / out_name

        # Save with tight bounding box to avoid random whitespace, but keep simple.
        fig.savefig(out_path, dpi=dpi, bbox_inches="tight")
        return True, f"OK  -> {out_path.name}"

    except Exception as e:
        tb = traceback.format_exc()
        return False, f"FAIL -> {in_path.name}: {e}\n{tb}"

    finally:
        try:
            if fig is not None:
                fig.clf()
        except Exception:
            pass
        try:
            import matplotlib.pyplot as plt  # noqa: E402

            plt.close("all")
        except Exception:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Render sample JSON visual configs to PNGs.")
    parser.add_argument(
        "--in",
        dest="in_dir",
        default=str(Path(__file__).parent / "sample_visual_data"),
        help="Folder containing *.json configs (default: sample_visual_data next to this file).",
    )
    parser.add_argument(
        "--out",
        dest="out_dir",
        default=str(Path(__file__).parent / "render_out"),
        help="Output folder for PNGs (default: render_out next to this file).",
    )
    parser.add_argument("--dpi", dest="dpi", type=int, default=180, help="PNG dpi (default: 180).")
    args = parser.parse_args()

    in_dir = Path(args.in_dir).expanduser().resolve()
    out_dir = Path(args.out_dir).expanduser().resolve()
    dpi = int(args.dpi)

    if not in_dir.exists() or not in_dir.is_dir():
        print(f"Input folder not found: {in_dir}")
        return 2

    out_dir.mkdir(parents=True, exist_ok=True)

    json_files = sorted(in_dir.glob("*.json"))
    if not json_files:
        print(f"No *.json files found in: {in_dir}")
        return 0

    print(f"Rendering {len(json_files)} file(s)")
    print(f"  in : {in_dir}")
    print(f"  out: {out_dir}")
    print("")

    ok_count = 0
    fail_count = 0
    failed: List[str] = []

    for p in json_files:
        ok, msg = _render_one(p, out_dir, dpi)
        if ok:
            ok_count += 1
            print(msg)
        else:
            fail_count += 1
            failed.append(p.name)
            print(msg)

    print("")
    print("Summary")
    print("-------")
    print(f"Passed: {ok_count}")
    print(f"Failed: {fail_count}")
    if failed:
        print("Failed files:")
        for f in failed:
            print(f"  - {f}")

    return 1 if fail_count > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())