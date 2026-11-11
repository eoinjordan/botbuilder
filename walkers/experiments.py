# SPDX-License-Identifier: MIT
"""Simulation experiments on the two crank walkers.

    python -m walkers.experiments [--no-recordings]

Writes reports/lego/sim.json and the recordings in docs/images/.
"""
from __future__ import annotations

import argparse
import json
import sys

import mujoco
import numpy as np
from PIL import Image

from . import model, sim
from .model import BUILDS, ROOT

REPORT = ROOT / "reports" / "lego" / "sim.json"
IMAGES = ROOT / "docs" / "images"
WALK_RPM = 60.0
KEYS = ("fell", "fell_how", "fell_at_s", "distance_forward_m", "speed_mm_s", "slip_fraction", "drift_left_m",
        "yaw_change_deg", "max_roll_deg", "max_pitch_deg", "max_tilt_deg", "phase_gap_error_deg", "torque", "feet")


def brief(result: dict, extra: dict | None = None) -> dict:
    out = {k: result[k] for k in KEYS}
    out.update(extra or {})
    return out


def forward(build: str) -> dict:
    s = sim.WalkerSim(build)
    top = s.meta["motor"]["no_load_rpm"]
    rows = []
    for rpm in (15, 30, 45, 60, 75, 90, 105, 120, 135, 150, top):
        s.reset()
        r = sim.run(s, sim.constant(rpm), 10.0)
        rows.append(brief(r, {"rpm": rpm, "ideal_speed_mm_s": round(rpm / 60.0 * model.STRIDE, 1)}))
    steady = [r for r in rows if not r["fell"] and r["max_tilt_deg"] < 3.0 and abs(r["yaw_change_deg"]) < 5.0
              and r["feet"]["none_fraction"] < 0.01]
    best = max(steady, key=lambda r: r["rpm"]) if steady else None
    return {"runs": rows, "duration_s": 10.0,
            "fastest_steady_rpm": best["rpm"] if best else None,
            "fastest_steady_speed_mm_s": best["speed_mm_s"] if best else None,
            "steady_means": "no fall, tilt under 3 degrees, heading change under 5 degrees in 10 s, a foot always down"}


def friction(build: str) -> list:
    rows = []
    for mu in model.load_json("components.json")["floor"]["friction_sensitivity"] + [0.1, 0.05]:
        s = sim.WalkerSim(build, friction=mu)
        r = sim.run(s, sim.constant(WALK_RPM), 10.0)
        rows.append(brief(r, {"friction": mu, "foot_sliding_m": r["foot_sliding_m"]}))
    return sorted(rows, key=lambda r: -r["friction"])


def turning(build: str) -> list:
    """One side slower, stopped or reversed. The legs drift out of phase
    opposition whenever the two speeds differ."""
    rows = []
    for right in (45.0, 30.0, 0.0, -60.0):
        s = sim.WalkerSim(build)
        r = sim.run(s, sim.constant(WALK_RPM, right), 12.0)
        rows.append(brief(r, {"left_rpm": WALK_RPM, "right_rpm": right,
                              "yaw_rate_deg_s": round(r["yaw_change_deg"] / 12.0, 2)}))
    return rows


def start_stop(build: str) -> dict:
    out = {}
    s = sim.WalkerSim(build)
    r = sim.run(s, sim.constant(WALK_RPM, ramp_s=0.0), 4.0, settle_s=0.0)
    out["step_start"] = brief(r, {"what": "from rest to 60 rpm with no ramp"})
    for label, stop_at in (("stop_mid_stance", 3.0), ("stop_at_handover", 3.25)):
        s = sim.WalkerSim(build)
        track = []
        r = sim.run(s, sim.constant(WALK_RPM, stop_at_s=stop_at), 6.0, settle_s=0.0,
                    on_tick=lambda q: track.append((q.time, float(q.data.xpos[q.chassis][0]), q.tilt_deg())))
        t = np.array(track)
        after = t[t[:, 0] >= stop_at]
        out[label] = brief(r, {"what": f"walk at 60 rpm, command zero speed at {stop_at} s and hold",
                               "coast_after_stop_mm": abs(round(float((after[-1, 1] - after[0, 1]) * 1000), 1)),
                               "max_tilt_after_stop_deg": round(float(after[:, 2].max()), 2),
                               "tilt_at_end_deg": round(float(after[-1, 2]), 2)})
    return out


