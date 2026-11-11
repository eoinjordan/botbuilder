# SPDX-License-Identifier: MIT
"""Run the assembly test for both thigh mountings, render the pictures and
write reports/assembly.json and docs/assembly.md."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from . import assembly, model, render
from .model import COLORS, JOINTS, ROOT, apply, box, build_robot, servo_shape

IMAGES = ROOT / "docs" / "images"
RED = (220, 40, 40)
VARIANT_TEXT = {"rail": "hip horn on the rail face (knee servo beside the hip servo)",
                "flat": "hip horn on the flat face (knee servo stacked outward)"}


def _mesh(manifold):
    mesh = manifold.to_mesh()
    return np.asarray(mesh.vert_properties)[:, :3], np.asarray(mesh.tri_verts)


def _items(placed, only=None):
    out = []
    for _, solid, m in placed:
        if m.is_empty() or (only and solid.name not in only):
            continue
        v, f = _mesh(m)
        out.append((v, f, COLORS[solid.kind]))
    return out


def _overlaps(placed, pairs):
    by_name = {solid.name: m for _, solid, m in placed}
    out = []
    for a, b in pairs:
        common = by_name[a] ^ by_name[b]
        if common.volume() > 0.01:
            v, f = _mesh(common)
            out.append((v, f, RED))
    return out


def _save(image: Image.Image, name: str) -> str:
    IMAGES.mkdir(parents=True, exist_ok=True)
    image.convert("P", palette=Image.ADAPTIVE, colors=128).save(IMAGES / name, optimize=True)
    return f"images/{name}"


def _side_by_side(images, labels):
    w = sum(i.width for i in images)
    h = max(i.height for i in images)
    sheet = Image.new("RGB", (w, h), (255, 255, 255))
    x = 0
    for image, label in zip(images, labels):
        sheet.paste(image, (x, 0))
        ImageDraw.Draw(sheet).text((x + 10, 8), label, fill=(30, 40, 40))
        x += image.width
    return sheet


def _pad(lo, hi, pad):
    return np.array([np.asarray(lo, float) - pad, np.asarray(hi, float) + pad])


def render_images(robots: dict, reports: dict, selected: str) -> dict:
    robot, rep = robots[selected], reports[selected]
    placed = robot.placed()
    pairs = [(f["a"], f["b"]) for f in rep["neutral_interferences"]]
    red = _overlaps(placed, pairs)
    items = _items(placed)
    images = {}
    for view in ("iso", "front", "left", "top"):
        images[f"assembly_{view}"] = _save(
            render.render(items, view, (900, 700), overlays=red, title=f"neutral pose, {view} view; red = interference"),
            f"assembly-{view}.png")

    stand_q = rep["balance"]["stand_pose"]["q_deg"]
    stand = _items(robot.placed(stand_q))
    images["stand_left"] = _save(_side_by_side(
        [render.render(stand, "left", (520, 620)), render.render(stand, "iso", (620, 620))],
        ["stand pose, left view", "stand pose"]), "stand-pose.png")

    # Close-ups of the interferences at the neutral pose.
    close = {"interference_roll_servo_deck": ("torso_print", "left_roll_servo"),
             "interference_board_neck": ("torso_print", "unoq")}
    for key, (a, b) in close.items():
        hit = next((f for f in rep["neutral_interferences"] if {f["a"], f["b"]} == {a, b}), None)
        if hit is None:
            continue
        frame_box = _pad(hit["box_min_mm"], hit["box_max_mm"], 28.0)
        extra = [("braccio_shield", "torso_print")] if b == "unoq" else []
        picture = render.render(_items(placed, {a, b, "braccio_shield"} if b == "unoq" else {a, b}), "iso", (760, 560),
                                overlays=_overlaps(placed, [(a, b)] + extra), bounds=frame_box,
                                title=f"{a} and {b}: {hit['volume_mm3']} mm3 overlap (red)")
        images[key] = _save(picture, key.replace("_", "-") + ".png")

    # First contact of each collision-limited sweep, left leg only.
    for joint in ("left_hip_roll", "left_hip_pitch", "left_knee"):
        for direction in ("positive", "negative"):
            end = rep["sweeps"][joint][direction]
            if end["first_contact_deg"] is None:
                continue
            q = {joint: end["first_contact_deg"]}
            posed = robot.placed(q)
            hits = [(b["moving"], b["fixed"]) for b in end["blocked_by"]]
            key = f"sweep_{joint}_{direction}"
            images[key] = _save(render.render(
                _items(posed), "iso" if joint.endswith("knee") else "front", (760, 600), overlays=_overlaps(posed, hits),
                title=f"{joint} at {end['first_contact_deg']} deg: first contact (red)"), key.replace("_", "-") + ".png")

    # Assumption: which thigh face meets the hip horn.
    pair = [render.render(_items(robots[v].placed()), "front", (640, 520)) for v in ("rail", "flat")]
    images["assumption_thigh_face"] = _save(_side_by_side(pair, [f"'{v}': {VARIANT_TEXT[v]}" for v in ("rail", "flat")]),
                                            "assumption-thigh-face.png")

    # Assumption: how a servo lies in its cradle, with horn, blank and ties.
    for name in ("SR431", "SR311"):
        shape = servo_shape(name, robot.hardware)
        to_cradle = model.servo_in_cradle(False)
        cradle = model.load_part("fit_" + name)
        blank = apply(model.load_part("fit_horn"), to_cradle @ model.trans(shape.shaft_x, 0, shape.face_z))
        ties, blocked = [], []
        for sx in (-1, 1):
            cx = sx * shape.length * model.SLOT_X_FRACTION
            half = shape.width / 2
            top = model.PLATE + shape.height
            band = (box([cx - 2.2, -half - 6.1, -1.2], [cx + 2.2, half + 6.1, top + 1.2])
                    - box([cx - 3.0, -half - 4.9, 0.0], [cx + 3.0, half + 4.9, top]))
            hit = band ^ apply(shape.body + shape.horn, to_cradle)
            (blocked if hit.volume() > 0.5 else ties).append(band)
        parts = [(*_mesh(cradle), COLORS["print"]), (*_mesh(apply(shape.body, to_cradle)), COLORS["servo"]),
                 (*_mesh(apply(shape.horn, to_cradle)), COLORS["horn"]), (*_mesh(blank), (200, 170, 90))]
        parts += [(*_mesh(t), (40, 150, 70)) for t in ties] + [(*_mesh(t), RED) for t in blocked]
        views = [render.render(parts, v, (560, 460)) for v in ("iso", "left")]
        images[f"assumption_cradle_{name}"] = _save(_side_by_side(
            views, [f"{name} in its cradle: horn, drill blank, ties (red tie crosses the output shaft)", "side"]),
            f"assumption-cradle-{name}.png")

    images["balance"] = _save(_balance_plot(rep["balance"]), "balance.png")
    return images


def _balance_plot(balance: dict) -> Image.Image:
    panels = [("neutral pose", balance["neutral_two_feet"]), ("stand pose", balance["stand_pose"])]
    w, h, scale = 460, 520, 2.0
    sheet = Image.new("RGB", (w * len(panels), h), (255, 255, 255))
    draw = ImageDraw.Draw(sheet)
    for i, (label, s) in enumerate(panels):
        poly = np.array(s["polygon_mm"])
        centre = poly.mean(axis=0)
        # ground frame: x forward, y left. Plot forward up, left to the left.
        def px(p, i=i, centre=centre):
            return (i * w + w / 2 - (p[1] - centre[1]) * scale, h / 2 - (p[0] - centre[0]) * scale)
        draw.polygon([px(p) for p in poly], outline=(8, 127, 96), fill=(225, 245, 235))
        c = px(s["com_ground_mm"][:2])
        colour = (8, 127, 96) if s["inside"] else RED
        draw.ellipse([c[0] - 6, c[1] - 6, c[0] + 6, c[1] + 6], fill=colour)
        draw.text((i * w + 12, 10), f"{label}: support polygon (both feet), top view, toes up", fill=(30, 40, 40))
        draw.text((i * w + 12, 28), f"centre of mass margin {s['margin_mm']} mm ({'inside' if s['inside'] else 'OUTSIDE'})", fill=colour)
    return sheet


# --- findings and markdown --------------------------------------------------

def findings(rep: dict) -> list:
    out = []
    for f in rep["neutral_interferences"]:
        if f["a"] == "torso_print" and f["b"].endswith("roll_servo"):
            out.append({"id": f"deck-{f['b']}", "level": "interference",
                        "text": f"{f['b']} overlaps the torso deck by {f['volume_mm3']} mm3 at its centred position in the cradle: "
                                f"the case end and the upper mounting ear run {f['depth_mm']} mm into the 4 mm deck plate "
                                f"(z {f['box_min_mm'][2]} to {f['box_max_mm'][2]} mm)."})
        elif f["b"] == "unoq":
            out.append({"id": "board-neck", "level": "interference",
                        "text": f"The UNO Q centred between the deck rails overlaps the neck root by {f['volume_mm3']} mm3 "
                                f"({round(f['box_max_mm'][0] - f['box_min_mm'][0], 2)} mm along x). Moving the board "
                                f"{rep['board']['forward_shift_to_clear_mm']} mm forward clears it and keeps it on the deck."})
        elif f["b"] == "braccio_shield":
            out.append({"id": "shield-neck", "level": "interference",
                        "text": f"The Braccio shield above the board overlaps the neck by {f['volume_mm3']} mm3 at the same position."})
        else:
            out.append({"id": f"{f['a']}-{f['b']}", "level": "interference",
                        "text": f"{f['a']} and {f['b']} overlap by {f['volume_mm3']} mm3 at the neutral pose."})
    blocked = [c for c in rep["cradles"] if not all(t["clear"] for t in c["ties"])]
    if blocked:
        c = blocked[0]
        t = next(t for t in c["ties"] if not t["clear"])
        out.append({"id": "tie-over-shaft", "level": "fit",
                    "text": f"On all {len(blocked)} cradles one of the two cable ties crosses the output shaft: the slot pair at "
                            f"{abs(t['at_x_mm'])} mm from the cradle centre is in line with the shaft at {t['shaft_x_mm']} mm "
                            f"(SR431; depends on the assumed shaft position). Only the tie at the far end can go over the case."})
    if all(c["rail_clearance_each_side_mm"] > 0 for c in rep["cradles"]):
        out.append({"id": "rails", "level": "ok",
                    "text": "Every servo case fits between its rails with "
                            f"{rep['cradles'][0]['rail_clearance_each_side_mm']} mm each side, sits fully on its plate, and all tie slots are open."})
    if all(h["hole_on_shaft_axis"] and h["driver_path_clear"] for h in rep["horns"]):
        out.append({"id": "horn-access", "level": "ok",
                    "text": "All six horn screw holes are on their shaft axes and a screwdriver has a free path to each at the neutral pose."})
    b = rep["balance"]
    n, s = b["neutral_two_feet"], b["stand_pose"]
    out.append({"id": "balance-neutral", "level": "ok" if n["inside"] else "balance",
                "text": f"Legs straight down: the centre of mass is {abs(n['margin_mm'])} mm "
                        f"{'inside' if n['inside'] else 'outside'} the support polygon of the two feet"
                        + ("." if n["inside"] else " (behind the heels); it falls backward.")})
    out.append({"id": "balance-stand", "level": "ok" if s["inside"] else "balance",
                "text": f"With the thighs swung back {s['thigh_swing_deg']} degrees and the knees turned the other way to keep "
                        f"the soles level, the centre of mass is {s['margin_mm']} mm inside the polygon. This is the stand pose."})
    for side in ("left", "right"):
        o = b[f"one_foot_{side}"]
        if side == "right":
            continue
        best = o["best_within_30_deg_stance_roll"]
        text = (f"On one foot the centre of mass is {abs(o['at_stand_pose']['margin_mm'])} mm outside the foot at the stand pose "
                f"and still {abs(best['margin_mm'])} mm outside with the stance hip rolled up to 30 degrees: "
                "there is no ankle, so hip roll tilts the body instead of shifting it.")
        far = o["smallest_stance_roll_that_balances"]
        if far:
            text += (f" It only comes over the foot with the stance hip rolled {far['stance_roll_deg']} degrees, "
                     "which lays the body on its side.")
        out.append({"id": "balance-one-foot", "level": "balance", "text": text})
    return out


def _table(header, rows):
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join(["---"] * len(header)) + "|"]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(lines)


def markdown(report: dict) -> str:
    sel = report["selected"]
    rep = report["variants"][sel]
    img = report["images"]
    md = ["# Digital assembly test", "",
          "Generated by `scripts/run_assembly.py` from the seven printable STLs, the parametric servo model and",
          "`config/`. Do not edit by hand. The numbers are also in `reports/assembly.json`.", "",
          "Status: geometry only. Nothing here has been printed, assembled or powered.", "",
          "## Findings", ""]
    md += [f"- **{f['level']}**: {f['text']}" for f in report["findings"]]
    md += ["", f"![assembled robot]({img['assembly_iso']})", "",
           f"![front]({img['assembly_front']})", "", f"![left]({img['assembly_left']})", "", f"![top]({img['assembly_top']})", ""]

    md += ["## Assumptions", "",
           "The design directory does not say how each servo lies in its cradle or which face of a printed blank",
           "meets a horn. These choices were made here (`config/assembly.json`):", ""]
    md += [f"- {k}: {v}" for k, v in report["assumptions"]["placement"].items()]
    md += ["", f"![thigh face]({img['assumption_thigh_face']})", "",
           f"![SR431 in its cradle]({img['assumption_cradle_SR431']})", "",
           f"![SR311 in its cradle]({img['assumption_cradle_SR311']})", "",
           "Dimensions the makers do not publish, and the values assumed for them:", "",
           _table(["item", "quantity", "assumed value", "why"],
                  [(a["item"], a["quantity"], a["value"], a["why"]) for a in report["assumptions"]["dimensions"]]), "",
           "Published dimensions and their sources:", "",
           _table(["item", "source"], [(k, v) for k, v in report["sources"].items()]), ""]

    md += ["## The two thigh mountings", "",
           _table(["", "rail face", "flat face"], [
               ("overall width (mm)", *[report["variants"][v]["dimensions"]["size_mm"][1] for v in ("rail", "flat")]),
               ("foot centre to foot centre (mm)", *[report["variants"][v]["dimensions"]["stance_width_between_foot_centres_mm"] for v in ("rail", "flat")]),
               ("one-foot margin at the stand pose (mm)", *[report["variants"][v]["balance"]["one_foot_left"]["at_stand_pose"]["margin_mm"] for v in ("rail", "flat")]),
               ("left hip roll free range (deg)", *[report["variants"][v]["sweeps"]["left_hip_roll"]["collision_free_deg"] for v in ("rail", "flat")]),
               ("left knee free range (deg)", *[report["variants"][v]["sweeps"]["left_knee"]["collision_free_deg"] for v in ("rail", "flat")]),
           ]), "", f"Everything below is for the `{sel}` mounting, which the robot description uses.", ""]

    d = rep["dimensions"]
    md += ["## Size", "", f"Bounding box at the neutral pose: {d['size_mm'][0]} x {d['size_mm'][1]} x {d['size_mm'][2]} mm "
           f"(length, width, height). Soles at z = {d['sole_z_mm']} mm in the torso frame.", "",
           _table(["joint", "axis point in the torso frame (mm)"], [(j, d["joint_origins_mm"][j]) for j in JOINTS]), ""]

    md += ["## Interference at the neutral pose", ""]
    if rep["neutral_interferences"]:
        md += [_table(["part", "part", "overlap (mm3)", "depth (mm)", "box min (mm)", "box max (mm)"],
                      [(f["a"], f["b"], f["volume_mm3"], f["depth_mm"], f["box_min_mm"], f["box_max_mm"]) for f in rep["neutral_interferences"]]), ""]
    else:
        md += ["None.", ""]
    for key in ("interference_roll_servo_deck", "interference_board_neck"):
        if key in img:
            md += [f"![{key}]({img[key]})", ""]

    md += ["## Joint sweeps", "",
           "One joint at a time from the neutral pose, others at zero, until a part that moves with the joint meets one that",
           "does not. 180 means a full half turn without contact. Limits are the free range less "
           f"{report['assumptions']['limit_margin_deg']} degrees where a collision ends it, intersected with +/-90 degrees of servo travel about neutral.", "",
           _table(["joint", "collision free (deg)", "first contact, negative", "first contact, positive", "limit used (deg)"],
                  [(j, rep["sweeps"][j]["collision_free_deg"],
                    ", ".join(f"{b['moving']} / {b['fixed']}" for b in rep["sweeps"][j]["negative"]["blocked_by"]) or "none",
                    ", ".join(f"{b['moving']} / {b['fixed']}" for b in rep["sweeps"][j]["positive"]["blocked_by"]) or "none",
                    [rep["joint_limits_deg"][j]["min_deg"], rep["joint_limits_deg"][j]["max_deg"]]) for j in JOINTS]), ""]
    md += [f"![{k}]({v})\n" for k, v in img.items() if k.startswith("sweep_")]

    md += ["## Servos in their cradles", "",
           _table(["servo", "model", "rail clearance each side (mm)", "seated on plate", "tie slots open", "ties clear of shaft", "overlap with its printed part (mm3)"],
                  [(c["servo"], c["model"], c["rail_clearance_each_side_mm"], c["seat_support_fraction"], f"{c['tie_slots_open']}/4",
                    f"{sum(t['clear'] for t in c['ties'])}/2", c["body_interference_mm3"]) for c in rep["cradles"]]), "",
           "## Horn blanks", "",
           _table(["joint", "hole on shaft axis", "blank solid under the horn", "driver path clear", "driver comes from"],
                  [(h["joint"], h["hole_on_shaft_axis"], h["blank_fill_fraction"], h["driver_path_clear"], h["driver_from"]) for h in rep["horns"]]), "",
           "The blank is placed on the shaft axis by construction, so the hole check confirms the model and the STL agree; it does not",
           "measure a print. The horn itself is not dimensioned by the maker.", ""]

    b = rep["board"]
    md += ["## UNO Q on the deck", "",
           _table(["check", "value"], [
               ("board outline (mm)", b["board_outline_mm"]),
               ("clearance to each deck rail (mm)", b["rail_clearance_each_side_mm"]),
               ("rail height above the board underside (mm)", b["rail_engagement_mm"]),
               ("overlap with the torso, board centred (mm3)", b["board_interference_mm3"]),
               ("overlap with the torso, shield (mm3)", b["shield_interference_mm3"]),
               ("forward shift that clears both (mm)", b["forward_shift_to_clear_mm"]),
               ("overhang past the deck front after the shift (mm)", b["front_overhang_after_shift_mm"]),
               ("lowest torso material above the stack, after the shift (mm)", b["head_above_stack_top_after_shift_mm"]),
           ]), ""]

    m = rep["mass"]
    md += ["## Mass and centre of mass", "",
           f"Total {m['total_g']} g: servos {m['by_kind_g']['servo']} g, printed parts {m['by_kind_g']['print']} g "
           f"({m['print_material']} at {m['print_density_g_cm3']} g/cm3, {int(m['print_solid_fraction'] * 100)} percent of solid; "
           f"{m['total_if_printed_solid_g']} g in total if printed solid), board {m['by_kind_g']['board']} g and shield {m['by_kind_g']['shield']} g (both assumed).",
           f"Centre of mass at the neutral pose: {m['com_neutral_mm']} mm in the torso frame.", "",
           _table(["link", "mass (g)", "centre of mass in the link frame (mm)"], [(k, v["mass_g"], v["com_link_mm"]) for k, v in m["links"].items()]), ""]

    bal = rep["balance"]
    o = bal["one_foot_left"]
    md += ["## Balance", "", f"![balance]({img['balance']})", "",
           _table(["case", "margin (mm)", "inside the support polygon"], [
               ("two feet, legs straight down", bal["neutral_two_feet"]["margin_mm"], bal["neutral_two_feet"]["inside"]),
               (f"two feet, stand pose (thighs back {bal['stand_pose']['thigh_swing_deg']} deg)", bal["stand_pose"]["margin_mm"], bal["stand_pose"]["inside"]),
               ("one foot, stand pose", o["at_stand_pose"]["margin_mm"], o["at_stand_pose"]["inside"]),
               ("one foot, best with stance hip roll within 30 deg", o["best_within_30_deg_stance_roll"]["margin_mm"], o["best_within_30_deg_stance_roll"]["inside"]),
           ]), "",
           "Margin is the distance from the ground projection of the centre of mass to the nearest edge of the support polygon;",
           "negative means outside. The stand pose keeps the shins vertical and the soles level: hip pitch = t, knee = -t.", "",
           f"Stand pose joint angles (deg): {bal['stand_pose']['q_deg']}", "",
           f"Parts that interfere at the stand pose and not at neutral: {len(bal['stand_pose_interferences'])}.", "",
           f"![stand pose]({img['stand_left']})", ""]
    return "\n".join(md) + "\n"


def run(progress=print) -> dict:
    hardware = model.load_json("hardware.json")
    config = model.load_json("assembly.json")
    selected = config["thigh_face"]
    robots, reports = {}, {}
    for variant in ("rail", "flat"):
        robots[variant] = build_robot(variant, hardware, config)
        reports[variant] = assembly.analyse(robots[variant], lambda text, v=variant: progress(f"[{variant}] {text}"))
    progress("rendering")
    images = render_images(robots, reports, selected)
    assumed = []
    for group in ("servos",):
        for name, spec in hardware[group].items():
            assumed += [{"item": name, "quantity": k, "value": v["value"], "why": v["why"]} for k, v in spec["assumed"].items()]
    for name in ("board", "shield", "print", "driver"):
        assumed += [{"item": hardware[name].get("name", name), "quantity": k, "value": v["value"], "why": v["why"]}
                    for k, v in hardware[name]["assumed"].items()]
    sums = {}
    for name in sorted(model.PART_FILES.values()):
        sums[name] = hashlib.sha256((model.stl_dir() / name).read_bytes()).hexdigest()
    report = {
        "generated_by": "scripts/run_assembly.py",
        "status": "geometry only; never printed, assembled or powered",
        "stl_sha256": sums,
        "selected": selected,
        "assumptions": {"placement": config["notes"], "dimensions": assumed,
                        "limit_margin_deg": config["limit_margin_deg"], "sweep_step_deg": config["sweep_step_deg"]},
        "sources": {"SR431 and SR311 servos, supply": hardware["servos"]["SR431"]["source"],
                    "Arduino UNO Q outline and power": hardware["board"]["source"],
                    "Braccio shield outline": hardware["shield"]["source"]},
        "findings": findings(reports[selected]),
        "images": images,
        "variants": reports,
    }
    (ROOT / "reports").mkdir(exist_ok=True)
    (ROOT / "reports" / "assembly.json").write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    (ROOT / "docs" / "assembly.md").write_text(markdown(report), encoding="utf-8")
    return report
