# SPDX-License-Identifier: MIT
"""Search for the gait and the jump of the motion study and write
config/gaits.json and config/gait_motion.json.

    python scripts/optimise_motion.py [--only comb.walk ...] [--workers 7]

Seeded CMA-ES (microduck/cmaes.py) on the model of microduck/motionsim.py.
Bounded two ways: a fixed number of generations per search (which makes the
result repeatable) and a wall-clock budget per search as a backstop. The whole
run takes about 20 minutes on eight cores of a laptop without a GPU. Check
the free disk space before a long run; the search itself writes two small
files.

The walking gait is the one of microduck/gait.py, so the result is a set of
its parameters. The comb robot's set is also written to
config/gait_motion.json in the format of config/gait.json, which is the file
trajectories/manifest.json names for the control page.
"""
import argparse
import json
import multiprocessing
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from microduck import gait, gaitsearch, motiongen, variant  # noqa: E402

# what, preset, kind, seed, generations, population, wall-clock budget (s)
PLAN = [
    ("comb.walk", "comb", "gait", 1, 40, 14, 1200.0),
    ("comb.jump", "comb", "jump", 1, 40, 14, 600.0),
    ("flat_feet.walk", "flat_feet", "gait", 1, 30, 14, 1200.0),
    ("flat_feet.jump", "flat_feet", "jump", 1, 40, 14, 600.0),
]
SPACE = {"gait": motiongen.GAIT_SPACE, "jump": motiongen.JUMP_SPACE}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--only", nargs="*", help="searches to run, e.g. comb.walk flat_feet.jump (default: all)")
    parser.add_argument("--workers", type=int, default=max(1, multiprocessing.cpu_count() - 1))
    args = parser.parse_args()
    path = ROOT / "config" / "gaits.json"
    doc = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    doc = {k: v for k, v in doc.items() if k in ("comb", "flat_feet", "search")}
    jump_speed = variant.load_json("motion.json")["firmware"]["jump_max_speed_deg_s"]["value"]
    for what, preset, kind, seed, generations, popsize, budget in PLAN:
        if args.only and what not in args.only:
            continue
        print(f"{what}: seed {seed}, {generations} generations of {popsize}", flush=True)
        # the gait search starts from the repository's default gait (config/gait.json)
        start = None
        if kind == "gait":
            default = gait.load_params()
            start = [(default[name] - lo) / (hi - lo) for name, lo, hi in motiongen.GAIT_SPACE]
        result = gaitsearch.search(kind, preset, seed, generations, popsize, budget, args.workers, x0=start, sigma0=0.2 if start else 0.25,
                                   max_speed=jump_speed if kind == "jump" else None,
                                   progress=lambda g, f, best, sigma: print(f"  {g:3d} {f:8.3f} {best:8.3f} {sigma:.3f}", flush=True) if g % 5 == 0 else None)
        params = {k: round(v, 2) for k, v in motiongen.from_unit(SPACE[kind], result["x"]).items()}
        if "period_s" in params:
            params["period_s"] = round(round(params["period_s"] / 0.02) * 0.02, 2)     # a whole number of 20 ms ticks
            params["lead_in_s"] = gaitsearch.LEAD_IN_S
        entry = {"kind": "gait" if kind == "gait" else "jump", "params": params,
                 "search": {"method": "CMA-ES, microduck/cmaes.py", "seed": seed, "generations": result["generations"],
                            "population": popsize, "candidates": result["evaluations"],
                            "simulated_runs": result["evaluations"] * result["runs_per_candidate"],
                            "wall_clock_s": result["seconds"], "wall_clock_budget_s": budget, "workers": args.workers,
                            "score": round(result["score"], 3), "best_score_by_generation": result["history"]}}
        doc.setdefault(preset, {})[what.split(".")[1]] = entry
        searches = [doc[p][m]["search"] for p in doc if p != "search" for m in doc[p]]
        doc["search"] = {"scenarios": [{"floor_friction": mu, "mass_scale": mass, "start_tilt_deg": list(tilt), "start_push_m_s": list(push)}
                                       for mu, mass, tilt, push in gaitsearch.SCENARIOS],
                         "straight_run_s": gaitsearch.SEARCH_SECONDS, "turn_run_s": gaitsearch.TURN_SECONDS, "turn_input": gaitsearch.TURN_INPUT,
                         "total_candidates": sum(s["candidates"] for s in searches),
                         "total_simulated_runs": sum(s["simulated_runs"] for s in searches),
                         "total_wall_clock_s": round(sum(s["wall_clock_s"] for s in searches), 1)}
        path.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8", newline="\n")
        if what == "comb.walk":
            tuned = {"_comment": "Open-loop gait parameters (microduck/gait.py) found by scripts/optimise_motion.py for the comb soles. "
                                "Angles in degrees. Same format as config/gait.json.", **params}
            (ROOT / "config" / "gait_motion.json").write_text(json.dumps(tuned, indent=2) + "\n", encoding="utf-8", newline="\n")
        print(f"  score {result['score']:.3f} in {result['seconds']} s: {params}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