def _walks(r: dict) -> bool:
    return (not r["fell"]) and r["slip_fraction"] is not None and r["slip_fraction"] < 0.5 and r["max_tilt_deg"] < 15.0


def slopes(build: str) -> dict:
    out = {}
    for label, key, sign in (("uphill", "uphill_deg", 1), ("downhill", "uphill_deg", -1),
                             ("left_side_high", "left_high_deg", 1), ("right_side_high", "left_high_deg", -1)):
        rows, limit = [], 0
        for angle in range(2, 31, 2):
            s = sim.WalkerSim(build)
            s.set_slope(**{key: sign * angle})
            s.reset()
            r = sim.run(s, sim.constant(WALK_RPM), 8.0)
            ok = _walks(r)
            rows.append({"deg": angle, "walks": ok, **{k: r[k] for k in ("fell", "fell_how", "speed_mm_s", "slip_fraction", "max_tilt_deg")}})
            if not ok:
                break
            limit = angle
        out[label] = {"steepest_walked_deg": limit, "runs": rows}
    out["note"] = ("Slope by tilting gravity. Walks means: no fall, tilt under 15 degrees from the slope, and at least "
                   "half the ideal distance. Friction 0.4.")
    return out


def steps(build: str) -> dict:
    rows, limit = [], 0
    for height in range(2, 25, 2):
        s = sim.WalkerSim(build)
        s.set_step(0.14, height / 1000.0)
        s.reset()
        r = sim.run(s, sim.constant(WALK_RPM), 14.0)
        over = (not r["fell"]) and r["distance_forward_m"] > 0.30 and r["height_range_mm"][1] > 96.0 + 0.8 * height
        rows.append({"height_mm": height, "climbed": over, **{k: r[k] for k in ("fell", "fell_how", "distance_forward_m", "max_tilt_deg")}})
        if not over:
            break
        limit = height
    return {"highest_climbed_mm": limit, "runs": rows,
            "note": "A square step across the path, 140 mm ahead of the axle row. The feet lift 24 mm at most."}


def phase_errors(build: str) -> dict:
    rows = []
    for error in (0, 5, 10, 20, 30, 45, 60, 90, 120, 150, 180):
        s = sim.WalkerSim(build)
        s.reset(phase_error_deg=error)
        r = sim.run(s, sim.constant(WALK_RPM), 10.0)
        rows.append(brief(r, {"phase_error_deg": error, "height_range_mm": r["height_range_mm"]}))
    base = rows[0]["speed_mm_s"]
    fine = [r["phase_error_deg"] for r in rows if not r["fell"] and r["speed_mm_s"] > 0.9 * base and r["max_tilt_deg"] < 3.0]
    tolerated = 0
    for r in rows:
        if r["phase_error_deg"] in fine:
            tolerated = r["phase_error_deg"]
        else:
            break
    return {"runs": rows, "tolerated_deg": tolerated,
            "tolerated_means": "no fall, at least 90 percent of the speed with no error, tilt under 3 degrees"}


def record(build: str, name: str, command, duration: float, setup=None, size=(320, 240), every=20) -> str:
    s = sim.WalkerSim(build)
    if setup:
        setup(s)
        s.reset()
    renderer = mujoco.Renderer(s.model, size[1], size[0])
    camera = mujoco.MjvCamera()
    # A fixed camera: the floor stays still, so the GIF stays small.
    camera.distance, camera.azimuth, camera.elevation = 0.95, 115.0, -18.0
    camera.lookat[:] = s.data.xpos[s.chassis] + [0.13, 0.0, -0.03]
    frames, count = [], [0]

    def grab(q):
        if count[0] % every == 0:
            renderer.update_scene(q.data, camera)
            frames.append(Image.fromarray(renderer.render()))
        count[0] += 1
    sim.run(s, command, duration, on_tick=grab)
    renderer.close()
    first = frames[0].quantize(colors=32, method=Image.MEDIANCUT, dither=Image.Dither.NONE)
    rest = [f.quantize(palette=first, dither=Image.Dither.NONE) for f in frames[1:]]
    path = IMAGES / name
    first.save(path, save_all=True, append_images=rest, duration=int(every * sim.CONTROL_DT * 1000), loop=0, optimize=True)
    return f"images/{name}"


