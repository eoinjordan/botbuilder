# SPDX-License-Identifier: MIT
"""Run the digital assembly test.

Writes reports/assembly.json, docs/assembly.md and docs/images/*.png. Needs
the STLs in stl (scripts/fetch_stls.py).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from microduck import model, report  # noqa: E402

if __name__ == "__main__":
    if not model.have_stls():
        sys.exit("STLs not found in stl: run scripts/fetch_stls.py first")
    result = report.run()
    for finding in result["findings"]:
        print(f"{finding['level']}: {finding['text']}")
