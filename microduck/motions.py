# SPDX-License-Identifier: MIT
"""The motions the control page may offer, as a manifest.

The control page does not invent motions. It reads a manifest of named
trajectories and the limits of the parametric gait, and shows anything that
is missing as disabled with the reason.

trajectories/manifest.json, when present, is that manifest:

    {
      "version": 1,
      "gait": {"params": "config/gait.json",
               "forward": [min, max],     scale of step_amplitude_deg, inside -1..1
               "turn": [min, max]},       difference in step scale between the legs, inside -1..1
      "motions": {"<name>": {"file": "trajectories/<file>.csv", "label": "..."}},
      "unavailable": {"<name>": "<reason>"}
    }

Names the page knows: stand, sit, jump. A trajectory file is the CSV of
microduck/gait.py. A file that is missing, malformed, outside the joint limits
or over the speed limit is moved to "unavailable" with the reason.

Without the file the manifest is built from what the repository has: the
stand trajectory and the default forward gait.

Standard library only: scripts/build_site.py imports this.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from . import gait, protocol

ROOT = protocol.ROOT
MANIFEST = Path("trajectories") / "manifest.json"
ACTIONS = ("stand", "sit", "jump")
HEAD_REASON = "no head joints: this robot has six leg joints and a fixed camera mount"


def builtin_manifest() -> dict:
    return {
        "version": 1,
        "source": "built in (no trajectories/manifest.json)",
        "gait": {"params": "config/gait.json", "forward": [0.0, 1.0], "turn": [0.0, 0.0]},
        "motions": {"stand": {"file": "trajectories/stand.csv", "label": "Stand"}},
        "unavailable": {
            "back": "only the forward gait has been simulated; no backward range in the motion manifest",
            "turn": "the default gait has no turn parameter and the robot has no hip yaw joint",
            "sit": "no sit trajectory in the repository yet",
            "jump": "no jump trajectory in the repository yet",
        },
    }


def _range(value, name: str) -> list:
    if (not isinstance(value, list) or len(value) != 2
            or not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in value)):
        raise ValueError(f"gait.{name} must be [min, max]")
    low, high = float(value[0]), float(value[1])
    if not -1.0 <= low <= 0.0 <= high <= 1.0:
        raise ValueError(f"gait.{name} must satisfy -1 <= min <= 0 <= max <= 1")
    return [low, high]


def _inside(root: Path, relative: str, folder: str) -> Path:
    if not isinstance(relative, str) or "\\" in relative or relative.startswith("/"):
        raise ValueError(f"bad path {relative!r}")
    path = (root / relative).resolve()
    if not path.is_relative_to((root / folder).resolve()):
        raise ValueError(f"{relative} is not under {folder}/")
    return path


def load_manifest(root: Path = ROOT, cal: protocol.Calibration | None = None) -> dict:
    """The manifest as the page reads it: checked, with the gait parameters
    and the robot's limits filled in. Raises ValueError on a malformed file."""
    path = root / MANIFEST
    if path.is_file():
        with open(path, encoding="utf-8") as handle:
            raw = json.load(handle)
        source = MANIFEST.as_posix()
    else:
        raw = builtin_manifest()
        source = raw["source"]
    if not isinstance(raw, dict) or raw.get("version") != 1:
        raise ValueError("manifest version must be 1")
    cal = cal or protocol.load_calibration(root / "config" / "calibration.json", root / "robot" / "joints.json")
    with open(root / "config" / "calibration.json", encoding="utf-8") as handle:
        allow_jump = json.load(handle).get("allow_jump") is True

    gait_raw = raw.get("gait") or {}
    params_path = _inside(root, gait_raw.get("params", "config/gait.json"), "config")
    params = {k: v for k, v in gait.load_params(params_path).items() if not k.startswith("_")}
    forward = _range(gait_raw.get("forward", [0.0, 1.0]), "forward")
    turn = _range(gait_raw.get("turn", [0.0, 0.0]), "turn")

    unavailable = {str(k): str(v) for k, v in (raw.get("unavailable") or {}).items()}
    motions = {}
    for name, entry in (raw.get("motions") or {}).items():
        if name not in ACTIONS:
            unavailable[name] = "not a motion the control page knows"
            continue
        try:
            file = _inside(root, entry["file"], "trajectories")
            rows = gait.read_csv(file)
            problems = gait.check_limits(rows, cal)
            if problems:
                t, joint, what = problems[0]
                raise ValueError(f"{len(problems)} rows outside the limits, first at {t} ms on {joint}: {what}")
            if not rows:
                raise ValueError("no rows")
        except (OSError, KeyError, TypeError, ValueError) as error:
            unavailable[name] = f"trajectory not playable: {error}"
            continue
        motions[name] = {"label": str(entry.get("label", name.capitalize())), "file": f"trajectories/{file.name}",
                         "duration_ms": rows[-1][0], "source": file.relative_to(root.resolve()).as_posix()}
        unavailable.pop(name, None)
    for name in ACTIONS:
        if name not in motions:
            unavailable.setdefault(name, f"no {name} trajectory in the motion manifest")
    if forward[0] == 0.0:
        unavailable.setdefault("back", "no backward range in the motion manifest")
    if turn == [0.0, 0.0]:
        unavailable.setdefault("turn", "no turn range in the motion manifest")
    unavailable["head"] = HEAD_REASON
    return {
        "version": 1,
        "source": source,
        "gait": {"forward": forward, "turn": turn, "params": params},
        "motions": motions,
        "unavailable": unavailable,
        "robot": {"max_speed_deg_s": cal.max_speed_deg_s, "watchdog_ms": cal.watchdog_ms,
                  "watchdog_action": cal.watchdog_action, "allow_jump": allow_jump,
                  "stand_deg": list(cal.stand_deg),
                  "limits_deg": [[j.min_deg, j.max_deg] for j in cal.joints]},
    }


def export(data_dir: Path, root: Path = ROOT) -> dict:
    """Write motions.json and the trajectories it names under data_dir."""
    manifest = load_manifest(root)
    folder = data_dir / "trajectories"
    folder.mkdir(parents=True, exist_ok=True)
    for entry in manifest["motions"].values():
        shutil.copyfile(root / entry["source"], data_dir / entry["file"])
    (data_dir / "motions.json").write_text(json.dumps(manifest, separators=(",", ":")), encoding="utf-8", newline="\n")
    return manifest
