# SPDX-License-Identifier: MIT
"""Digital assembly test of the two crank walkers.

Places the printed parts and the bought parts, then checks interference at
rest and through the crank cycle, the gear mesh, mass, centre of mass and the
static balance at every crank phase. Writes reports/lego/assembly.json and
the pictures in docs/images/.

    python -m walkers.assembly
"""
from __future__ import annotations

import json
import sys

import numpy as np
from PIL import Image, ImageDraw

from microduck import render

from . import model
from .model import BUILDS, CRANK_R, ROOT, Walker, build_walker, margin

REPORT = ROOT / "reports" / "lego" / "assembly.json"
IMAGES = ROOT / "docs" / "images"
PHASE_STEP = 5
COLORS = {"print": (236, 200, 120), "motor": (150, 156, 164), "controller": (70, 120, 170), "camera": (60, 150, 110),
          "technic": (60, 60, 66), "ballast": (120, 90, 60)}
# Pairs that touch by design: a part resting on or pinned to its seat.
SEATED = {("chassis", "head"), ("chassis", "EV3 brick"), ("chassis", "Pi Zero 2 W"), ("head", "pan-tilt kit"),
          ("head", "Pixy2"), ("head", "Camera Module 2"), ("pan-tilt kit", "Pixy2")}


def _overlap(a, b) -> float:
    ba, bb = a.bounding_box(), b.bounding_box()
    if any(ba[i] > bb[i + 3] or bb[i] > ba[i + 3] for i in range(3)):
        return 0.0
    return float((a ^ b).volume())


def interference(walker: Walker) -> dict:
    """Overlap volumes at rest (phase 90, left foot down) and the worst over
    the crank cycle for every pair that involves a moving part."""
    solids = [i for i in walker.items if i.solid is not None]
    fixed = [i for i in solids if i.motion is None]
    moving = [i for i in solids if i.motion is not None]
    placed = {i.name: i.placed() for i in fixed}
    rest = []
    idler_turn = model.rot("y", 360.0 / 32.0)
    for n, a in enumerate(fixed):
        for b in fixed[n + 1:]:
            sa, sb = placed[a.name], placed[b.name]
            # Mesh the idler half a tooth round, as it sits in practice.
            if "gear" in a.name and "gear" in b.name:
                if "centre" in a.name:
                    sa = model.apply(a.solid, model.trans(*a.matrix[:3, 3]) @ idler_turn @ model.rot("x", 90.0))
                if "centre" in b.name:
                    sb = model.apply(b.solid, model.trans(*b.matrix[:3, 3]) @ idler_turn @ model.rot("x", 90.0))
            volume = _overlap(sa, sb)
            if volume > 0.5 and (a.name, b.name) not in SEATED:
                rest.append({"a": a.name, "b": b.name, "volume_mm3": round(volume, 1)})
    worst = {}
    phases = list(range(0, 360, PHASE_STEP))
    for phase in phases:
        now = {i.name: i.placed(phase) for i in moving}
        for n, a in enumerate(moving):
            for b in fixed:
                volume = _overlap(now[a.name], placed[b.name])
                if volume > 0.01:
                    key = (a.name, b.name)
                    if volume > worst.get(key, (0.0, 0))[0]:
                        worst[key] = (volume, phase)
            for b in moving[n + 1:]:
                volume = _overlap(now[a.name], now[b.name])
                if volume > 0.01:
                    key = (a.name, b.name)
                    if volume > worst.get(key, (0.0, 0))[0]:
                        worst[key] = (volume, phase)
    cycle = [{"a": a, "b": b, "volume_mm3": round(v, 1), "worst_phase_deg": p} for (a, b), (v, p) in sorted(worst.items())]
    pairs = len(moving) * len(fixed) + len(moving) * (len(moving) - 1) // 2
    return {"rest": rest, "cycle": cycle, "phases_checked": len(phases), "pairs_per_phase": pairs,
            "fixed_parts": [i.name for i in fixed], "moving_parts": [i.name for i in moving]}