def verdicts(build: str, r: dict) -> dict:
    f = r["forward"]
    walk = next(x for x in f["runs"] if x["rpm"] == WALK_RPM)
    top = f["runs"][-1]
    tq = walk["torque"]
    turn = r["turning"]
    out = {
        "walks": f"At {WALK_RPM:g} rpm it walks {walk['speed_mm_s']} mm/s in a straight line with {walk['slip_fraction'] * 100:.1f} "
                 f"percent slip, tilt under {walk['max_tilt_deg']} degrees. Peak motor torque {tq['peak_nm']} N m of "
                 f"{tq['stall_nm']} N m stall; mean {tq['mean_nm']} N m.",
        "speed": (f"Steady up to {f['fastest_steady_rpm']:g} rpm ({f['fastest_steady_speed_mm_s']} mm/s). "
                  if f["fastest_steady_rpm"] else "No speed met the steady criteria. ")
                 + f"At the motor's {top['rpm']:g} rpm: "
                 + (f"it falls {top['fell_how']} at {top['fell_at_s']} s." if top["fell"] else
                    f"{top['speed_mm_s']} mm/s, tilt up to {top['max_tilt_deg']} degrees, heading change {top['yaw_change_deg']} "
                    f"degrees, no foot on the floor {top['feet']['none_fraction'] * 100:.0f} percent of the time."),
        "turning": "; ".join(f"right side at {x['right_rpm']:g} rpm: heading {x['yaw_change_deg']} degrees in 12 s"
                             + (f", fell {x['fell_how']}" if x["fell"] else "") for x in turn) + ".",
        "slope": f"Steepest walked: {r['slopes']['uphill']['steepest_walked_deg']} degrees up, "
                 f"{r['slopes']['downhill']['steepest_walked_deg']} down, {r['slopes']['left_side_high']['steepest_walked_deg']} "
                 f"with the left side high, {r['slopes']['right_side_high']['steepest_walked_deg']} with the right side high.",
        "step": f"Highest step climbed: {r['steps']['highest_climbed_mm']} mm.",
        "phase": f"Phase error between the sides tolerated: {r['phase_errors']['tolerated_deg']} degrees.",
    }
    return out


def run_build(build: str, recordings: bool) -> dict:
    s = sim.WalkerSim(build)
    stand = sim.run(s, sim.constant(0.0), 5.0)
    result = {"build": build, "model": s.meta,
              "stand": brief(stand, {"height_range_mm": stand["height_range_mm"]}),
              "forward": forward(build), "friction": friction(build), "turning": turning(build),
              "start_stop": start_stop(build), "slopes": slopes(build), "steps": steps(build),
              "phase_errors": phase_errors(build)}
    result["verdict"] = verdicts(build, result)
    if recordings:
        top = s.meta["motor"]["no_load_rpm"]
        result["recordings"] = {
            "walk": record(build, f"lego-{build}-walk.gif", sim.constant(WALK_RPM), 6.0),
            "fast": record(build, f"lego-{build}-fast.gif", sim.constant(top), 5.0),
            "turn": record(build, f"lego-{build}-turn.gif", sim.constant(WALK_RPM, 0.0), 6.0),
        }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--no-recordings", action="store_true")
    args = parser.parse_args()
    report = {"_comment": "Generated by python -m walkers.experiments. MuJoCo, 1 ms step, control every 5 ms.",
              "status": "Simulation only. Neither walker has been assembled or powered.",
              "walk_rpm": WALK_RPM,
              "builds": {b: run_build(b, not args.no_recordings) for b in BUILDS}}
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8", newline="\n")
    for b in BUILDS:
        for k, v in report["builds"][b]["verdict"].items():
            print(f"{b} [{k}] {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
