# SPDX-License-Identifier: MIT
"""Pictures of the bought components, for the configurator and the recipes.

config/component_images.json lists every component with its picture and
where the picture comes from. Three kinds:

- photo:   a photograph under docs/components/, with its author, licence
           and source recorded. scripts/fetch_component_photos.py fetches
           the openly licensed ones from Wikimedia Commons and writes what
           the file's own page says into the data file.
- drawing: drawn here from the dimensions the repository already holds
           (config/hardware.json, config/bases.json, walkers/config/*.json),
           with the software rasteriser: outlines and envelopes, labelled as
           drawings. No product photograph is copied.
- render:  a picture the repository already has: a part thumbnail, a build
           picture, or a two-wheeled model from robot/lego/wheeled.

    python -m microduck.componentpics             draw what is missing or out of date
    python -m microduck.componentpics --all       redraw every drawing
    python -m microduck.componentpics --credits   only rewrite site/credits.html

The pictures are 8-bit palette PNGs of 320 x 240, the form site/export.js
copies into a PDF. The record of what each drawing was made from is in
reports/component_images.json; a test compares it with the files.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import sys
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image, ImageDraw, ImageFont

from . import render
from .recipe import credit_line  # noqa: F401  (one wording for the page and the PDF)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "config" / "component_images.json"
FOLDER = ROOT / "docs" / "components"
RECORD = ROOT / "reports" / "component_images.json"
CREDITS = ROOT / "site" / "credits.html"
SIZE = (320, 240)
LABEL = 30                                    # pixels under the picture for the label of a drawing
VIEW = render.iso_view(38.0, 30.0)
COLOURS = 32
PALETTE = {
    "board": (20, 120, 110), "blue": (40, 90, 160), "red": (150, 40, 60), "black": (40, 42, 48), "grey": (150, 156, 164),
    "light": (214, 218, 222), "steel": (188, 194, 200), "yellow": (236, 196, 60), "white": (240, 240, 236),
    "gold": (200, 170, 80), "print": (236, 205, 120), "glass": (30, 30, 36), "lego": (190, 196, 200), "teal": (70, 170, 170),
}


# --- shapes -------------------------------------------------------------------

def box(lo, hi, colour):
    vertices, faces = render.box_mesh(np.minimum(lo, hi), np.maximum(lo, hi))
    return vertices, faces, PALETTE[colour]


def plate(length, width, thickness, colour, z=0.0):
    return box((-length / 2.0, -width / 2.0, z), (length / 2.0, width / 2.0, z + thickness), colour)


def cylinder(axis, centre, radius, length, colour, sections=48):
    mesh = trimesh.creation.cylinder(radius=radius, height=length, sections=sections)
    if axis == "x":
        mesh.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2.0, [0.0, 1.0, 0.0]))
    elif axis == "y":
        mesh.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2.0, [1.0, 0.0, 0.0]))
    mesh.apply_translation(centre)
    return np.asarray(mesh.vertices), np.asarray(mesh.faces), PALETTE[colour]


def sphere(centre, radius, colour):
    mesh = trimesh.creation.icosphere(subdivisions=3, radius=radius)
    mesh.apply_translation(centre)
    return np.asarray(mesh.vertices), np.asarray(mesh.faces), PALETTE[colour]


def torus(major, minor, colour, around=48, across=16):
    """A ring lying flat: 'major' to the centre of the cord, 'minor' the cord radius."""
    u = np.linspace(0.0, 2.0 * np.pi, around, endpoint=False)
    v = np.linspace(0.0, 2.0 * np.pi, across, endpoint=False)
    uu, vv = np.meshgrid(u, v, indexing="ij")
    vertices = np.stack([(major + minor * np.cos(vv)) * np.cos(uu), (major + minor * np.cos(vv)) * np.sin(uu),
                         minor * np.sin(vv) + minor], axis=-1).reshape(-1, 3)
    faces = []
    for i in range(around):
        for j in range(across):
            a, b = i * across + j, i * across + (j + 1) % across
            c, d = ((i + 1) % around) * across + j, ((i + 1) % around) * across + (j + 1) % across
            faces += [[a, c, b], [b, c, d]]
    return vertices, np.asarray(faces), PALETTE[colour]


class Dimensions:
    """The dimension data the drawings read."""

    def __init__(self, root: Path = ROOT):
        def load(*parts):
            return json.loads(root.joinpath(*parts).read_text(encoding="utf-8"))
        self.hardware = load("config", "hardware.json")
        self.bases = load("config", "bases.json")["bases"]
        self.components = load("walkers", "config", "components.json")
        self.wheeled = load("walkers", "config", "wheeled.json")
        self.files = ("config/hardware.json", "config/bases.json", "walkers/config/components.json", "walkers/config/wheeled.json")


def _value(node):
    return node["value"] if isinstance(node, dict) and "value" in node else node


def _board(length, width, colour, thickness=1.6):
    return [plate(length, width, thickness, colour)]


def _header_row(length, y, pins, z=1.6, height=8.5):
    return [box((-length / 2.0, y - 1.27, z), (length / 2.0, y + 1.27, z + height), "black")]


def _servo(length, width, height, ears, colour="black"):
    """A hobby servo as its case, its mounting ears and its output."""
    items = [box((-length / 2.0, -width / 2.0, 0.0), (length / 2.0, width / 2.0, height), colour)]
    items.append(box((-ears / 2.0, -width / 2.0, height * 0.68), (ears / 2.0, width / 2.0, height * 0.68 + 2.0), colour))
    items.append(cylinder("z", (length / 2.0 - width / 2.0, 0.0, height + 2.5), width * 0.28, 5.0, "white"))
    return items


# --- the drawings: each returns (shapes, size text, where the dimensions are) ---

def draw_unoq(d):
    b = d.hardware["board"]["published"]
    length, width = b["length_mm"], b["width_mm"]
    items = _board(length, width, "board")
    items += _header_row(length * 0.7, width / 2.0 - 2.5, 18) + _header_row(length * 0.7, -width / 2.0 + 2.5, 18)
    items.append(box((-length / 2.0 - 1.0, -4.5, 1.6), (-length / 2.0 + 7.0, 4.5, 4.8), "steel"))      # USB-C, the 5 V 3 A input
    return items, f"{length:g} x {width:g} mm", "config/hardware.json board"


def draw_braccio_shield(d):
    s = d.hardware["shield"]["published"]
    length, width = s["length_mm"], s["width_mm"]
    items = _board(length, width, "blue")
    for i in range(6):                                                  # six servo outputs
        x = -length / 2.0 + 10.0 + i * 8.5
        items.append(box((x, width / 2.0 - 12.0, 1.6), (x + 6.0, width / 2.0 - 4.0, 9.0), "white"))
    items.append(box((length / 2.0 - 16.0, -width / 2.0 + 3.0, 1.6), (length / 2.0 - 2.0, -width / 2.0 + 12.0, 12.0), "black"))  # supply jack
    return items, f"{length:g} x {width:g} mm", "config/hardware.json shield"


def _braccio_servo(d, name):
    p = d.hardware["servos"][name]["published"]
    return (_servo(p["length_mm"], p["width_mm"], p["height_mm"], p["length_mm"] + 13.0),
            f"{p['length_mm']:g} x {p['width_mm']:g} x {p['height_mm']:g} mm case", f"config/hardware.json servos.{name}")


def draw_sr431(d):
    return _braccio_servo(d, "SR431")


def draw_sr311(d):
    return _braccio_servo(d, "SR311")


def draw_pca9685(d):
    length, width = d.hardware["controllers"]["pi"]["published"]["driver_board_mm"]
    items = _board(length, width, "blue")
    for row in range(3):                                                # sixteen channels of three pins
        items.append(box((-length / 2.0 + 5.0, -width / 2.0 + 2.0 + row * 2.6, 1.6), (length / 2.0 - 5.0, -width / 2.0 + 4.2 + row * 2.6, 8.0),
                         ("black", "red", "yellow")[row]))
    items.append(box((-6.0, width / 2.0 - 8.0, 1.6), (6.0, width / 2.0 - 1.0, 9.0), "blue"))            # servo supply terminal
    return items, f"{length:g} x {width:g} mm", "config/hardware.json controllers.pi driver_board_mm"


def draw_buildhat(d):
    length, width, thickness = _value(d.components["build_hat"]["size_mm"])
    items = _board(length, width, "board", thickness)
    for i in range(4):                                                  # four LPF2 motor ports
        x = -length / 2.0 + 6.0 + i * 14.0
        items.append(box((x, -width / 2.0 - 1.0, thickness), (x + 11.0, -width / 2.0 + 9.0, thickness + 6.0), "black"))
    items.append(box((length / 2.0 - 15.0, width / 2.0 - 12.0, thickness), (length / 2.0 - 1.0, width / 2.0 - 2.0, thickness + 10.0), "black"))  # barrel jack
    return items, f"{length:g} x {width:g} mm", "walkers/config/components.json build_hat"


def draw_hub51515(d):
    length, width, height = _value(d.components["hub51515"]["size_mm"])
    items = [box((-length / 2.0, -width / 2.0, 0.0), (length / 2.0, width / 2.0, height), "teal")]
    items.append(plate(length * 0.45, width * 0.45, 0.8, "white", height))                              # the light matrix
    items.append(cylinder("z", (length * 0.36, 0.0, height + 0.5), 5.0, 1.0, "white"))                   # centre button
    for side in (-1.0, 1.0):                                            # three ports a side
        for i in range(3):
            y = -width / 2.0 + 8.0 + i * 15.0
            items.append(box((side * length / 2.0 - 1.0, y, 6.0), (side * length / 2.0 + 1.0, y + 10.0, 14.0), "black"))
    return items, f"{length:g} x {width:g} x {height:g} mm", "walkers/config/components.json hub51515"


def _envelope(d, key, colour):
    env = d.components[key]["envelope"]
    items = [box(env["body"][0], env["body"][1], colour), box(env["hub"][0], env["hub"][1], "light")]
    items.append(cylinder("y", (0.0, env["hub"][1][1] + 1.0, 0.0), 6.0, 2.0, "red"))                    # the output
    size = _value(d.components[key]["size_mm"])
    return items, f"{size[0]:g} x {size[1]:g} x {size[2]:g} mm envelope", f"walkers/config/components.json {key}"


def draw_angular_motor(d):
    return _envelope(d, "angular_motor", "teal")


def draw_m5_360(d):
    a = d.hardware["head_servo"]["assumed"]
    length, width, below = _value(a["body_length_mm"]), _value(a["body_width_mm"]), _value(a["body_below_ears_mm"])
    return (_servo(length, width, below / 0.68, _value(a["ear_span_mm"]), "blue"),
            f"{length:g} x {width:g} mm body, SG90 class", "config/hardware.json head_servo")


def draw_tt_motor(d):
    # The box the two-wheeled models place for a TT gear motor (walkers/wheeled.py, viewer).
    length, width, height = 70.0, 18.8, 22.5
    items = [box((-length / 2.0, -width / 2.0, 0.0), (length / 2.0 - 26.0, width / 2.0, height), "yellow"),
             cylinder("x", (length / 2.0 - 13.0, 0.0, height / 2.0), 10.0, 26.0, "steel"),
             cylinder("y", (-length / 2.0 + 11.25, 0.0, height / 2.0), 2.7, width + 18.0, "white")]
    return items, f"{length:g} x {width:g} x {height:g} mm", "walkers/wheeled.py viewer, the TT motor box"


def draw_pixy2(d):
    width, height = d.hardware["pixy"]["published"]["board_mm"]
    items = _board(height, width, "black")
    items.append(cylinder("z", (height / 2.0 - 12.0, 0.0, 1.6 + 7.0), 7.0, 14.0, "glass"))
    items += [box((-height / 2.0 + 2.0, -8.0, 1.6), (-height / 2.0 + 8.0, 8.0, 7.0), "white")]
    return items, f"{width:g} x {height:g} mm board", "config/hardware.json pixy"


def draw_pixy_pantilt(d):
    length, width, height = _value(d.components["pixy2_pan_tilt"]["size_mm"])
    board_w, board_h = d.hardware["pixy"]["published"]["board_mm"]
    items = [plate(length, width, 3.0, "light")]
    items.append(box((-11.5, -6.25, 3.0), (11.5, 6.25, 25.0), "blue"))                                   # pan servo
    items.append(box((-6.25, -16.0, 27.0), (6.25, 7.0, 39.0), "blue"))                                   # tilt servo
    items.append(box((8.0, -board_w / 2.0, height - board_h), (9.6, board_w / 2.0, height), "black"))    # the Pixy2
    items.append(cylinder("x", (16.0, 0.0, height - 14.0), 7.0, 13.0, "glass"))
    return items, f"{length:g} x {width:g} x {height:g} mm envelope", "walkers/config/components.json pixy2_pan_tilt"


def _camera_board(d, key, extra=()):
    cam = d.hardware["cameras"][key]
    def figure(name):
        for part in ("published", "assumed", "third_party"):
            if name in cam.get(part, {}):
                return _value(cam[part][name])
        raise KeyError(name)
    length, width = figure("length_mm"), figure("width_mm")
    items = _board(length, width, "black")
    items.append(cylinder("z", (length / 2.0 - 9.0, 0.0, 1.6 + 3.5), 4.0, 7.0, "glass"))
    items += list(extra)
    return items, f"{length:g} x {width:g} mm", f"config/hardware.json cameras.{key}"


def draw_esp_eye(d):
    return _camera_board(d, "esp_eye", [box((-20.5, -4.0, -2.6), (-14.0, 4.0, 0.0), "steel")])           # Micro-USB on the back


def draw_esp32_s3_eye(d):
    sub = d.hardware["cameras"]["esp32_s3_eye"]["published"]["sub_board_mm"]
    lcd = [box((-30.0, -sub[0] / 2.0, 6.0), (-30.0 + sub[1], sub[0] / 2.0, 9.0), "glass")]
    return _camera_board(d, "esp32_s3_eye", lcd)


def draw_xiao_sense(d):
    r = d.hardware["round_display"]["published"]
    length, width, stack = r["xiao_sense_stack_mm"]
    items = _board(length, width, "black", 1.2)
    items.append(box((-length / 2.0 - 1.0, -4.5, 1.2), (-length / 2.0 + 6.5, 4.5, 4.4), "steel"))        # USB-C
    items.append(box((-2.0, -width / 2.0 + 1.0, 5.0), (length / 2.0, width / 2.0 - 1.0, 6.0), "black"))  # the Sense board
    items.append(box((0.0, -4.0, 6.0), (8.0, 4.0, stack - 4.0), "glass"))                                 # camera module, about 8 x 8 mm
    return items, f"{length:g} x {width:g} x {stack:g} mm with the camera", "config/hardware.json round_display xiao_sense_stack_mm"


def draw_round_display(d):
    r = d.hardware["round_display"]
    glass = _value(r["assumed"]["glass_diameter_mm"])
    thick = _value(r["third_party"]["thickness_mm"])
    items = [cylinder("z", (0.0, 0.0, thick / 2.0), glass / 2.0, thick, "black", 64),
             cylinder("z", (0.0, 0.0, thick + 0.3), glass / 2.0 - 3.5, 0.6, "glass", 64)]
    for side in (-1.0, 1.0):                                            # the round eyes the firmware shows
        items.append(cylinder("z", (2.0, side * 7.5, thick + 0.8), 4.2, 0.4, "white", 32))
    return items, f"{glass:g} mm across, {thick:g} mm thick", "config/hardware.json round_display"


def draw_m5core(d):
    length, width, height = _value(d.bases["m5_basex_ev3"]["outline_mm"])
    core = height * 0.62
    items = [box((-length / 2.0, -width / 2.0, 0.0), (length / 2.0, width / 2.0, height - core), "grey"),     # BaseX
             box((-length / 2.0, -width / 2.0, height - core), (length / 2.0, width / 2.0, height), "black"),  # Core
             plate(length * 0.74, width * 0.56, 0.6, "glass", height),
             plate(length * 0.70, width * 0.52, 0.3, "teal", height + 0.6)]
    for i in range(3):
        items.append(plate(8.0, 3.5, 0.8, "light", height))
        vertices, faces, colour = items[-1]
        items[-1] = (vertices + np.array([-length * 0.26 + i * length * 0.26, 0.0, 0.0]) + np.array([0.0, -width * 0.39, 0.0]), faces, colour)
    return items, f"{length:g} x {width:g} x {height:g} mm on the BaseX", "config/bases.json m5_basex_ev3 outline_mm"


def _wheel(d, key, tyre, hub):
    w = d.wheeled["wheels"][key]
    radius, width = w["diameter_mm"] / 2.0, w["width_mm"]
    items = [cylinder("y", (0.0, 0.0, radius), radius, width, tyre, 72),
             cylinder("y", (0.0, 0.0, radius), radius * 0.62, width + 1.0, hub, 48),
             cylinder("y", (0.0, 0.0, radius), 3.0, width + 3.0, "black", 16)]
    return items, f"{w['diameter_mm']:g} mm across, {width:g} mm wide", f"walkers/config/wheeled.json wheels.{key}"


def draw_lego_wheel(d):
    return _wheel(d, "lego_56", "black", "lego")


def draw_tt_wheel(d):
    return _wheel(d, "tt_65", "black", "yellow")


def draw_o_ring(d):
    # "58 x 3 (two)": inner diameter and cord of the ring on the 65 mm printed wheel.
    inner, cord = (float(word) for word in d.wheeled["o_rings"]["rings"]["d65"].split(" (")[0].split(" x "))
    return [torus(inner / 2.0 + cord / 2.0, cord / 2.0, "black")], f"{inner:g} x {cord:g} mm", "walkers/config/wheeled.json o_rings"


def draw_ball(d):
    ball = d.wheeled["supports"]["ball"]["ball_mm"]
    return ([sphere((0.0, 0.0, ball / 2.0), ball / 2.0, "lego"), sphere((ball * 1.3, 0.0, 6.35), 6.35, "steel")],
            f"{ball:g} mm LEGO ball, 12.7 mm steel ball", "walkers/config/wheeled.json supports.ball")


def draw_lipo(d):
    a = d.hardware["battery"]["assumed"]
    length, width, thick = _value(a["length_mm"]), _value(a["width_mm"]), _value(a["thickness_mm"])
    items = [plate(length, width, thick, "steel"), box((length / 2.0, -width / 2.0, 0.0), (length / 2.0 + 4.0, width / 2.0, thick), "gold"),
             box((length / 2.0 + 4.0, -2.5, 1.0), (length / 2.0 + 22.0, -0.8, 2.6), "red"),
             box((length / 2.0 + 4.0, 0.8, 1.0), (length / 2.0 + 22.0, 2.5, 2.6), "black")]
    return items, f"about {length:g} x {width:g} x {thick:g} mm: measure your cell", "config/hardware.json battery"


def _module(d):
    return 8.0                                   # the Technic hole pitch the printed parts are drawn to


def draw_technic_pin(d):
    hole = 4.8
    items = [cylinder("x", (0.0, 0.0, hole / 2.0), hole / 2.0, 2.0 * _module(d), "grey"),
             cylinder("x", (0.0, 0.0, hole / 2.0), hole / 2.0 + 0.7, 1.2, "grey")]
    return items, f"{2 * _module(d):g} mm long, for a {hole:g} mm hole", "walkers/config/components.json technic"


def draw_technic_axle(d):
    length = 5 * _module(d)
    items = [box((-length / 2.0, -2.4, 1.5), (length / 2.0, 2.4, 3.3), "black"), box((-length / 2.0, -0.9, 0.0), (length / 2.0, 0.9, 4.8), "black")]
    return items, f"cross axle, {length:g} mm shown; length to suit", "walkers/config/components.json technic"


def draw_technic_bush(d):
    length = _value(d.components["technic"]["bush_length_mm"])
    items = [cylinder("x", (0.0, 0.0, 3.7), 3.7, length, "grey"), cylinder("x", (length / 2.0 + 0.2, 0.0, 3.7), 2.4, 0.5, "black"),
             cylinder("x", (length * 1.6, 0.0, 3.7), 3.7, length / 2.0, "grey")]
    return items, f"bush {length:g} mm, half bush {length / 2:g} mm", "walkers/config/components.json technic bush_length_mm"


def draw_technic_beam(d):
    pitch, holes = _module(d), 7
    length = pitch * holes
    items = [box((-length / 2.0, -3.7, 0.0), (length / 2.0, 3.7, 7.8), "light")]
    for i in range(holes):
        items.append(cylinder("z", (-length / 2.0 + pitch / 2.0 + i * pitch, 0.0, 7.8), 2.4, 0.4, "black", 24))
    return items, f"beam with holes at {pitch:g} mm", "walkers/config/components.json technic"


DRAWINGS = {
    "unoq": draw_unoq, "braccio_shield": draw_braccio_shield, "sr431": draw_sr431, "sr311": draw_sr311, "pca9685": draw_pca9685,
    "buildhat": draw_buildhat, "hub51515": draw_hub51515, "angular_motor": draw_angular_motor, "m5_360": draw_m5_360,
    "tt_motor": draw_tt_motor, "pixy2": draw_pixy2, "pixy_pantilt": draw_pixy_pantilt, "esp_eye": draw_esp_eye,
    "esp32_s3_eye": draw_esp32_s3_eye, "xiao_sense": draw_xiao_sense, "round_display": draw_round_display, "m5core": draw_m5core,
    "lego_wheel": draw_lego_wheel, "tt_wheel": draw_tt_wheel, "o_ring": draw_o_ring, "ball": draw_ball, "lipo": draw_lipo,
    "technic_pin": draw_technic_pin, "technic_axle": draw_technic_axle, "technic_bush": draw_technic_bush,
    "technic_beam": draw_technic_beam,
}


# --- pictures -----------------------------------------------------------------

def _fit(image: Image.Image, room: tuple) -> Image.Image:
    pixels = np.asarray(image.convert("RGB"))
    drawn = np.argwhere((pixels < 250).any(axis=2))
    if len(drawn):
        (top, left), (bottom, right) = drawn.min(axis=0), drawn.max(axis=0) + 1
        image = image.crop((left, top, right, bottom))
    scale = min(room[0] / image.width, room[1] / image.height)
    return image.resize((max(1, round(image.width * scale)), max(1, round(image.height * scale))), Image.LANCZOS)


def _card(picture, lines) -> Image.Image:
    card = Image.new("RGB", SIZE, (255, 255, 255))
    if picture is not None:
        room = (SIZE[0] - 28, SIZE[1] - LABEL - 20)
        picture = _fit(picture, room)
        card.paste(picture, ((SIZE[0] - picture.width) // 2, 10 + (room[1] - picture.height) // 2))
    pen = ImageDraw.Draw(card)
    font = ImageFont.load_default()
    y = SIZE[1] - LABEL if picture is not None else SIZE[1] // 2 - 12
    for text in lines:
        width = pen.textlength(text, font=font)
        pen.text(((SIZE[0] - width) / 2.0, y), text, fill=(60, 72, 70), font=font)
        y += 13
    return card.quantize(colors=COLOURS, dither=0)


def draw(entry: dict, dims: Dimensions, root: Path = ROOT) -> Image.Image:
    """The picture of a drawing or of a blank card."""
    if entry.get("blank"):
        return _card(None, [entry["name"], entry["blank"]])
    items, size, _ = DRAWINGS[entry["id"]](dims)
    image = render.render(items, view=VIEW, size=(SIZE[0] * 2, SIZE[1] * 2), supersample=2, margin=0.03)
    return _card(image, [f"Drawing: {entry['name']}"[:50], size])


def render_wheeled(entry: dict, root: Path = ROOT) -> Image.Image:
    """A two-wheeled model of robot/lego/wheeled/viewer.json, as the build pictures are drawn."""
    from . import buildpics
    views = json.loads((root / "robot" / "lego" / "wheeled" / "viewer.json").read_text(encoding="utf-8"))
    items = buildpics._wheeled_items({"view": views[entry["wheeled_model"]]}, root)
    image = render.render(items, view=buildpics.VIEW, size=(SIZE[0] * 2, SIZE[1] * 2), supersample=2, margin=0.03)
    return _card(image, [entry["name"], "model " + entry["wheeled_model"]])


def inputs_sha(entry: dict, dims: Dimensions, root: Path = ROOT) -> str:
    """Checksum of what a generated picture is made from. Cheap: nothing is drawn."""
    digest = hashlib.sha256()
    digest.update(json.dumps([SIZE, COLOURS, entry["id"], entry["name"], entry.get("blank", "")]).encode("utf-8"))
    if entry["id"] in DRAWINGS and not entry.get("blank"):
        # The shapes themselves, so only a dimension the drawing uses makes it stale.
        items, size, _ = DRAWINGS[entry["id"]](dims)
        digest.update(size.encode("utf-8"))
        for vertices, faces, colour in items:
            digest.update(np.round(np.asarray(vertices, float), 3).tobytes())
            digest.update(np.asarray(faces, np.int64).tobytes())
            digest.update(bytes(colour))
    if entry.get("wheeled_model"):
        views = json.loads((root / "robot" / "lego" / "wheeled" / "viewer.json").read_text(encoding="utf-8"))
        view = views[entry["wheeled_model"]]
        digest.update(json.dumps(view, sort_keys=True).encode("utf-8"))
        for name in sorted({item["file"] for item in view["stl"] + view["wheels"] if "file" in item}):
            digest.update((root / "stl" / name).read_bytes())
    return digest.hexdigest()


def load(root: Path = ROOT) -> dict:
    return json.loads((root / "config" / "component_images.json").read_text(encoding="utf-8"))


def generated(entry: dict) -> bool:
    """Whether this module makes the entry's file (a drawing, a blank card or a wheeled model)."""
    return entry.get("kind") == "drawing" or bool(entry.get("wheeled_model"))


