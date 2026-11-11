# SPDX-License-Identifier: MIT
"""Recordings of the motion study as small GIFs (MuJoCo offscreen renderer,
collision boxes; the flat soles of the comparison preset are drawn in orange)."""
from __future__ import annotations

from dataclasses import replace

import mujoco
from PIL import Image

from . import motion_experiments as mx
from . import motiongen, motionsim, variant
from .protocol import ROOT

SIZE = (288, 216)


class Recorder:
    def __init__(self, sim: motionsim.MotionSim, every_ticks: int, azimuth: float = 125.0):
        self.sim, self.every, self.count, self.frames = sim, every_ticks, 0, []
        self.renderer = mujoco.Renderer(sim.model, SIZE[1], SIZE[0])
        self.camera = mujoco.MjvCamera()
        self.camera.distance, self.camera.azimuth, self.camera.elevation = 0.62, azimuth, -12.0
        self.option = mujoco.MjvOption()
        self.lookat = None

    def __call__(self, sim) -> None:
        if self.count % self.every == 0:
            # the camera follows slowly, so the floor pattern does not jump from frame to frame
            pos = sim.data.xpos[sim.torso]
            want = [pos[0] + 0.04, pos[1], 0.085]
            self.lookat = want if self.lookat is None else [a + 0.1 * (b - a) for a, b in zip(self.lookat, want)]
            self.camera.lookat[:] = self.lookat
            self.renderer.update_scene(sim.data, self.camera, self.option)
            self.frames.append(Image.fromarray(self.renderer.render()))
        self.count += 1

    def save(self, name: str, frame_ms: int, hold_last: int = 6) -> str:
        self.renderer.close()
        path = ROOT / "docs" / "images" / name
        first = self.frames[0].quantize(colors=24, method=Image.MEDIANCUT, dither=Image.Dither.NONE)
        rest = [f.quantize(palette=first, dither=Image.Dither.NONE) for f in self.frames[1:]]
        rest += [rest[-1]] * hold_last
        first.save(path, save_all=True, append_images=rest, duration=frame_ms, loop=0, optimize=True)
        return f"images/{name}"


def record_all(gaits: dict, firmware: dict) -> dict:
    out = {}
    for preset in mx.PRESETS:
        g = gaits[preset]
        tag = preset.replace("_", "-")
        for label, turn in ((("walk", 0.0), ("turn", 1.0)) if preset == mx.DEFAULT else (("walk", 0.0),)):
            sim = motionsim.MotionSim(preset)
            rec = Recorder(sim, 6)
            motionsim.run(sim, mx.walk_trajectory(sim.cal, g["walk"], 7.0, 1.0, turn)[0], on_tick=rec)
            out[f"{preset}_{label}"] = rec.save(f"motion-{tag}-{label}.gif", 120)
        if preset != mx.DEFAULT:
            continue            # the comparison preset: its walk only
        # the jump at one fifth speed: every 20 ms tick shown for 100 ms
        speed = firmware["jump_max_speed_deg_s"]["value"]
        cal = replace(variant.calibration(preset), max_speed_deg_s=float(speed))
        sim = motionsim.MotionSim(preset, cal=cal)
        trajectory, t_push = motiongen.jump(cal.stand_deg, g["jump"]["params"], speed, cal=cal)
        rec = Recorder(sim, 1, azimuth=100.0)
        window = [(t, q) for t, q in trajectory if t <= (t_push + 0.9) * 1000]
        start = int((t_push - 0.3) * 1000)
        motionsim.run(sim, window, on_tick=lambda s: rec(s) if s.now_ms >= start else None)
        out[f"{preset}_jump"] = rec.save(f"motion-{tag}-jump.gif", 100)
        # sit, servos off, stand up
        sim = motionsim.MotionSim(preset)
        rec = Recorder(sim, 5)
        down, up = mx.sit_trajectories(sim.cal)
        motionsim.run(sim, down, on_tick=rec)
        sim.send("R", delayed=False)
        for _ in range(75):
            sim.tick()
            rec(sim)
        sim.send("E", delayed=False)
        start_ms = sim.now_ms
        motionsim.run(sim, [(t + start_ms, q) for t, q in up], on_tick=rec)
        out[f"{preset}_sit"] = rec.save(f"motion-{tag}-sit.gif", 100)
    return out