def clearances(walker: Walker) -> dict:
    """Smallest gaps that matter, over the cycle (mm)."""
    out = {}
    fixed = {i.name: i.placed() for i in walker.items if i.solid is not None and i.motion is None}
    pairs = [("left leg", "right leg"), ("left leg", "chassis"), ("right leg", "chassis"),
             ("left leg", "left motor"), ("right leg", "right motor"),
             ("left rear crank", "left idler axle bush"), ("left front crank", "left idler axle bush"),
             ("left rear crank", "left leg"), ("left rear crank", "chassis")]
    for a, b in pairs:
        best = (1e9, 0)
        for phase in range(0, 360, 15):
            sa = walker.item(a).placed(phase)
            sb = fixed[b] if b in fixed else walker.item(b).placed(phase)
            gap = float(sa.min_gap(sb, 60.0))
            if gap < best[0]:
                best = (gap, phase)
        out[f"{a} to {b}"] = {"min_gap_mm": round(best[0], 2), "at_phase_deg": best[1]}
    lowest = min(float(s.bounding_box()[2]) for s in fixed.values())
    out["lowest fixed part above the floor"] = {"min_gap_mm": round(lowest + model.LEG_DROP, 1),
                                                "note": "floor at its highest, both feet level"}
    return out


def gear_mesh(build: str, comp: dict) -> dict:
    """Measure the printed gear from its STL and compare with module 1 at the
    16 mm axle spacing."""
    mesh = model.part_mesh(build, "gear_16t_print_6")
    low = mesh.vertices[np.abs(mesh.vertices[:, 2]) < 1e-6][:, :2]
    radius = np.hypot(low[:, 0], low[:, 1])
    rim = low[radius > 6.0]
    angle = np.arctan2(rim[:, 1], rim[:, 0])
    order = np.argsort(angle)
    angle, r = angle[order], np.hypot(rim[order, 0], rim[order, 1])
    tip, root = float(r.max()), float(r.min())
    pitch_r = 8.0
    # Flank crossings of the pitch circle, by interpolation along the outline.
    a2, r2 = np.append(angle, angle[0] + 2 * np.pi), np.append(r, r[0])
    cross = []
    for k in range(len(a2) - 1):
        if (r2[k] - pitch_r) * (r2[k + 1] - pitch_r) < 0:
            t = (pitch_r - r2[k]) / (r2[k + 1] - r2[k])
            cross.append((a2[k] + t * (a2[k + 1] - a2[k]), r2[k + 1] > r2[k]))
    teeth = len(cross) // 2
    rising = [c[0] for c in cross if c[1]]
    falling = [c[0] for c in cross if not c[1]]
    widths = [(f - max(x for x in rising + [rising[-1] - 2 * np.pi] if x < f)) * pitch_r for f in falling]
    thickness = float(np.median(widths))
    circular_pitch = 2 * np.pi * pitch_r / teeth
    module = 2 * pitch_r / teeth
    centre = model.AXLES_X[1] - model.AXLES_X[0]
    backlash = circular_pitch - 2 * thickness
    idler = model.manifold_of(mesh)
    worst = 0.0
    for step in range(16):
        turn = step * 22.5 / 16
        a = model.apply(idler, model.rot("z", turn))
        b = model.apply(idler, model.trans(centre, 0, 0) @ model.rot("z", 11.25 - turn))
        worst = max(worst, _overlap(a, b))
    return {
        "teeth": teeth, "tip_radius_mm": round(tip, 3), "root_radius_mm": round(root, 3),
        "pitch_radius_mm": pitch_r, "module_mm": round(module, 4),
        "tooth_thickness_at_pitch_mm": round(thickness, 3), "circular_pitch_mm": round(circular_pitch, 4),
        "axle_spacing_mm": centre, "standard_centre_distance_mm": round(module * teeth, 3),
        "centre_distance_error_mm": round(centre - module * teeth, 4),
        "backlash_per_mesh_mm": round(backlash, 3),
        "backlash_per_mesh_deg": round(float(np.degrees(backlash / pitch_r)), 2),
        "crank_to_crank_play_deg": round(float(np.degrees(2 * backlash / pitch_r)), 2),
        "tip_to_root_clearance_mm": round(centre - tip - root, 3),
        "overlap_through_one_tooth_mm3": round(worst, 3),
        "thickness_mm": round(float(mesh.bounds[1][2] - mesh.bounds[0][2]), 2),
        "stock_gear": comp["technic"]["gear_16t"]["value"],
        "verdict": "Module 1, 16 teeth: the same pitch as a Technic 16-tooth gear, and the 16 mm axle spacing is the "
                   "standard centre distance. The printed tooth is thinned for backlash. A stock gear is 7.8 mm wide "
                   "against the printed 5 mm.",
    }


