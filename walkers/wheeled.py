# SPDX-License-Identifier: MIT
"""Wheeled variants of every controller base: two driven wheels on the rear
axle line of the walker chassis and a third support under the forward shelf.

    python -m walkers.wheeled [--no-recordings]

Writes reports/wheeled/analysis.json, reports/wheeled/sim.json, one MuJoCo
model per variant in robot/lego/wheeled/ and the recordings in docs/images/.

"Wheels at the back" drives toward the support (the head's usual way round);
"wheels at the front" is the same build with the head pinned on facing the
other way and the drive reversed.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass

import mujoco
import numpy as np
import trimesh
from PIL import Image

from . import model
from .model import ROOT, STL

REPORTS = ROOT / "reports" / "wheeled"
MODELS = ROOT / "robot" / "lego" / "wheeled"
IMAGES = ROOT / "docs" / "images"
G = 9.81
MM = 0.001
CONTROL_DT = 0.005
POST_CLASS = {"d43": 43.2, "d56": 56.0, "d65": 65.0}
ENDS = ("back", "front")
SUPPORTS = ("skid", "ball")
# Option ids the configurator uses (config/compat.json).
CONTROLLER_ID = {"ev3": "ev3", "pi_buildhat": "pi", "hub51515": "hub51515", "m5_basex": "m5core", "unoq": "unoq", "pi": "pi"}
DRIVE_ID = {("ev3", "ev3_large"): "ev3_motors", ("pi_buildhat", "angular"): "buildhat_51515", ("hub51515", "angular"): "hub_motors",
            ("m5_basex", "ev3_large"): "basex_ev3", ("m5_basex", "servo360"): "m5_360_wheels", ("unoq", "servo360"): "m5_360_wheels",
            ("unoq", "tt"): "tt_hbridge", ("pi", "servo360"): "m5_360_wheels", ("pi", "tt"): "tt_hbridge"}
WHEEL_ID = {"LEGO": "lego", "TT stock": "tt65", "printed solid with O-ring or band": "printed_ring", "printed hub with TPU tyre": "printed_tpu"}
SUPPORT_ID = {"skid": "skid", "ball": "roller"}


def config() -> dict:
    return model.load_json("wheeled.json")


def _print_mass(folder: str, name: str, printing: dict, density: float | None = None, fraction: float | None = None):
    mesh = trimesh.load_mesh(STL / folder / f"{name}.stl")
    d = density or printing["density_g_cm3"]["value"]
    f = fraction or printing["solid_fraction"]["value"]
    return float(mesh.volume / 1000.0 * d * f), np.asarray(mesh.center_mass, float)


def post_size(diameter: float) -> str:
    return min(POST_CLASS, key=lambda k: abs(POST_CLASS[k] - diameter))


@dataclass
class Variant:
    id: str
    base: str
    drive: str
    wheel: str
    support: str
    end: str
    tyre: str           # friction key of the tread
    items: list         # (name, kind, mass_g, xyz mm)
    radius: float       # rolling radius, mm
    half_track: float   # mm
    width: float        # wheel width, mm
    wheel_mass: float   # g, each
    motor: dict         # stall_nm, no_load_rpm, feedback, rotor, stall_current_a
    mu: dict            # wheel, support, rolling

    def mass(self) -> float:
        return float(sum(i[2] for i in self.items))

    def com(self) -> np.ndarray:
        return sum(i[2] * np.asarray(i[3], float) for i in self.items) / self.mass()


def default_wheel(cfg: dict, base: str, drive: str) -> str:
    return cfg["bases"][base]["wheels"][drive][0]


def build(base: str, drive: str, wheel: str | None = None, support: str = "skid", end: str = "back",
          bare: bool = False) -> Variant:
    cfg, comp = config(), model.load_json("components.json")
    printing = comp["printing"]
    b = cfg["bases"][base]
    d = cfg["drives"][drive]
    wheel = wheel or default_wheel(cfg, base, drive)
    w = cfg["wheels"][wheel]
    geo = cfg["geometry"]
    ax = geo["axle_x_mm"]
    radius = w["diameter_mm"] / 2.0
    if bare:                                    # no ring fitted: it rolls on the plastic rim
        radius -= 1.0
    items = []
    chassis = b["chassis"]
    mass, com = _print_mass(chassis, "chassis", printing)
    items.append(("chassis", "print", mass, com))
    head = model.trans(model.HEAD_X, 0.0, model.SHELF_TOP) @ model.rot("z", 180.0 if end == "front" else 0.0)
    mass, com = _print_mass(chassis, b["head"], printing)
    items.append(("head", "print", mass, (head @ np.append(com, 1.0))[:3]))
    if b["camera"] == "pantilt":
        items.append(("pan-tilt kit", "camera", comp["pixy2_pan_tilt"]["mass_g"]["value"], (head @ [8.0, 0.0, 90.0, 1.0])[:3]))
        items.append(("Pixy2", "camera", comp["pixy2"]["mass_g"]["value"], (head @ [27.5, 0.0, 131.0, 1.0])[:3]))
    elif b["camera"] == "camera_module_2":
        items.append(("Camera Module 2", "camera", comp["camera_module_2"]["mass_g"]["value"], (head @ [31.5, 0.0, 55.0, 1.0])[:3]))
    ctrl = b["controller"]
    z0 = 47.0 if chassis.startswith("pi") else model.DECK_TOP
    items.append((ctrl["name"], "controller", ctrl["mass_g"], (0.0, 0.0, z0 + ctrl["size_mm"][2] / 2.0)))
    for extra in b["extra"]:
        items.append((extra["name"], "battery", extra["mass_g"], tuple(extra["at_mm"])))

    if "components_key" in d:
        spec = comp[d["components_key"]]
        motor = {"stall_nm": spec["stall_torque_nm"]["value"], "no_load_rpm": spec["no_load_rpm"]["value"],
                 "rotor": spec["rotor_inertia_kgm2"]["value"], "closed_loop": True}
        for side, sign in (("left", 1.0), ("right", -1.0)):
            item = model.motor_item(f"{side} motor", spec, "forward", sign * d["y_centre_mm"], ax)
            items.append((item.name, "motor", item.mass_g, item.com_world()))
            items.append((f"{side} axle, bushes and bracket", "technic", comp["technic"]["motor_bracket_g"]["value"] + 2.0,
                          (ax, sign * 50.0, 0.0)))
        half_track = model.PANEL_OUT + 3.0 + w["width_mm"] / 2.0
        lowest = min(spec["envelope"]["hub"][0][2], spec["envelope"]["body"][0][2], geo["panel_bottom_mm"])
    else:
        motor = {"stall_nm": d["stall_torque_nm"]["value"], "no_load_rpm": d["no_load_rpm"]["value"],
                 "rotor": d["rotor_inertia_kgm2"]["value"], "closed_loop": False}
        cradle = "servo_cradle_print_2" if drive == "servo360" else "tt_cradle_print_2"
        cmass, _ = _print_mass("wheeled", cradle, printing)
        for side, sign in (("left", 1.0), ("right", -1.0)):
            if drive == "servo360":
                items.append((f"{side} servo", "motor", d["mass_g"]["value"], (ax + 5.9, sign * 72.0, 0.0)))
                items.append((f"{side} servo cradle", "print", cmass, (ax + 9.9, sign * 66.2, 0.0)))
            else:
                items.append((f"{side} TT motor", "motor", d["mass_g"]["value"], (ax + 24.0, sign * 77.0, 0.0)))
                items.append((f"{side} TT cradle", "print", cmass, (ax + 16.0, sign * 62.8, 0.0)))
        if drive == "tt":
            pmass, _ = _print_mass("wheeled", "driver_plate", printing)
            items.append(("driver board on its plate", "controller", 5.0 + pmass, (-45.0, 0.0, 46.0)))
        half_track = d["wheel_plane_y_mm"] - (3.0 if (drive == "tt" and wheel != "tt_65") else 0.0)
        lowest = min(geo["panel_bottom_mm"], -12.0 if drive == "servo360" else -11.25)

    if "stl" in w:
        hub, _ = _print_mass("wheeled", w["stl"][0], printing)
        if w["friction"] == "tpu":
            tyre, _ = _print_mass("wheeled", w["stl"][1], printing, cfg["tpu"]["density_g_cm3"]["value"], 1.0)
            wheel_mass = hub + tyre
        else:
            wheel_mass = hub + (0.0 if bare else w["ring_g"])
    else:
        wheel_mass = w["mass_g"]["value"]
    for side, sign in (("left", 1.0), ("right", -1.0)):
        items.append((f"{side} wheel", "wheel", wheel_mass, (ax, sign * half_track, 0.0)))

    size = post_size(w["diameter_mm"])
    pmass, pcom = _print_mass("wheeled", f"post_{size}", printing)
    post_h = geo["shelf_underside_mm"] + POST_CLASS[size] / 2.0 - 24.0
    s = cfg["supports"][support]
    tmass, _ = _print_mass("wheeled", s["stl"][0], printing)
    items.append(("support post", "print", pmass, (geo["support_x_mm"], 0.0, geo["shelf_underside_mm"] - post_h + pcom[2])))
    items.append((f"support tip ({support})", "print", tmass + s.get("ball_g", 0.0),
                  (geo["support_x_mm"], 0.0, geo["shelf_underside_mm"] - post_h - 10.0)))

    tyre_key = w.get("bare_friction", w["friction"]) if bare else w["friction"]
    mu = {"wheel": cfg["friction"][tyre_key]["value"], "wheel_range": cfg["friction"][tyre_key]["range"],
          "support": cfg["friction"][s["friction"]]["value"], "support_range": cfg["friction"][s["friction"]]["range"],
          "rolling": cfg["friction"]["rolling"]["value"]}
    motor["stall_current_a"] = d["stall_current_a"]["value"]
    motor["feedback"] = d["feedback"]
    vid = f"{base}-{drive}-{wheel}{'-bare' if bare else ''}-{support}-{end}".replace("_", "")
    v = Variant(vid, base, drive, wheel, support, end, tyre_key, [(n, k, float(m), np.asarray(p, float)) for n, k, m, p in items],
                radius, half_track, w["width_mm"], wheel_mass, motor, mu)
    v.lowest = lowest
    v.bare = bare
    return v


# -- analysis --

def _limits(v: Variant, a: float, h: float, wheelbase: float) -> dict:
    """Level-floor acceleration and braking limits and slope limits for the
    variant's direction of travel. a: centre of mass ahead of the axle
    (toward the support); h: its height; all in m."""
    m = v.mass() / 1000.0
    mu, mus = v.mu["wheel"], v.mu["support"]
    lead = v.end == "back"          # the support leads when the wheels are at the back
    force = 2.0 * v.motor["stall_nm"] / (v.radius * MM)

    def loads(ax, theta=0.0):
        """Normal loads (wheels, support) at forward acceleration ax on a
        climb of theta; forward is the direction of travel."""
        along = ax + G * np.sin(theta)                  # inertial plus gravity, pushing backward
        shift = m * along * h / wheelbase               # moves load toward the trailing end
        nw = m * G * np.cos(theta) * (wheelbase - a) / wheelbase + (shift if lead else -shift)
        ns = m * G * np.cos(theta) * a / wheelbase - (shift if lead else -shift)
        return nw, ns

    def solve(sign, theta=0.0):
        """Largest acceleration (sign +1) or braking (sign -1) the tyres can
        give, by bisection, with the support dragging."""
        lo, hi = 0.0, 30.0
        for _ in range(50):
            mid = (lo + hi) / 2
            nw, ns = loads(sign * mid, theta)
            nw, ns = max(nw, 0.0), max(ns, 0.0)
            ok = mu * nw + (-sign) * mus * ns >= m * mid + sign * m * G * np.sin(theta) if sign > 0 \
                else mu * nw + mus * ns >= m * mid
            lo, hi = (mid, hi) if ok else (lo, mid)
        return lo
    nw0, ns0 = loads(0.0)
    drag = mus * ns0 + v.mu["rolling"] * nw0
    # The trailing end unloads the leading one: which threshold exists depends on the end.
    lift_accel = G * a / h if lead else None                    # support lifts (wheelie) when accelerating
    lift_brake = None if lead else G * a / h                    # support lifts (nose-over) when braking
    wheels_lift_brake = G * (wheelbase - a) / h if lead else None
    wheels_lift_accel = None if lead else G * (wheelbase - a) / h
    accel_traction = solve(+1)
    accel_motor = max(0.0, (force - drag) / m)
    brake_traction = solve(-1)
    slope_torque = slope_traction = 0.0
    for deg in np.arange(0.0, 60.01, 0.1):
        th = np.radians(deg)
        nw, ns = loads(0.0, th)
        if nw <= 0 or ns <= 0:
            break
        need = m * G * np.sin(th) + mus * ns + v.mu["rolling"] * nw
        if need <= force:
            slope_torque = deg
        if mu * nw >= m * G * np.sin(th) + mus * ns:
            slope_traction = deg
    tip = np.degrees(np.arctan2(a if lead else wheelbase - a, h))
    accel = min(accel_traction, accel_motor)
    return {
        "wheel_load_fraction": round(nw0 / (m * G), 3), "support_load_n": round(ns0, 2),
        "drag_n": round(drag, 3), "torque_per_wheel_level_nm": round(drag * v.radius * MM / 2, 4),
        "torque_fraction_of_stall_level": round(drag * v.radius * MM / 2 / v.motor["stall_nm"], 3),
        "accel_limit_traction_m_s2": round(accel_traction, 2), "accel_limit_motor_m_s2": round(accel_motor, 2),
        "brake_limit_traction_m_s2": round(brake_traction, 2),
        "support_lifts_accelerating_m_s2": round(lift_accel, 2) if lift_accel else None,
        "support_lifts_braking_m_s2": round(lift_brake, 2) if lift_brake else None,
        "wheels_lift_braking_m_s2": round(wheels_lift_brake, 2) if wheels_lift_brake else None,
        "wheels_lift_accelerating_m_s2": round(wheels_lift_accel, 2) if wheels_lift_accel else None,
        "tips_before_it_slips": bool((lift_accel is not None and accel >= lift_accel)
                                     or (lift_brake is not None and brake_traction >= lift_brake)),
        "slope_limit_torque_deg": round(float(slope_torque), 1), "slope_limit_traction_deg": round(float(slope_traction), 1),
        "slope_tips_at_deg": round(float(tip), 1),
        "slope_limit_deg": round(float(min(slope_torque, slope_traction, tip)), 1),
    }


def analyse(v: Variant) -> dict:
    cfg = config()
    geo = cfg["geometry"]
    com = v.com()
    wheelbase = (geo["support_x_mm"] - geo["axle_x_mm"]) * MM
    a = (com[0] - geo["axle_x_mm"]) * MM
    h = (com[2] + v.radius) * MM
    tri = np.array([[geo["axle_x_mm"], -v.half_track], [geo["support_x_mm"], 0.0], [geo["axle_x_mm"], v.half_track]])
    side = model.margin(tri, com[:2])
    w0 = v.motor["no_load_rpm"] * 2 * np.pi / 60.0
    lim = _limits(v, a, h, wheelbase)
    top = w0 * v.radius * MM
    cruise = top * (1.0 - lim["torque_fraction_of_stall_level"])
    groups = {}
    for _, kind, mass, _ in v.items:
        groups[kind] = groups.get(kind, 0.0) + mass
    return {
        "id": v.id, "base": v.base, "drive": v.drive, "wheel": v.wheel, "support": v.support, "wheels_at": v.end,
        "ids": {"controller": CONTROLLER_ID[v.base], "locomotion": "wheeled", "drive": DRIVE_ID[(v.base, v.drive)],
                "wheels": v.end, "support": SUPPORT_ID[v.support], "wheel": WHEEL_ID[cfg["wheels"][v.wheel]["kind"]]},
        "tyre": v.tyre, "mass_g": round(v.mass(), 1), "mass_by_kind_g": {k: round(m, 1) for k, m in groups.items()},
        "com_mm": [round(float(x), 1) for x in com], "com_height_above_floor_mm": round(h * 1000, 1),
        "com_ahead_of_axle_mm": round(a * 1000, 1), "wheelbase_mm": round(wheelbase * 1000, 1),
        "com_fraction_of_wheelbase": round(a / wheelbase, 3),
        "track_mm": round(2 * v.half_track, 1), "wheel_diameter_mm": round(2 * v.radius, 2),
        "static_margin_mm": round(side, 1), "stable": bool(side > 0),
        "margin_to_axle_line_mm": round(a * 1000, 1), "margin_to_support_mm": round((wheelbase - a) * 1000, 1),
        "sideways_tilt_to_tip_deg": round(float(np.degrees(np.arctan2(side * MM, h))), 1),
        "ground_clearance_mm": round(v.radius + v.lowest, 1),
        "friction": {"wheel": v.mu["wheel"], "wheel_range": v.mu["wheel_range"], "support": v.mu["support"],
                     "support_range": v.mu["support_range"], "rolling": v.mu["rolling"]},
        "motor": {"stall_torque_nm": v.motor["stall_nm"], "no_load_rpm": v.motor["no_load_rpm"],
                  "feedback": v.motor["feedback"], "stall_current_both_a": round(2 * v.motor["stall_current_a"], 2),
                  "wheel_force_at_stall_n": round(2 * v.motor["stall_nm"] / (v.radius * MM), 2)},
        "top_speed_no_load_m_s": round(top, 3), "cruise_speed_estimate_m_s": round(cruise, 3),
        "current_estimate_cruise_a": round(2 * v.motor["stall_current_a"] * lim["torque_fraction_of_stall_level"], 2),
        **lim,
    }


# -- MuJoCo model --

def _combine(items):
    mass = sum(i[2] for i in items) / 1000.0
    com = sum(i[2] * i[3] for i in items) / sum(i[2] for i in items) * MM
    inertia = np.zeros((3, 3))
    for _, kind, m, p in items:
        d = p * MM - com
        size = {"print": 0.06, "controller": 0.05, "battery": 0.04, "motor": 0.04, "camera": 0.03}.get(kind, 0.02)
        inertia += (m / 1000.0) * (d @ d * np.eye(3) - np.outer(d, d)) + (m / 1000.0) * size * size / 6.0 * np.eye(3)
    return mass, com, inertia


def mjcf(v: Variant) -> str:
    cfg = config()
    geo = cfg["geometry"]
    r = v.radius * MM
    fixed = [i for i in v.items if i[1] != "wheel"]
    mass, com, inertia = _combine(fixed)
    wm = v.wheel_mass / 1000.0
    half = v.width * MM / 2
    iyy = 0.5 * wm * r * r
    ixx = wm * (3 * r * r + (2 * half) ** 2) / 12.0
    sx = geo["support_x_mm"] * MM
    ctrl = cfg["bases"][v.base]["controller"]["size_mm"]
    z0 = (47.0 if cfg["bases"][v.base]["chassis"].startswith("pi") else model.DECK_TOP) * MM
    x = [f'<mujoco model="wheeled_{v.id.replace("-", "_")}">',
         "  <!-- SPDX-License-Identifier: MIT -->",
         "  <!-- Generated by python -m walkers.wheeled; do not edit. Units: m, kg, rad. -->",
         '  <compiler angle="radian"/>',
         '  <option timestep="0.001" integrator="implicitfast" cone="elliptic" impratio="10"/>',
         "  <default>",
         '    <geom contype="1" conaffinity="0" friction="0.01 0.002 0.0001" solref="0.004 1" condim="3"/>',
         '    <default class="show"><geom contype="0" conaffinity="0" type="box"/></default>',
         "  </default>",
         "  <asset>",
         '    <texture name="grid" type="2d" builtin="checker" rgb1="0.86 0.9 0.87" rgb2="0.8 0.85 0.82" width="256" height="256"/>',
         '    <material name="grid" texture="grid" texrepeat="20 20" reflectance="0"/>',
         "  </asset>",
         '  <visual><headlight ambient="0.5 0.5 0.5" diffuse="0.6 0.6 0.6"/><global offwidth="640" offheight="480"/></visual>',
         "  <worldbody>",
         '    <light pos="0.3 -0.4 1.2" dir="-0.2 0.3 -1" diffuse="0.5 0.5 0.5"/>',
         '    <geom name="floor" type="plane" size="6 6 0.1" contype="0" conaffinity="1" material="grid"/>',
         '    <body name="step" mocap="true" pos="0 0 -1"><geom name="step" type="box" size="0.5 0.5 0.05" contype="0" conaffinity="1" rgba="0.6 0.45 0.3 1"/></body>',
         f'    <body name="chassis" pos="0 0 {r:.5f}">',
         '      <freejoint name="root"/>',
         f'      <inertial pos="{com[0]:.5f} {com[1]:.5f} {com[2]:.5f}" mass="{mass:.5f}" fullinertia="{inertia[0, 0]:.3e} {inertia[1, 1]:.3e} {inertia[2, 2]:.3e} {inertia[0, 1]:.3e} {inertia[0, 2]:.3e} {inertia[1, 2]:.3e}"/>',
         '      <geom class="show" pos="0.019 0 0.04" size="0.084 0.058 0.002" rgba="0.93 0.78 0.47 1"/>',
         '      <geom class="show" pos="0 0.0541 0.0145" size="0.048 0.0039 0.0265" rgba="0.93 0.78 0.47 1"/>',
         '      <geom class="show" pos="0 -0.0541 0.0145" size="0.048 0.0039 0.0265" rgba="0.93 0.78 0.47 1"/>',
         f'      <geom class="show" pos="0 0 {z0 + ctrl[2] * MM / 2:.4f}" size="{ctrl[0] * MM / 2:.4f} {ctrl[1] * MM / 2:.4f} {ctrl[2] * MM / 2:.4f}" rgba="0.28 0.47 0.67 1"/>',
         f'      <geom class="show" pos="{model.HEAD_X * MM} 0 {(model.SHELF_TOP + 35) * MM}" size="0.02 0.02 0.035" rgba="0.93 0.78 0.47 1"/>',
         f'      <geom class="show" pos="{model.HEAD_X * MM + (0.025 if v.end == "back" else -0.025)} 0 {(model.SHELF_TOP + 55) * MM}" size="0.006 0.015 0.012" rgba="0.25 0.6 0.43 1"/>',
         f'      <geom class="show" pos="{sx} 0 {(geo["shelf_underside_mm"] * MM + 0.024 - r) / 2:.4f}" size="0.006 0.006 {(geo["shelf_underside_mm"] * MM - 0.024 + r) / 2:.4f}" rgba="0.93 0.78 0.47 1"/>',
         # Printed plastic that can touch a step or the floor: panel bottoms and the head.
         f'      <geom name="belly" type="box" pos="0 0 {(v.lowest + 4.0) * MM:.4f}" size="0.048 0.054 0.004" friction="0.3 0.002 0.0001" rgba="0 0 0 0"/>',
         f'      <geom name="head_hit" type="box" pos="{(model.HEAD_X + 2) * MM} 0 {(model.SHELF_TOP + 35) * MM}" size="0.03 0.028 0.035" friction="0.3 0.002 0.0001" rgba="0 0 0 0"/>']
    if v.support == "skid":
        rs = cfg["supports"]["skid"]["contact_radius_mm"] * MM
        x.append(f'      <geom name="support" type="sphere" pos="{sx} 0 {rs - r:.5f}" size="{rs}" friction="{v.mu["support"]} 0.002 0.0001" rgba="0.85 0.4 0.3 1"/>')
    else:
        rb = cfg["supports"]["ball"]["ball_mm"] * MM / 2
        load = mass * G * (com[0] - geo["axle_x_mm"] * MM) / ((geo["support_x_mm"] - geo["axle_x_mm"]) * MM)
        loss = v.mu["support"] * load * rb       # the ball slides in its cup: friction torque at the ball radius
        x.append(f'      <body name="ball" pos="{sx} 0 {rb - r:.5f}">')
        x.append(f'        <joint name="ball" type="ball" frictionloss="{loss:.6f}" armature="0.000002" damping="0.00001"/>')
        x.append(f'        <inertial pos="0 0 0" mass="0.004" diaginertia="1e-7 1e-7 1e-7"/>')
        x.append(f'        <geom name="support" type="sphere" size="{rb}" friction="0.6 0.002 0.0001" rgba="0.6 0.62 0.65 1"/>')
        x.append("      </body>")
    for side, sign in (("left", 1.0), ("right", -1.0)):
        x.append(f'      <body name="{side}_wheel" pos="{geo["axle_x_mm"] * MM} {sign * v.half_track * MM:.4f} 0">')
        x.append(f'        <joint name="{side}_wheel" type="hinge" axis="0 1 0" armature="{v.motor["rotor"]}" frictionloss="0.002"/>')
        x.append(f'        <inertial pos="0 0 0" mass="{wm:.5f}" diaginertia="{ixx:.3e} {iyy:.3e} {ixx:.3e}"/>')
        x.append(f'        <geom name="{side}_tyre" type="cylinder" size="{r:.5f} {half:.4f}" quat="0.70711 0.70711 0 0" friction="{v.mu["wheel"]} 0.002 0.0001" rgba="0.2 0.22 0.25 1"/>')
        x.append("      </body>")
    x += ["    </body>", "  </worldbody>", "  <actuator>"]
    for side in ("left", "right"):
        x.append(f'    <motor name="{side}_motor" joint="{side}_wheel" gear="1" ctrllimited="true" ctrlrange="{-v.motor["stall_nm"]} {v.motor["stall_nm"]}"/>')
    x += ["  </actuator>", "</mujoco>"]
    return "\n".join(x) + "\n"


class WheeledSim:
    """The variant in MuJoCo with a motor model: torque = stall torque times
    (drive fraction minus speed over no-load speed) for the open-loop drives;
    the same envelope around a speed controller for the encoder motors."""

    def __init__(self, v: Variant, xml: str | None = None):
        self.v = v
        self.model = mujoco.MjModel.from_xml_string(xml or mjcf(v))
        self.data = mujoco.MjData(self.model)
        m = self.model
        self.chassis = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, "chassis")
        self.dof = [m.jnt_dofadr[mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, f"{s}_wheel")] for s in ("left", "right")]
        self.stall = v.motor["stall_nm"]
        self.w0 = v.motor["no_load_rpm"] * 2 * np.pi / 60.0
        self.sign = 1.0 if v.end == "back" else -1.0       # direction of travel along x
        self.step_pos = [0.0, 0.0, -1.0]
        self.steps = int(round(CONTROL_DT / m.opt.timestep))
        if not v.motor["closed_loop"]:
            # The fall of torque with speed is a damping on the wheel joint, so
            # the integrator handles it inside each step.
            for dof in self.dof:
                m.dof_damping[dof] = self.stall / self.w0
        self.reset()

    def reset(self) -> None:
        mujoco.mj_resetData(self.model, self.data)
        self.data.mocap_pos[0] = self.step_pos
        self.data.qpos[2] += 0.0003
        mujoco.mj_forward(self.model, self.data)
        self.time = 0.0
        self.integral = [0.0, 0.0]

    def set_slope(self, uphill_deg: float) -> None:
        a = np.radians(uphill_deg)
        self.model.opt.gravity[:] = [-self.sign * G * np.sin(a), 0.0, -G * np.cos(a)]

    def set_step(self, distance_m: float, height_m: float) -> None:
        """A step across the path, its near edge distance_m ahead of the leading part."""
        if self.sign > 0:
            self.step_pos = [0.092 + 0.014 + distance_m + 0.5, 0.0, height_m - 0.05]
        else:
            self.step_pos = [-0.016 - self.v.radius * MM - distance_m - 0.5, 0.0, height_m - 0.05]
        self.data.mocap_pos[0] = self.step_pos

    def forward_pos(self) -> float:
        return float(self.sign * self.data.xpos[self.chassis][0])

    def yaw(self) -> float:
        r = self.data.xmat[self.chassis].reshape(3, 3)
        return float(np.arctan2(r[1, 0], r[0, 0]))

    def pitch_deg(self) -> float:
        """Nose-up positive, in the direction of travel."""
        r = self.data.xmat[self.chassis].reshape(3, 3)
        return float(self.sign * np.degrees(np.arcsin(np.clip(r[2, 0], -1, 1))))

    def tilt_deg(self) -> float:
        up = self.data.xmat[self.chassis].reshape(3, 3)[:, 2]
        g = -self.model.opt.gravity / np.linalg.norm(self.model.opt.gravity)
        return float(np.degrees(np.arccos(np.clip(up @ g, -1.0, 1.0))))

    def tick(self, left: float, right: float) -> None:
        """Advance 5 ms with drive fractions -1..1, positive = forward in the
        direction of travel."""
        for i, u in enumerate((left, right)):
            w = float(self.data.qvel[self.dof[i]]) * self.sign
            if self.v.motor["closed_loop"]:
                target = 0.8 * self.w0 * u                 # regulated speed, with headroom
                err = target - w
                self.integral[i] = float(np.clip(self.integral[i] + 2.0 * err * CONTROL_DT, -self.stall, self.stall))
                wanted = 0.05 * err + self.integral[i]
                lo = max(-self.stall, -self.stall * (1.0 + w / self.w0))
                hi = min(self.stall, self.stall * (1.0 - w / self.w0))
                torque = float(np.clip(wanted, min(lo, hi), max(lo, hi)))
            else:
                torque = float(np.clip(self.stall * u, -self.stall, self.stall))
            self.data.ctrl[i] = torque * self.sign
        for _ in range(self.steps):
            mujoco.mj_step(self.model, self.data)
        self.time += CONTROL_DT


def drive(s: WheeledSim, command, duration: float, on_tick=None) -> np.ndarray:
    rows = []
    while s.time < duration - 1e-9:
        left, right = command(s.time)
        s.tick(left, right)
        p = s.data.xpos[s.chassis]
        v = s.data.cvel[s.chassis][3:6]
        rows.append((s.time, s.forward_pos(), float(p[1]), s.yaw(), s.pitch_deg(), s.tilt_deg(),
                     float(s.sign * v[0]), abs(float(s.data.ctrl[0])), abs(float(s.data.ctrl[1])), float(p[0])))
        if on_tick:
            on_tick(s)
    return np.array(rows)


def experiments(v: Variant, analysis: dict) -> dict:
    out = {"id": v.id}
    s = WheeledSim(v)
    a = drive(s, lambda t: (1.0, 1.0), 3.0)
    last = a[a[:, 0] >= 2.0]
    speed = float((last[-1, 1] - last[0, 1]) / (last[-1, 0] - last[0, 0]))
    reach = a[a[:, 6] >= 0.9 * speed]
    out["straight"] = {"speed_m_s": round(speed, 3), "distance_3s_m": round(float(a[-1, 1]), 3),
                       "time_to_90_percent_s": round(float(reach[0, 0]), 2) if len(reach) else None,
                       "fraction_of_no_load_speed": round(speed / analysis["top_speed_no_load_m_s"], 2),
                       "max_pitch_deg": round(float(np.abs(a[:, 4]).max()), 2),
                       "heading_change_deg": round(float(np.degrees(a[-1, 3] - a[0, 3])), 1),
                       "mean_torque_nm": round(float(last[:, 7:9].mean()), 4)}
    # Braking from full speed.
    b = drive(s, lambda t: (0.0, 0.0), 5.0)
    stopped = b[np.abs(b[:, 6]) < 0.005]
    out["stop"] = {"distance_m": round(float(b[-1, 1] - a[-1, 1]), 3),
                   "time_s": round(float(stopped[0, 0] - 3.0), 2) if len(stopped) else None,
                   "max_pitch_deg": round(float(b[:, 4].max()), 2), "min_pitch_deg": round(float(b[:, 4].min()), 2),
                   "max_tilt_deg": round(float(b[:, 5].max()), 2)}
    s = WheeledSim(v)
    a = drive(s, lambda t: (-1.0, 1.0), 3.0)
    yaw = np.unwrap(a[:, 3])
    late = a[:, 0] >= 1.5
    rate = float(np.degrees((yaw[late][-1] - yaw[late][0]) / 1.5))
    ideal = float(np.degrees(analysis["top_speed_no_load_m_s"] * (0.8 if v.motor["closed_loop"] else 1.0) / (v.half_track * MM)))
    out["spin"] = {"yaw_rate_deg_s": round(abs(rate), 1), "ideal_deg_s": round(ideal, 1),
                   "fraction_of_ideal": round(abs(rate) / ideal, 2),
                   "centre_drift_mm": round(float(np.hypot(a[-1, 9] - a[0, 9], a[-1, 2] - a[0, 2]) * 1000), 1),
                   "max_tilt_deg": round(float(a[:, 5].max()), 2)}
    s = WheeledSim(v)
    a = drive(s, lambda t: (0.5, 1.0), 4.0)
    yaw = np.unwrap(a[:, 3])
    late = a[:, 0] >= 2.0
    w = (yaw[late][-1] - yaw[late][0]) / 2.0
    path = np.hypot(np.diff(a[late][:, 9]), np.diff(a[late][:, 2])).sum() / 2.0
    out["arc"] = {"radius_m": round(float(path / abs(w)), 3) if abs(w) > 1e-3 else None,
                  "ideal_radius_m": round(3.0 * v.half_track * MM, 3),
                  "yaw_rate_deg_s": round(float(abs(np.degrees(w))), 1), "max_tilt_deg": round(float(a[:, 5].max()), 2)}
    # Slope: steepest climbed in the direction of travel.
    level = out["straight"]["speed_m_s"]
    best, rows = 0, []
    for deg in range(2, 61, 2):
        s = WheeledSim(v)
        s.set_slope(deg)
        s.reset()
        a = drive(s, lambda t: (min(1.0, t), min(1.0, t)), 5.0)       # drive ramped up over 1 s
        late = a[a[:, 0] >= 3.0]
        sp = float((late[-1, 1] - late[0, 1]) / 2.0)
        ok = sp > 0.2 * level and a[:, 5].max() < 30.0
        rows.append({"deg": deg, "speed_m_s": round(sp, 3), "max_tilt_deg": round(float(a[:, 5].max()), 1), "climbs": bool(ok)})
        if not ok:
            break
        best = deg
    fail = rows[-1]
    why = None
    if not fail["climbs"]:
        why = "tips" if fail["max_tilt_deg"] >= 30.0 else ("slides back" if fail["speed_m_s"] < -0.01 else "stalls or spins")
    out["slope"] = {"steepest_climbed_deg": best, "fails_at_deg": fail["deg"] if not fail["climbs"] else None, "how": why,
                    "speed_at_limit_m_s": rows[-2]["speed_m_s"] if len(rows) > 1 else None}
    best, rows = 0, []
    for height in (2, 4, 6, 8, 10, 12, 14, 16, 20, 24):
        s = WheeledSim(v)
        s.set_step(0.10, height * MM)
        s.reset()
        a = drive(s, lambda t: (min(1.0, 2 * t), min(1.0, 2 * t)), 5.0)
        over = float(a[-1, 1]) > 0.10 + 0.13 + 0.06 and a[:, 5].max() < 35.0
        rows.append({"mm": height, "distance_m": round(float(a[-1, 1]), 3), "max_tilt_deg": round(float(a[:, 5].max()), 1), "climbed": bool(over)})
        if not over:
            break
        best = height
    fail = rows[-1]
    how = None
    if not fail["climbed"]:
        d = fail["distance_m"]
        how = "tips" if fail["max_tilt_deg"] >= 35.0 else ("the leading part stops at the step" if d < 0.13 else "the trailing part stops at the step")
    out["step"] = {"highest_climbed_mm": best, "fails_at_mm": fail["mm"] if not fail["climbed"] else None, "how": how}
    return out


def record(v: Variant, name: str, command, duration: float, step_mm: float = 0.0) -> str:
    s = WheeledSim(v)
    if step_mm:
        s.set_step(0.10, step_mm * MM)
        s.reset()
    renderer = mujoco.Renderer(s.model, 240, 320)
    camera = mujoco.MjvCamera()
    camera.distance, camera.azimuth, camera.elevation = 1.1, 115.0, -20.0
    camera.lookat[:] = [0.25, 0.0, 0.03]
    frames, count = [], [0]

    def grab(q):
        if count[0] % 20 == 0:
            renderer.update_scene(q.data, camera)
            frames.append(Image.fromarray(renderer.render()))
        count[0] += 1
    drive(s, command, duration, on_tick=grab)
    renderer.close()
    first = frames[0].quantize(colors=32, method=Image.MEDIANCUT, dither=Image.Dither.NONE)
    rest = [f.quantize(palette=first, dither=Image.Dither.NONE) for f in frames[1:]]
    first.save(IMAGES / name, save_all=True, append_images=rest, duration=100, loop=0, optimize=True)
    return f"images/{name}"


def default_variants(all_wheels: bool = False) -> list:
    """Every base and drive with each support and each end, on its default
    wheel or on every wheel offered for it."""
    cfg = config()
    out = []
    for base, b in cfg["bases"].items():
        for d in b["drives"]:
            for wheel in (b["wheels"][d] if all_wheels else b["wheels"][d][:1]):
                for support in SUPPORTS:
                    for end in ENDS:
                        out.append(build(base, d, wheel, support, end))
    return out


def viewer(v: Variant) -> dict:
    """What the site's 3D view needs for one variant: STLs with their
    placement, bought parts as boxes, stock wheels as cylinders. Lengths in
    mm, matrices row-major, robot frame."""
    cfg = config()
    b, w, geo = cfg["bases"][v.base], cfg["wheels"][v.wheel], cfg["geometry"]
    ax, sx = geo["axle_x_mm"], geo["support_x_mm"]

    def flat(matrix):
        return [round(float(x), 4) for x in np.asarray(matrix).flatten()]
    head = model.trans(model.HEAD_X, 0.0, model.SHELF_TOP) @ model.rot("z", 180.0 if v.end == "front" else 0.0)
    size = post_size(w["diameter_mm"])
    r_class = POST_CLASS[size] / 2.0
    post_h = geo["shelf_underside_mm"] + r_class - 24.0
    tip = cfg["supports"][v.support]["stl"][0]
    stl = [{"file": f"lego/{b['chassis']}/chassis.stl", "matrix": flat(np.eye(4)), "kind": "print"},
           {"file": f"lego/{b['chassis']}/{b['head']}.stl", "matrix": flat(head), "kind": "print"},
           {"file": f"lego/wheeled/post_{size}.stl", "matrix": flat(model.trans(sx, 0.0, geo["shelf_underside_mm"] - post_h)), "kind": "print"},
           {"file": f"lego/wheeled/{tip}.stl", "matrix": flat(model.trans(sx, 0.0, -r_class)), "kind": "print"}]
    wheels, boxes = [], []
    for sign in (1.0, -1.0):
        y = sign * v.half_track
        if "stl" in w:
            turn = model.rot("x", 90.0 * sign)
            place = model.trans(ax, y + sign * v.width / 2.0, 0.0) @ turn
            parts = [(w["stl"][0], 0.0)] + ([(w["stl"][1], 2.4)] if w["friction"] == "tpu" else [])
            for name, lift in parts:
                wheels.append({"file": f"lego/wheeled/{name}.stl", "matrix": flat(place @ model.trans(0.0, 0.0, lift)),
                               "centre": [ax, y, 0.0], "kind": "tyre" if "tyre" in name else "wheel"})
        else:
            wheels.append({"cylinder": True, "centre": [ax, y, 0.0], "radius": v.radius, "width": v.width, "kind": "tyre"})
        if v.drive == "servo360":
            boxes.append({"kind": "motor", "min": [ax - 5.4, min(sign * 58.0, sign * 85.0), -6.1], "max": [ax + 17.3, max(sign * 58.0, sign * 85.0), 6.1]})
        elif v.drive == "tt":
            boxes.append({"kind": "motor", "min": [ax - 11.25, min(sign * 67.5, sign * 86.3), -11.25], "max": [ax + 58.75, max(sign * 67.5, sign * 86.3), 11.25]})
        else:
            comp = model.load_json("components.json")[cfg["drives"][v.drive]["components_key"]]
            yc = sign * cfg["drives"][v.drive]["y_centre_mm"]
            for lo, hi in (comp["envelope"]["hub"], comp["envelope"]["body"]):
                boxes.append({"kind": "motor", "min": [ax + lo[0], yc + lo[1], lo[2]], "max": [ax + hi[0], yc + hi[1], hi[2]]})
    ctrl = b["controller"]["size_mm"]
    z0 = 47.0 if b["chassis"].startswith("pi") else model.DECK_TOP
    boxes.append({"kind": "controller", "min": [-ctrl[0] / 2, -ctrl[1] / 2, z0], "max": [ctrl[0] / 2, ctrl[1] / 2, z0 + ctrl[2]]})
    for extra in b["extra"]:
        p = extra["at_mm"]
        boxes.append({"kind": "battery", "min": [p[0] - 18, p[1] - 28, p[2] - 9], "max": [p[0] + 18, p[1] + 28, p[2] + 9]})
    return {"id": v.id, "radius_mm": v.radius, "stl": stl, "wheels": wheels, "boxes": boxes}


def tyre_variants() -> list:
    """The same robot on each wheel option, skid, wheels at the back."""
    cfg = config()
    out = []
    for base, d in (("ev3", "ev3_large"), ("unoq", "tt"), ("unoq", "servo360")):
        for wheel in cfg["bases"][base]["wheels"][d]:
            out.append(build(base, d, wheel, "skid", "back"))
            if "bare_friction" in cfg["wheels"][wheel]:
                out.append(build(base, d, wheel, "skid", "back", bare=True))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--no-recordings", action="store_true")
    args = parser.parse_args()
    REPORTS.mkdir(parents=True, exist_ok=True)
    MODELS.mkdir(parents=True, exist_ok=True)
    for old in MODELS.glob("*.xml"):
        old.unlink()
    variants = default_variants()
    full = default_variants(all_wheels=True)
    seen = {v.id for v in full}
    tyres = tyre_variants()
    everything = full + [v for v in tyres if v.id not in seen]
    analysis, sims = {}, {}
    for v in everything:
        analysis[v.id] = analyse(v)
        (MODELS / f"{v.id}.xml").write_text(mjcf(v), encoding="utf-8", newline="\n")
        sims[v.id] = experiments(v, analysis[v.id])
        print(v.id, analysis[v.id]["mass_g"], sims[v.id]["straight"]["speed_m_s"], sims[v.id]["slope"]["steepest_climbed_deg"],
              sims[v.id]["step"]["highest_climbed_mm"], flush=True)
    doc = {"_comment": "Generated by python -m walkers.wheeled. Lengths in mm unless a key says otherwise.",
           "status": "Analysed only. No wheeled variant has been built.",
           "defaults": [v.id for v in variants], "all": [v.id for v in full], "tyre_comparison": [v.id for v in tyres],
           "variants": analysis}
    (REPORTS / "analysis.json").write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8", newline="\n")
    views = {v.id: viewer(v) for v in full}
    (MODELS / "viewer.json").write_text(json.dumps(views, separators=(",", ":")) + "\n", encoding="utf-8", newline="\n")
    simdoc = {"_comment": "Generated by python -m walkers.wheeled. MuJoCo, 1 ms step, control every 5 ms. Full drive in every run.",
              "status": "Simulation only. No wheeled variant has been built.", "variants": sims}
    if not args.no_recordings:
        ev3 = build("ev3", "ev3_large", None, "skid", "back")
        tt = build("unoq", "tt", None, "ball", "front")
        simdoc["recordings"] = {
            "ev3_straight_and_turn": record(ev3, "wheeled-ev3-drive.gif", lambda t: (1.0, 1.0) if t < 2.0 else (0.3, 1.0), 4.5),
            "ev3_step": record(ev3, "wheeled-ev3-step.gif", lambda t: (1.0, 1.0), 3.5, step_mm=sims[ev3.id]["step"]["highest_climbed_mm"] + 2),
            "unoq_tt_ball_front": record(tt, "wheeled-unoq-tt-drive.gif", lambda t: (1.0, 1.0) if t < 1.5 else (-1.0, 1.0), 3.5),
        }
    (REPORTS / "sim.json").write_text(json.dumps(simdoc, indent=1) + "\n", encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
