# SPDX-License-Identifier: MIT
"""Record simulation runs as GIFs with MuJoCo's offscreen renderer.

Uses build/microduck_visual.xml (the STLs as visuals) when the STLs are
present, otherwise the primitive model. The physics is the same either way.
"""
from __future__ import annotations

from pathlib import Path

import mujoco
from PIL import Image

from . import gait, model, sim
from .protocol import ROOT

SIZE = (400, 300)
FRAME_EVERY_TICKS = 5       # 100 ms per frame


def _xml() -> Path:
    visual = ROOT / "build" / "microduck_visual.xml"
    return visual if visual.is_file() and model.have_stls() else ROOT / "robot" / "microduck.xml"


def record(pose: str, trajectory: list, path: Path, hold_last: int = 8) -> str:
    s = sim.DuckSim(_xml())
    s.reset(pose)
    renderer = mujoco.Renderer(s.model, SIZE[1], SIZE[0])
    camera = mujoco.MjvCamera()
    camera.lookat[:] = s.torso_pos() + [0.14, 0.0, -0.07]
    camera.distance, camera.azimuth, camera.elevation = 0.72, 125.0, -14.0
    frames, count = [], [0]

    def grab(_sim):
        if count[0] % FRAME_EVERY_TICKS == 0:
            renderer.update_scene(s.data, camera)
            frames.append(Image.fromarray(renderer.render()))
        count[0] += 1

    sim.play(s, trajectory, on_tick=grab)
    renderer.close()
    first = frames[0].quantize(colors=48, method=Image.MEDIANCUT, dither=Image.Dither.NONE)
    rest = [f.quantize(palette=first, dither=Image.Dither.NONE) for f in frames[1:]]
    rest += [rest[-1]] * hold_last
    path.parent.mkdir(parents=True, exist_ok=True)
    first.save(path, save_all=True, append_images=rest, duration=FRAME_EVERY_TICKS * 20, loop=0, optimize=True)
    return f"images/{path.name}"


def record_all(results: dict) -> dict:
    images = ROOT / "docs" / "images"
    cal = sim.DuckSim().cal
    out = {"gait": record("stand", gait.gait(cal.stand_deg, results["gait_default"]["params"], 8.0), images / "sim-gait.gif"),
           "neutral": record("neutral", gait.stand([0.0] * 6, 1.6), images / "sim-neutral-fall.gif")}
    if "gait_best" in results:
        out["gait_best"] = record("stand", gait.gait(cal.stand_deg, results["gait_best"]["params"], 8.0), images / "sim-gait-best.gif")
    return out