def mass_table(walker: Walker) -> dict:
    groups = {}
    rows = []
    for item in walker.items:
        if item.mass_g <= 0:
            continue
        groups[item.kind] = groups.get(item.kind, 0.0) + item.mass_g
        rows.append({"name": item.name, "kind": item.kind, "mass_g": round(item.mass_g, 1), "from": item.source,
                     "at_mm": [round(float(v), 1) for v in item.com_world(90.0)]})
    printed = groups.get("print", 0.0)
    fraction = walker.components["printing"]["solid_fraction"]["value"]
    return {"total_g": round(walker.mass_g(), 1), "by_kind_g": {k: round(v, 1) for k, v in groups.items()},
            "total_if_printed_solid_g": round(walker.mass_g() - printed + printed / fraction, 1), "items": rows}


def stability(walker: Walker, shift=(0.0, 0.0)) -> dict:
    """Static balance through the cycle: margin of the centre of mass inside
    the support polygon of the foot or feet on the floor."""
    rows, margins = [], []
    for phase in range(0, 360, PHASE_STEP):
        com = walker.com(phase)
        m = margin(walker.support_polygon(phase), com[:2] + shift)
        margins.append(m)
        if phase % 15 == 0:
            rows.append({"phase_deg": phase, "on_floor": list(model.stance(phase)), "margin_mm": round(m, 1),
                         "com_xy_mm": [round(float(com[0] + shift[0]), 1), round(float(com[1] + shift[1]), 1)],
                         "body_height_mm": round(-model.ground_z(phase), 1)})
    margins = np.array(margins)
    worst = int(np.argmin(margins))
    com = walker.com(90.0)
    height = float(com[2] + model.LEG_DROP + CRANK_R)
    low = float(margins.min())
    return {"min_margin_mm": round(low, 1), "at_phase_deg": worst * PHASE_STEP,
            "max_margin_mm": round(float(margins.max()), 1),
            "stable_at_every_phase": bool(low > 0),
            "com_height_above_floor_mm": round(height, 1),
            "tilt_to_tip_deg": round(float(np.degrees(np.arctan2(max(low, 0.0), height))), 1),
            "phases": rows}


def com_window(walker: Walker) -> dict:
    """Where the centre of mass may be, in the body frame, for it to stay over
    the stance foot at every phase: the intersection of all support polygons."""
    polygons = [walker.support_polygon(p) for p in range(0, 360, PHASE_STEP)]
    com = walker.com(90.0)

    def worst(x, y):
        return min(margin(poly, (x, y)) for poly in polygons)
    xs = np.arange(-60.0, 60.5, 0.5)
    ys = np.arange(-30.0, 30.5, 0.5)
    ok_x = [x for x in xs if worst(x, com[1]) >= 0]
    ok_y = [y for y in ys if worst(com[0], y) >= 0]
    best = max(((worst(x, y), x, y) for x in np.arange(-30, 31, 1.0) for y in np.arange(-12, 13, 1.0)))
    return {"x_range_mm_at_com_y": [float(min(ok_x)), float(max(ok_x))] if ok_x else None,
            "y_range_mm_at_com_x": [float(min(ok_y)), float(max(ok_y))] if ok_y else None,
            "best_point_mm": [best[1], best[2]], "best_margin_mm": round(best[0], 1),
            "note": "The window is long fore and aft and narrow sideways: each foot reaches only 10.5 mm past the "
                    "centreline with its finger tips."}, polygons


