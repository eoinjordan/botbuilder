# SPDX-License-Identifier: MIT
"""Copy the printable STLs from the local design directory into build/stl.

The STLs are derived from third-party Microduck meshes whose licence is not
settled (see NOTICE), so they are not part of this repository. This script
reads them from the owner's design directory and records their checksums.

    python scripts/fetch_stls.py [--design-dir PATH]

The design directory defaults to $MICRODUCK_DESIGN_DIR, then to
../3d-print-designs/microduck-braccio-unoq next to this repository.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from microduck.model import FIT_FILES, OTHER_FILES, PART_FILES  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    default = os.environ.get("MICRODUCK_DESIGN_DIR", ROOT.parent / "3d-print-designs" / "microduck-braccio-unoq")
    parser.add_argument("--design-dir", type=Path, default=Path(default))
    args = parser.parse_args()
    source = args.design_dir / "stl"
    if not source.is_dir():
        print(f"no stl directory under {args.design_dir}", file=sys.stderr)
        return 1
    target = ROOT / "build" / "stl"
    target.mkdir(parents=True, exist_ok=True)
    sums = {}
    for name in sorted(set(list(PART_FILES.values()) + list(FIT_FILES.values()) + OTHER_FILES)):
        if not (source / name).is_file():
            print(f"missing {name}", file=sys.stderr)
            return 1
        shutil.copyfile(source / name, target / name)
        sums[name] = hashlib.sha256((target / name).read_bytes()).hexdigest()
    (target / "SHA256SUMS.json").write_text(json.dumps(sums, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"copied {len(sums)} files to {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