def update(root: Path = ROOT, redraw_all: bool = False, log=print) -> dict:
    content = load(root)
    dims = Dimensions(root)
    old = json.loads(RECORD.read_text(encoding="utf-8")).get("pictures", {}) if RECORD.is_file() else {}
    pictures = {}
    for entry in content["components"]:
        if not generated(entry):
            continue
        path = root / "docs" / "components" / entry["file"]
        digest = inputs_sha(entry, dims, root)
        before = old.get(entry["id"], {})
        if (redraw_all or not path.is_file() or before.get("inputs_sha256") != digest
                or before.get("sha256") != hashlib.sha256(path.read_bytes()).hexdigest()):
            path.parent.mkdir(parents=True, exist_ok=True)
            image = render_wheeled(entry, root) if entry.get("wheeled_model") else draw(entry, dims, root)
            image.save(path, optimize=True)
            log(f"drew docs/components/{entry['file']}")
        about = {"file": f"docs/components/{entry['file']}", "bytes": path.stat().st_size,
                 "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "inputs_sha256": digest}
        if entry["id"] in DRAWINGS and not entry.get("blank"):
            about["dimensions_from"] = DRAWINGS[entry["id"]](dims)[2]
        pictures[entry["id"]] = about
    record = {"generated_by": "python -m microduck.componentpics", "pictures": pictures}
    RECORD.write_text(json.dumps(record, indent=1) + "\n", encoding="utf-8", newline="\n")
    return record


# --- credits page -------------------------------------------------------------

def _text(value: str) -> str:
    """HTML text in plain ASCII: anything else as a numeric entity."""
    return "".join(ch if ord(ch) < 127 else f"&#{ord(ch)};" for ch in html.escape(str(value), quote=True))


def credits_html(root: Path = ROOT) -> str:
    """site/credits.html: the shared masthead and footer of site/index.html
    around a table generated from the data file."""
    content = load(root)
    index = (root / "site" / "index.html").read_text(encoding="utf-8")
    head = index[:index.index("<main>")].replace(' aria-current="page"', "")
    head = head.replace("<title>Botbuilder</title>", "<title>Botbuilder: picture credits</title>")
    start = head.index('<meta name="description" content="') + len('<meta name="description" content="')
    head = head[:start] + "Where every picture of a bought component on this site comes from: author, licence and source." + head[head.index('"', start):]
    foot = index[index.index("  <footer>"):].replace('  <script type="module" src="./build.js"></script>\n', "")
    rows = []
    for entry in content["components"]:
        if entry["kind"] == "render":
            continue
        picture = f'<img src="./components/{_text(entry["file"])}" alt="{_text(entry["name"])}" width="96" height="72" loading="lazy">'
        if entry["kind"] == "photo":
            source = f'<a href="{_text(entry["source_url"])}" rel="noopener noreferrer">{_text(entry.get("title") or entry["source_url"])}</a>'
            licence = f'<a href="{_text(entry["licence_url"])}" rel="noopener noreferrer">{_text(entry["licence"])}</a>' if entry.get("licence_url") else _text(entry["licence"])
            who = _text(entry["author"])
            what = "Photograph" + (f'; {_text(entry["changes"])}' if entry.get("changes") else "")
        else:
            source, licence, who, what = _text(entry["origin"]), "MIT, with the repository", "Botbuilder", "Drawing, not a photograph"
        rows.append(f"          <tr><td>{picture}</td><td>{_text(entry['name'])}</td><td>{what}</td><td>{who}</td><td>{licence}</td><td>{source}</td></tr>")
    body = f"""<main>
    <div class="title-row">
      <div><p class="eyebrow">WHERE THE PICTURES COME FROM</p><h1>Picture credits</h1></div>
    </div>
    <section aria-labelledby="credits-heading">
      <div class="section-heading"><h2 id="credits-heading">Bought components</h2></div>
      <p>The pictures of bought components are openly licensed photographs from Wikimedia Commons, credited below as each
        file's own page states, or drawings made from the dimensions this project holds. No maker's or shop's product
        photograph is used. Photographs are unchanged apart from cropping, resizing and a reduced palette, and each stays
        under its own licence. The pictures of printed parts and of whole robots are rendered by this project.</p>
      <p class="small-note flush">Generated from config/component_images.json by python -m microduck.componentpics.</p>
      <div class="table-wrap wrap-cells">
        <table class="credits">
          <tr><th>Picture</th><th>Component</th><th>Kind</th><th>Author</th><th>Licence</th><th>Source</th></tr>
{chr(10).join(rows)}
        </table>
      </div>
    </section>
  </main>
"""
    return head + body + foot


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--all", action="store_true", help="redraw every drawing")
    parser.add_argument("--credits", action="store_true", help="only rewrite site/credits.html")
    args = parser.parse_args(argv)
    if not args.credits:
        record = update(redraw_all=args.all)
        total = sum(item["bytes"] for item in record["pictures"].values())
        print(f"{len(record['pictures'])} generated pictures, {total / 1e3:.0f} kB in docs/components")
    CREDITS.write_text(credits_html(), encoding="utf-8", newline="\n")
    print("wrote site/credits.html")
    return 0


if __name__ == "__main__":
    sys.exit(main())