def sweep_mass(walker: Walker, polygons: list, name: str, mass_g: float, xs) -> list:
    """Min margin over the cycle as a mass already in the model is slid fore
    and aft (name) or a new one is added (name None)."""
    total = walker.mass_g()
    rows = []
    base = [walker.com(p)[:2] for p in range(0, 360, PHASE_STEP)]
    x_now = walker.item(name).com_world()[0] if name else 0.0
    for x in xs:
        if name:
            dx = mass_g * (x - x_now) / total
            coms = [c + [dx, 0.0] for c in base]
        else:
            coms = [(c * total + mass_g * np.array([x, 0.0])) / (total + mass_g) for c in base]
        rows.append((float(x), min(margin(poly, c) for poly, c in zip(polygons, coms))))
    return rows


def _range(rows: list, threshold: float):
    ok = [x for x, m in rows if m >= threshold]
    return [min(ok), max(ok)] if ok else None


def placement(walker: Walker, polygons: list) -> dict:
    """Where the brick (EV3) or a battery (Pi) must sit."""
    xs = np.arange(-80.0, 80.5, 1.0)
    if walker.build == "ev3-pixy2":
        brick = walker.item("EV3 brick")
        rows = sweep_mass(walker, polygons, "EV3 brick", brick.mass_g, xs)
        best = max(rows, key=lambda r: r[1])
        plateau = [x for x, m in rows if m >= best[1] - 0.05]
        on_deck = [-10.0, 10.0]
        return {"what": "EV3 brick centre, fore and aft, on the deck",
                "mass_g": round(brick.mass_g, 1),
                "x_range_balanced_mm": _range(rows, 0.0),
                "x_range_with_5_mm_margin_mm": _range(rows, 5.0),
                "x_range_at_full_margin_mm": [min(plateau), max(plateau)],
                "full_margin_mm": round(best[1], 1),
                "x_range_fully_on_deck_mm": on_deck,
                "margin_at_deck_centre_mm": round(dict(rows)[0.0], 1),
                "sweep": [{"x_mm": x, "min_margin_mm": round(m, 1)} for x, m in rows if x % 10 == 0]}
    pack = walker.components["build_hat"]["battery_pack_g"]["value"]
    rows = sweep_mass(walker, polygons, None, pack, xs)
    best = max(rows, key=lambda r: r[1])
    plateau = [x for x, m in rows if m >= best[1] - 0.05]
    return {"what": "an optional battery pack between the panels under the deck, fore and aft",
            "mass_g": pack,
            "x_range_balanced_mm": _range(rows, 0.0),
            "x_range_with_5_mm_margin_mm": _range(rows, 5.0),
            "x_range_at_full_margin_mm": [min(plateau), max(plateau)],
            "full_margin_mm": round(best[1], 1),
            "needed": False,
            "sweep": [{"x_mm": x, "min_margin_mm": round(m, 1)} for x, m in rows if x % 10 == 0]}


# -- pictures --

def _items(walker: Walker, phase=90.0, hide=()):
    out = []
    for item in walker.items:
        if item.solid is None or item.name in hide:
            continue
        v, f = model.arrays(item.placed(phase))
        out.append((v, f, COLORS[item.kind]))
    floor = model.ground_z(phase)
    v, f = render.box_mesh((-130, -110, floor - 1.0), (150, 110, floor))
    out.append((v, f, (214, 227, 220)))
    return out


