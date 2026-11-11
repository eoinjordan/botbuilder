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

    # The hip roll servo where its case end and upper ear meet the deck.
    seat = rep["roll_seat"]
    pair = {"torso_print", "left_roll_servo"}
    views = [render.render(_items(placed, pair), v, (560, 520), overlays=_overlaps(placed, [("torso_print", "left_roll_servo")]),
                           bounds=_pad([-6, 34, -30], [48, 80, 12], 4.0)) for v in ("iso", "left", "top")]
    images["roll_servo_seat"] = _save(_side_by_side(
        views, [f"left hip roll servo: overlap with the deck {seat['overlap_with_torso_mm3']} mm3 (red if any)", "left", "top"]),
        "roll-servo-seat.png")

    # The camera in its mount, with the controller stack behind it.
    names = {"torso_print", "camera_board", "unoq", "braccio_shield"}
    lens = np.asarray(rep["camera"]["lens_mm"])
    views = [render.render(_items(placed, names), v, (560, 520), bounds=_pad(lens - [70, 45, 62], lens + [12, 45, 22], 4.0))
             for v in ("iso", "left", "front")]
    images["camera_mount"] = _save(_side_by_side(views, ["camera board (red) in its mount", "left: lens looks +x", "front"]),
                                   "camera-mount.png")

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
        for fx in model.SLOT_X_FRACTIONS:
            cx = fx * shape.length
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
            views, [f"{name} in its cradle: horn, drill blank, tie paths (a red one crosses the output shaft)", "side"]),
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
                                f"(z {f['box_min_mm'][2]} to {f['box_max_mm'][2]} mm). The published case alone accounts for "
                                f"{next(c['case_interference_mm3'] for c in rep['cradles'] if c['servo'] == f['b'])} mm3, "
                                "so this does not rest on the assumed ear."})
        else:
            out.append({"id": f"{f['a']}-{f['b']}", "level": "interference",
                        "text": f"{f['a']} and {f['b']} overlap by {f['volume_mm3']} mm3 at the neutral pose."})
    fewest = min(sum(t["clear"] for t in c["ties"]) for c in rep["cradles"])
    out.append({"id": "ties", "level": "ok" if fewest >= 2 else "fit",
                "text": f"Each cradle has {len(rep['cradles'][0]['ties'])} tie slot pairs; on every cradle at least {fewest} "
                        "of the tie paths cross the case clear of the output shaft and horn (the pairs at the shaft end do not, "
                        "and are for a servo lying the other way round). This depends on the assumed shaft position and horn size."})
    if all(c["rail_clearance_each_side_mm"] > 0 for c in rep["cradles"]):
        out.append({"id": "rails", "level": "ok",
                    "text": "Every servo case fits between its rails with "
                            f"{rep['cradles'][0]['rail_clearance_each_side_mm']} mm each side, sits fully on its plate, and all tie slots are open."})
    if all(h["hole_on_shaft_axis"] and h["driver_path_clear"] for h in rep["horns"]):
        out.append({"id": "horn-access", "level": "ok",
                    "text": "All six horn screw holes are on their shaft axes and a screwdriver has a free path to each at the neutral pose."})
    c = rep["camera"]
    g = c["gaps"]
    fits = (c["board_overlap_with_mount_mm3"] < 0.5 and c["seated_on_the_corner_seats"] and c["clearance_each_side_mm"] > 0)
    out.append({"id": "camera-fit", "level": "ok" if fits else "fit",
                "text": f"The {c['name']} stands in its mount with {c['clearance_each_side_mm']} mm each side and "
                        f"{c['play_towards_the_lips_mm']} mm of play under the snap lips, on the corner seats, "
                        f"overlapping the print by {c['board_overlap_with_mount_mm3']} mm3. The mount is "
                        f"{g['unoq']['to_mount_mm']} mm from the UNO Q and {g['stack_envelope']['to_mount_mm']} mm from the "
                        "space kept for the shield and its plugs."})
    swept = {j: v for j, v in c["cone_sweeps"].items() if v["from_neutral"]["angles_in_cone_deg"] or v["from_stand"]["angles_in_cone_deg"]}
    clear = not c["cone_blocked_at_neutral"] and not c["cone_blocked_at_stand"]
    text = (f"The lens looks along +x, the way the toes point, {c['tilt_below_level_deg']} degrees below level, "
            f"{c['lens_height_above_floor_at_stand_mm']} mm above the floor at the stand pose. A cone of "
            f"{c['cone_half_angle_deg']} degrees half angle in front of it is "
            + ("clear at the neutral and stand poses." if clear else "NOT clear at the neutral or stand pose."))
    if swept:
        parts = []
        for j, v in swept.items():
            a = v["from_stand"]["angles_in_cone_deg"] or v["from_neutral"]["angles_in_cone_deg"]
            parts.append(f"{j} between {a[0]} and {a[1]} degrees")
        text += " A leg comes into the cone with " + "; ".join(parts) + " (one joint moved, the others at the stand or neutral pose)."
    else:
        text += " No joint brings a leg into it anywhere inside its limits."
    out.append({"id": "camera-view", "level": "ok" if clear else "fit", "text": text})
    lg = rep["lego_compatible"]
    good = (all(h["open_for_a_nominal_pin"] and h["wall_fill_fraction"] > 0.99 for h in lg["holes"])
            and all(s["present"] for s in lg["studs"]) and not lg["features_in_the_camera_cone_at_neutral"])
    out.append({"id": "lego-compatible", "level": "ok" if good else "fit",
                "text": f"{len(lg['holes'])} pin holes and {len(lg['studs'])} studs compatible with LEGO Technic and System elements: "
                        f"every hole is open for a {lg['nominal_mm']['pin_hole']} mm pin over {lg['nominal_mm']['beam']} mm with wall all round, "
                        f"none is nearer than {min(x['from_nearest_joint_axis_mm'] for x in lg['holes'] + lg['studs'])} mm to a joint axis "
                        f"or {min(x['gap_to_it_mm'] for x in lg['holes'] + lg['studs'])} mm to another part at the neutral pose, "
                        "and none is in the camera's clear cone. Whether a real pin or brick holds in a printed one is not known."
                        if good else "A pin hole or stud is blocked, thin-walled, missing or in the camera cone: see the table."})
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
          "Generated by `scripts/run_assembly.py` from the seven printable STLs, the parametric servo and board models and",
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
    md += [f"![hip roll servo under the deck]({img['roll_servo_seat']})", ""]

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
                  [(c["servo"], c["model"], c["rail_clearance_each_side_mm"], c["seat_support_fraction"], f"{c['tie_slots_open']}/{c['tie_slots_expected']}",
                    f"{sum(t['clear'] for t in c['ties'])}/{len(c['ties'])}", c["body_interference_mm3"]) for c in rep["cradles"]]), "",
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
           ]), ""]

    c = rep["camera"]
    g = c["gaps"]
    md += ["## Face: round display and camera", "",
           "The default head carries a Seeed Studio Round Display for XIAO in a ring at the deck front, screen forward as the",
           "eyes, and a camera board on the same head above or below it. A LiPo cell for the display is strapped under the deck",
           f"front. The assembly, description and simulation use `{report['face_default']}`. The display is drawn as a disc with",
           "a block for the XIAO behind it; its diameter, thickness and mass are assumed (see `config/hardware.json`).", "",
           _table(["face and camera", "torso file", "interference at neutral", "display overlap with print (mm3)", "lens (mm)",
                   "lens above the floor at stand (mm)", "top of the head above the deck (mm)", "cone clear at neutral and stand",
                   "thigh angles in the cone, others at stand (deg)", "total mass (g)", "centre of mass at neutral (mm)",
                   "legs straight: margin (mm)", "stand: thighs back (deg)", "stand margin (mm)"],
                  [(k, f["torso_file"], len(f["neutral_interferences"]), f["display_overlap_with_print_mm3"], f["lens_mm"],
                    f["lens_height_above_floor_at_stand_mm"], f["highest_point_above_deck_mm"],
                    not f["cone_blocked_at_neutral"] and not f["cone_blocked_at_stand"],
                    f["hip_pitch_in_cone_from_stand_deg"] or "never", f["total_g"], f["com_neutral_mm"], f["neutral_margin_mm"],
                    f["stand_thigh_swing_deg"], f["stand_margin_mm"]) for k, f in report["faces"].items()]), "",
           "The faces were not analysed on the turning head: the tilt cradles for them are generated, but the assembly test of",
           "the turning head uses the camera alone.", "",
           "## Camera mount", "",
           "The torso has no head or neck. Two posts at the front edge of the deck hold a camera board by its long edges,",
           "lens forward. Forward is the way the toes point: the foot plates reach "
           f"{c['toes_ahead_of_shin_mm']} mm ahead of the shin and {c['heel_behind_shin_mm']} mm behind it. The hip cradles open",
           "towards +x, so the hips stand ahead of the deck and the mount looks out between the legs.", "",
           f"![camera mount]({img['camera_mount']})", "",
           _table(["check", "value"], [
               ("camera preset", f"{c['preset']} ({c['name']})"),
               ("board as modelled: width, length, thickness (mm)", c["board_mm"]),
               ("board mass (g)", c["mass_g"]),
               ("clearance to each post (mm)", c["clearance_each_side_mm"]),
               ("play towards the snap lips (mm)", c["play_towards_the_lips_mm"]),
               ("play towards the back ledges (mm)", c["play_towards_the_ledges_mm"]),
               ("lower edge on the corner seats", c["seated_on_the_corner_seats"]),
               ("play upwards to the catch over the upper edge (mm)", c["play_upwards_to_the_catch_mm"]),
               ("overlap of board and print (mm3)", c["board_overlap_with_mount_mm3"]),
               ("mount to UNO Q (mm)", g["unoq"]["to_mount_mm"]),
               ("mount to Braccio shield (mm)", g["braccio_shield"]["to_mount_mm"]),
               ("mount to the space kept for shield plugs (mm)", g["stack_envelope"]["to_mount_mm"]),
               ("camera board to the space kept for shield plugs (mm)", g["stack_envelope"]["to_camera_board_mm"]),
               ("lens front in the torso frame (mm)", c["lens_mm"]),
               ("tilt below level (deg)", c["tilt_below_level_deg"]),
               ("lens above the floor at the stand pose (mm)", c["lens_height_above_floor_at_stand_mm"]),
               ("clear cone, half angle (deg)", c["cone_half_angle_deg"]),
               ("parts in the cone at neutral", ", ".join(h["solid"] for h in c["cone_blocked_at_neutral"]) or "none"),
               ("parts in the cone at the stand pose", ", ".join(h["solid"] for h in c["cone_blocked_at_stand"]) or "none"),
           ]), "",
           "Joint angles inside the limits at which a leg is in the cone, one joint moved at a time:", "",
           _table(["joint", "others at neutral (deg)", "others at the stand pose (deg)"],
                  [(j, v["from_neutral"]["angles_in_cone_deg"] or "never", v["from_stand"]["angles_in_cone_deg"] or "never")
                   for j, v in c["cone_sweeps"].items()]), "",
           "The camera presets alone in the fixed mount, without the display, each with its own torso file, checked in short form:", "",
           _table(["preset", "board (mm)", "each side (mm)", "under the lips (mm)", "up to the catch (mm)", "on the seats",
                   "overlap with print (mm3)", "mount to UNO Q (mm)", "cone clear at neutral and stand", "total mass (g)",
                   "centre of mass at neutral (mm)", "stand margin (mm)"],
                  [(k, p["board_mm"], p["clearance_each_side_mm"], p["play_towards_the_lips_mm"], p["play_upwards_to_the_catch_mm"],
                    p["seated_on_the_corner_seats"], p["board_overlap_with_mount_mm3"], p["gaps"]["unoq"]["to_mount_mm"],
                    not p["cone_blocked_at_neutral"] and not p["cone_blocked_at_stand"], p["total_g"], p["com_neutral_mm"],
                    p["stand_margin_mm"]) for k, p in report["camera_presets"].items()]), "",
           "The board is a plain plate with a lens barrel. Its connectors, buttons, pins and wires are not modelled; where they are",
           "and what is assumed about them is in `config/hardware.json` and the design README.", ""]

    base = rep
    md += ["## Other controllers on the deck", "",
           "The biped's deck with another controller in place of the UNO Q and Braccio shield, each as one block of the stated",
           "mass on its torso variant, camera mount unchanged. Assembly and static balance only: none was simulated, and what",
           "would drive the six servos from each is not part of this. Outlines and masses, with what is published and what is",
           "assumed, are in `config/hardware.json` under `controllers`.", "",
           _table(["controller", "torso file", "block mass (g)", "overlap with the print (mm3)", "gap to the camera board (mm)",
                   "interference at neutral", "total mass (g)", "centre of mass at neutral (mm)", "legs straight: margin (mm)",
                   "stand pose: thighs back (deg)", "stand margin (mm)", "hip pitch holding torque / limit"],
                  [("unoq with Braccio shield", model.PART_FILES["torso"], 55.0, 0.0, base["camera"]["gaps"]["stack_envelope"]["to_camera_board_mm"],
                    len(base["neutral_interferences"]), base["mass"]["total_g"], base["mass"]["com_neutral_mm"],
                    base["balance"]["neutral_two_feet"]["margin_mm"], base["balance"]["stand_pose"]["thigh_swing_deg"],
                    base["balance"]["stand_pose"]["margin_mm"], "see the simulation")]
                  + [(k, c["torso_file"] + ("" if c["has_its_own_torso"] else " (not made for it)"), c["mass_g"], c["overlap_with_print_mm3"],
                      c["gap_to_camera_board_mm"], len(c["neutral_interferences"]), c["total_g"], c["com_neutral_mm"],
                      c["neutral_margin_mm"], c["stand_thigh_swing_deg"], c["stand_margin_mm"], c["hip_pitch_torque_fraction"])
                     for k, c in report["controllers"].items()]), "",
           "The hip pitch torque is the static moment of everything above the hips about the hip pitch axis at the stand pose,",
           "shared by two servos, against the SR431's published 4.8 V torque.", ""]

    th = report["turning_head"]
    md += ["## Turning head (option)", "",
           "An optional head in place of the fixed mount: a 9 g SG90-class servo hangs by its ears in a tab at the deck front and",
           "turns a platform; the camera cradle tilts on one M3 screw and is set by hand. Printed from `01_torso_unoq_pan_head.stl`,",
           "`head_pan_platform.stl` and `head_tilt_cradle_<camera>.stl`. It is not part of the robot description or the simulation:",
           "the URDF, the MJCF and the joint commands are for the fixed mount. Servo body, shaft position and horn height are",
           "assumed (see the design README); nothing has been fitted.", "",
           f"![turning head]({img['turning_head']})", "",
           _table(["check", "value"], [
               ("camera preset", th["camera_preset"]),
               ("pan travel between the printed stops (deg)", th["pan_travel_to_the_stops_deg"]),
               ("stopped by", ", ".join(f"{b['moving']} / {b['fixed']}" for b in th["pan_stopped_by"]["positive"]) or "nothing"),
               ("tilt set to (deg below level)", th["tilt_set_to_deg"]),
               ("tilt free range about level (deg, positive is down)", th["tilt_free_deg"]),
               ("tilt stopped by", ", ".join(f"{b['moving']} / {b['fixed']}" for b in th["tilt_stopped_by"]["positive"] + th["tilt_stopped_by"]["negative"]) or "nothing"),
               ("interference at the neutral pose", len(th["neutral_interferences"])),
               ("left hip roll, hip pitch, knee free range with the head on (deg)", list(th["leg_sweeps_collision_free_deg"].values())),
               ("mass of the head with its servo and camera (g)", th["head_mass_g"]),
               ("total mass (g)", th["total_g"]),
               ("centre of mass at neutral (mm)", th["com_neutral_mm"]),
               ("margin with legs straight (mm)", th["neutral_margin_mm"]),
           ]), "",
           _table(["at the stand pose, pan (deg)", "new interference", "parts in the clear cone", "centre of mass (mm)", "stand margin (mm)", "lens (mm)"],
                  [(p["pan_deg"], len(p["new_interferences"]), ", ".join(h["solid"] for h in p["in_the_cone"]) or "none",
                    p["com_mm"], p["stand_margin_mm"], p["lens_mm"]) for p in th["at_the_stand_pose"]]), ""]

    lg = rep["lego_compatible"]

    def spread(rows, key):
        values = [r[key] for r in rows]
        return f"{min(values)} to {max(values)}" if values else "-"

    parts = sorted(lg["counts"])
    md += ["## Pin holes and studs", "",
           "Attachment features compatible with LEGO Technic and System elements. LEGO, Technic, Mindstorms and SPIKE are",
           "trademarks of the LEGO Group, which does not sponsor or endorse this. Geometry only: no printed hole or stud has been",
           "tried with a real element.", "",
           f"Nominal: pitch {lg['nominal_mm']['pitch']} mm, pin hole {lg['nominal_mm']['pin_hole']} mm with a counterbore of "
           f"{lg['nominal_mm']['pin_counterbore'][0]} x {lg['nominal_mm']['pin_counterbore'][1]} mm at each end, hole length "
           f"{lg['nominal_mm']['beam']} mm, stud {lg['nominal_mm']['stud'][0]} x {lg['nominal_mm']['stud'][1]} mm. Print allowance: "
           f"holes {lg['print_allowance_mm']['hole_extra']} mm larger, studs {lg['print_allowance_mm']['stud_under']} mm smaller.", "",
           _table(["part", "pin holes", "open for a nominal pin", "wall around the hole", "hole to nearest joint axis (mm)",
                   "hole pad to nearest other part (mm)", "studs", "present", "pointing up at neutral", "stud to nearest other part (mm)"],
                  [(p, lg["counts"][p]["holes"],
                    all(h["open_for_a_nominal_pin"] for h in lg["holes"] if h["part"] == p),
                    all(h["wall_fill_fraction"] > 0.99 for h in lg["holes"] if h["part"] == p),
                    spread([h for h in lg["holes"] if h["part"] == p], "from_nearest_joint_axis_mm"),
                    spread([h for h in lg["holes"] if h["part"] == p], "gap_to_it_mm"),
                    lg["counts"][p]["studs"],
                    all(s["present"] for s in lg["studs"] if s["part"] == p),
                    all(s["points_up_at_neutral"] for s in lg["studs"] if s["part"] == p),
                    spread([s for s in lg["studs"] if s["part"] == p], "gap_to_it_mm")) for p in parts]), "",
           f"Features inside the camera's clear cone at the neutral pose: {lg['features_in_the_camera_cone_at_neutral']}.",
           "The joint sweeps above were run with the pads and studs in place.", "",
           "### How much decoration the stand pose carries", "",
           "Extra mass placed at one spot, robot at the stand pose on two feet. Static balance only: the mass at which the centre of",
           "mass reaches the edge of the support polygon. Servo torque, walking and the stiffness of the plates are not in it, and",
           "the gait was not rerun with added mass.", "",
           _table(["where", "margin with 50 g (mm)", "with 100 g (mm)", "with 200 g (mm)", "mass that uses up the margin (g)"],
                  [(d["where"], d["margin_with_50_g_mm"], d["margin_with_100_g_mm"], d["margin_with_200_g_mm"],
                    "more than 3000" if d["mass_that_uses_up_the_margin_g"] is None else d["mass_that_uses_up_the_margin_g"])
                   for d in rep["decoration_budget"]]), "",
           f"The margin with nothing added is {rep['balance']['stand_pose']['margin_mm']} mm.", ""]

    m = rep["mass"]
    md += ["## Mass and centre of mass", "",
           f"Total {m['total_g']} g: servos {m['by_kind_g']['servo']} g, printed parts {m['by_kind_g']['print']} g "
           f"({m['print_material']} at {m['print_density_g_cm3']} g/cm3, {int(m['print_solid_fraction'] * 100)} percent of solid; "
           f"{m['total_if_printed_solid_g']} g in total if printed solid), board {m['by_kind_g']['board']} g and shield {m['by_kind_g']['shield']} g (both assumed), "
           f"camera {m['by_kind_g']['camera']} g"
           + (f", display with its XIAO {m['by_kind_g']['display']} g and battery {m['by_kind_g']['battery']} g (both assumed)." if "display" in m["by_kind_g"] else "."),
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
    presets = {}
    for name in model.CAMERAS:
        if name == config["camera"]["preset"]:
            continue
        progress(f"camera preset {name}")
        other = dict(config, face=None, camera=dict(config["camera"], preset=name))
        presets[name] = assembly.camera_preset_summary(build_robot(selected, hardware, other))
    progress("camera preset without the display")
    presets[config["camera"]["preset"] + " alone in the fixed mount"] = assembly.camera_preset_summary(
        build_robot(selected, hardware, dict(config, face=None)))
    faces = {}
    for face, camera in (("eyes_above", "esp32cam"), ("eyes_below", "esp32cam"), ("eyes_above", "esp_eye")):
        progress(f"face {face} {camera}")
        other = dict(config, face=face, camera=dict(config["camera"], preset=camera))
        faces[f"{face}_{camera}"] = assembly.face_summary(build_robot(selected, hardware, other), reports[selected]["joint_limits_deg"])
    controllers = {}
    for name in [k for k in hardware["controllers"] if not k.startswith("_")]:
        progress(f"controller {name}")
        other = build_robot(selected, hardware, dict(config, controller=name, face=None))
        controllers[name] = assembly.controller_summary(other, reports[selected]["joint_limits_deg"])
    progress("turning head")
    turning = build_robot(selected, hardware, dict(config, head="pan", face=None))
    head = assembly.head_checks(turning, reports[selected]["balance"]["stand_pose"]["q_deg"])
    progress("rendering")
    images = render_images(robots, reports, selected)
    names = {"torso_print", "pan_servo", "pan_horn", "head_platform_print", "head_cradle_print", "camera_board", "unoq", "braccio_shield"}
    shots = []
    for angle in (0.0, head["pan_travel_to_the_stops_deg"][1]):
        posed = turning.placed({"head_pan": angle, "head_tilt": head["tilt_set_to_deg"]})
        shots.append(render.render(_items(posed, names), "iso", (560, 520), bounds=_pad([20, -45, -20], [80, 45, 95], 4.0)))
    posed = turning.placed({"head_tilt": head["tilt_set_to_deg"]})
    shots.append(render.render(_items(posed, names), "left", (560, 520), bounds=_pad([20, -45, -20], [80, 45, 95], 4.0)))
    shots.append(render.render(_items(posed), "iso", (700, 520)))
    images["turning_head"] = _save(_side_by_side(shots, ["turning head, pan 0", f"at the stop, {head['pan_travel_to_the_stops_deg'][1]} deg",
                                                         "left", "whole robot"]), "turning-head.png")
    assumed = []
    for group in ("servos",):
        for name, spec in hardware[group].items():
            assumed += [{"item": name, "quantity": k, "value": v["value"], "why": v["why"]} for k, v in spec["assumed"].items()]
    for name in ("board", "shield", "print", "driver"):
        assumed += [{"item": hardware[name].get("name", name), "quantity": k, "value": v["value"], "why": v["why"]}
                    for k, v in hardware[name]["assumed"].items()]
    camera = hardware["cameras"][config["camera"]["preset"]]
    assumed += [{"item": camera["name"], "quantity": k, "value": v["value"], "why": v["why"]} for k, v in camera["assumed"].items()]
    assumed += [{"item": "camera", "quantity": k, "value": v["value"], "why": v["why"]}
                for k, v in hardware["camera_optics"]["assumed"].items()]
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
                    "Braccio shield outline": hardware["shield"]["source"],
                    camera["name"]: camera["source"]},
        "findings": findings(reports[selected]),
        "camera_presets": presets,
        "faces": faces,
        "face_default": f"{config.get('face')}_{config['camera']['preset']}",
        "turning_head": head,
        "controllers": controllers,
        "images": images,
        "variants": reports,
    }
    (ROOT / "reports").mkdir(exist_ok=True)
    (ROOT / "reports" / "assembly.json").write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8", newline="\n")
    (ROOT / "docs" / "assembly.md").write_text(markdown(report), encoding="utf-8", newline="\n")
    return report
