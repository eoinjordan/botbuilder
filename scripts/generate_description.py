# SPDX-License-Identifier: MIT
"""Regenerate robot/microduck.urdf, robot/microduck.xml, robot/joints.json
and robot/model.json from the STLs and reports/assembly.json, and the
firmware's calibration table from config/calibration.json and the limits."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from microduck import describe, firmware_table, model  # noqa: E402

if __name__ == "__main__":
    if not model.have_stls():
        sys.exit("STLs not found in stl: run scripts/fetch_stls.py first")
    result = describe.generate()
    print("collision boxes per link:", result["boxes"])
    print("stand pose (deg):", result["table"]["stand_pose_deg"])
    print("firmware table:", firmware_table.write())