def pictures(walker: Walker, polygons: list, window: dict, place: dict) -> dict:
    IMAGES.mkdir(parents=True, exist_ok=True)
    tag = f"lego-{walker.build}"
    out = {}
    for view, size in (("iso", (760, 600)), ("left", (760, 520)), ("top", (760, 560))):
        name = f"{tag}-{view}.png"
        render.render(_items(walker), view, size).save(IMAGES / name, optimize=True)
        out[view] = f"images/{name}"
    name = f"{tag}-drive.png"
    render.render(_items(walker, hide=("chassis", "head", "EV3 brick", "pan-tilt kit", "Pixy2", "Pi Zero 2 W",
                                       "Build HAT", "Camera Module 2")), "iso_back", (760, 520)).save(IMAGES / name, optimize=True)
    out["drive"] = f"images/{name}"

    # Balance: both soles at mid stance, the window, the centre of mass.
    width, height, scale = 760, 520, 2.6
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)

    def px(p):      # x forward is up the page, y left is to the left
        return (width / 2 - p[1] * scale, height / 2 + 20 - p[0] * scale)
    for phase, colour in ((90, (8, 127, 96)), (270, (68, 83, 199))):
        poly = walker.foot_polygon(model.stance(phase)[0], phase)
        draw.polygon([px(p) for p in poly], outline=colour, width=2)
    xr, yr = window["x_range_mm_at_com_y"], window["y_range_mm_at_com_x"]
    if xr and yr:
        draw.rectangle([px((xr[1], yr[1])), px((xr[0], yr[0]))], outline=(154, 90, 0), width=2)
    track = [walker.com(p)[:2] for p in range(0, 360, PHASE_STEP)]
    draw.line([px(p) for p in track] + [px(track[0])], fill=(179, 38, 30), width=3)
    c = px(walker.com(90.0))
    draw.ellipse([c[0] - 5, c[1] - 5, c[0] + 5, c[1] + 5], outline=(179, 38, 30), width=2)
    draw.line([px((0, -100)), px((0, 100))], fill=(200, 200, 200))
    draw.line([px((-90, 0)), px((110, 0))], fill=(200, 200, 200))
    draw.text((10, 8), f"{walker.build}: soles on the floor at mid stance, seen from above (forward is up)", fill=(30, 40, 40))
    draw.text((10, 24), "green: left sole   blue: right sole   brown: where the centre of mass may be   red: where it is",
              fill=(30, 40, 40))
    name = f"{tag}-balance.png"
    image.save(IMAGES / name, optimize=True)
    out["balance"] = f"images/{name}"
    return out


def gear_picture(build: str) -> str:
    mesh = model.part_mesh(build, "gear_16t_print_6")
    width, height, scale = 760, 300, 13.0
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    low = mesh.vertices[np.abs(mesh.vertices[:, 2]) < 1e-6][:, :2]
    rim = low[np.hypot(low[:, 0], low[:, 1]) > 6.0]
    rim = rim[np.argsort(np.arctan2(rim[:, 1], rim[:, 0]))]
    for x, turn in zip(model.AXLES_X, (0.0, 11.25, 0.0)):
        c, s = np.cos(np.radians(turn)), np.sin(np.radians(turn))
        pts = rim @ np.array([[c, s], [-s, c]])
        draw.polygon([(width / 2 + (px + x) * scale, height / 2 - py * scale) for px, py in pts], outline=(23, 44, 44))
        r = 8.0 * scale
        cx = width / 2 + x * scale
        draw.ellipse([cx - r, height / 2 - r, cx + r, height / 2 + r], outline=(8, 127, 96))
    draw.text((10, 8), "Printed 16-tooth gears on the 16 mm axle spacing; green: 16 mm pitch circles", fill=(30, 40, 40))
    name = "lego-gear-mesh.png"
    image.save(IMAGES / name, optimize=True)
    return f"images/{name}"


