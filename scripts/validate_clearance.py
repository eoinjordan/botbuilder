# SPDX-License-Identifier: MIT
"""Check the controller's leg clearance rule against the meshes.

    python scripts/validate_clearance.py [--uniform 3000] [--near 3000] [--per-joint 120]

Samples joint poses inside the soft limits, tests each with the exact mesh
interference of microduck/assembly.py (thigh plate, knee servo and shin of one
leg against those of the other) and with protocol.legs_clear(), and writes
reports/clearance.json. A false accept is a fault in the rule; the script
exits with an error if there is one. Takes a few minutes.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from microduck import clearance  # noqa: E402

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--uniform", type=int, default=3000)
    parser.add_argument("--near", type=int, default=3000)
    parser.add_argument("--per-joint", type=int, default=120)
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()
    result = clearance.validate(args.seed, args.uniform, args.near, args.per_joint,
                                progress=lambda name, k: print(f"  {name}: {k}", flush=True))
    result["generated_by"] = "scripts/validate_clearance.py"
    for name, counts in result["sets"].items():
        print(name, counts)
    print("total", result["total"])
    if not args.no_write:
        (ROOT / "reports" / "clearance.json").write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8", newline="\n")
    sys.exit(1 if result["total"]["false_accepts"] else 0)