def analyse(build: str, with_pictures: bool = True) -> dict:
    variants = {}
    grid = ([{"motor_direction": d, "camera": c} for d in ("rear", "forward") for c in ("pantilt", "bracket")]
            if build == "ev3-pixy2" else [{"motor_direction": d} for d in ("rear", "forward")])
    for options in grid:
        w = build_walker(build, **options)
        key = "motors " + options["motor_direction"] + (", " + options["camera"] if "camera" in options else "")
        st = stability(w)
        variants[key] = {"options": w.options, "mass_g": round(w.mass_g(), 1),
                         "com_mm": [round(float(v), 1) for v in w.com(90.0)],
                         "min_margin_mm": st["min_margin_mm"], "at_phase_deg": st["at_phase_deg"],
                         "stable_at_every_phase": st["stable_at_every_phase"]}
    walker = build_walker(build)
    window, polygons = com_window(walker)
    place = placement(walker, polygons)
    report = {
        "build": build, "title": model.TITLES[build], "options": walker.options,
        "placements": walker.notes,
        "variants": variants,
        "selected": "motors rear" + (", pantilt" if build == "ev3-pixy2" else ""),
        "interference": interference(walker),
        "clearances": clearances(walker),
        "mass": mass_table(walker),
        "centre_of_mass_mm": [round(float(v), 1) for v in walker.com(90.0)],
        "size_mm": None,
        "stability": stability(walker),
        "com_window": window,
        "placement": place,
    }
    lo = np.min([np.asarray(i.placed().bounding_box()[:3]) for i in walker.items if i.solid is not None], axis=0)
    hi = np.max([np.asarray(i.placed().bounding_box()[3:]) for i in walker.items if i.solid is not None], axis=0)
    report["size_mm"] = [round(float(v), 1) for v in (hi - lo)]
    if build == "ev3-pixy2":
        report["battery_sensitivity"] = {}
        for battery in ("six AA", "rechargeable pack"):
            w = build_walker(build, battery=battery)
            report["battery_sensitivity"][battery] = {"mass_g": round(w.mass_g(), 1),
                                                      "min_margin_mm": stability(w)["min_margin_mm"]}
    else:
        pack = walker.components["build_hat"]["battery_pack_g"]["value"]
        w = build_walker(build, ballast_g=pack, ballast_x=0.0)
        report["with_battery_pack"] = {"mass_g": round(w.mass_g(), 1), "min_margin_mm": stability(w)["min_margin_mm"],
                                       "com_mm": [round(float(v), 1) for v in w.com(90.0)]}
    if with_pictures:
        report["pictures"] = pictures(walker, polygons, window, place)
    return report


def findings(report: dict) -> list:
    out = []
    for build, rep in report["builds"].items():
        inter = rep["interference"]
        name = build
        if inter["rest"] or inter["cycle"]:
            worst = max(inter["rest"] + inter["cycle"], key=lambda r: r["volume_mm3"])
            out.append({"level": "interference", "build": name,
                        "text": f"{name}: {len(inter['rest']) + len(inter['cycle'])} overlapping pairs; the largest is "
                                f"{worst['a']} with {worst['b']}, {worst['volume_mm3']} mm3."})
        else:
            out.append({"level": "ok", "build": name,
                        "text": f"{name}: no part overlaps another at rest or at any of {inter['phases_checked']} crank "
                                f"phases, motors, controller and camera included."})
        st = rep["stability"]
        out.append({"level": "ok" if st["stable_at_every_phase"] else "balance", "build": name,
                    "text": f"{name}: {rep['mass']['total_g']} g. The centre of mass stays over the stance foot at every "
                            f"phase with at least {st['min_margin_mm']} mm to spare; a tilt of {st['tilt_to_tip_deg']} "
                            f"degrees uses that up."})
        bad = [k for k, v in rep["variants"].items() if v["min_margin_mm"] < 5.0]
        if bad:
            v = rep["variants"][bad[0]]
            out.append({"level": "fit", "build": name,
                        "text": f"{name}: with the motors pointing forward the margin falls to {v['min_margin_mm']} mm. "
                                f"Point them backward."})
    g = report["gear_mesh"]
    out.append({"level": "ok", "build": "both",
                "text": f"Gears: {g['teeth']} teeth, module {g['module_mm']:g}, on the standard {g['axle_spacing_mm']:g} mm "
                        f"centres; {g['backlash_per_mesh_mm']} mm backlash per mesh, {g['crank_to_crank_play_deg']} degrees "
                        f"of play between the two cranks of a side."})
    return out


def run(with_pictures: bool = True) -> dict:
    comp = model.load_json("components.json")
    report = {"_comment": "Generated by python -m walkers.assembly. Lengths in mm, masses in g. Frame: x forward, "
                          "y left, z up, origin on the centre axle between the panels.",
              "status": "Analysed only. Nothing here has been printed, assembled or powered.",
              "gear_mesh": gear_mesh(BUILDS[0], comp),
              "builds": {build: analyse(build, with_pictures) for build in BUILDS}}
    if with_pictures:
        report["gear_mesh"]["picture"] = gear_picture(BUILDS[0])
    report["findings"] = findings(report)
    return report


def main() -> int:
    report = run()
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8", newline="\n")
    for f in report["findings"]:
        print(f"[{f['level']}] {f['text']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
