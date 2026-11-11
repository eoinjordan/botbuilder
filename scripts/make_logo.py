# SPDX-License-Identifier: MIT
"""Write the Botbuilder logo: a robot head inside a gear, with a screwdriver
standing on it as the antenna.

The mark is a short list of shapes on a 64 x 64 grid, defined once below.
From that list this script writes

    site/assets/logo-mark.svg        the mark alone, in colour
    site/assets/logo-mark-mono.svg   the mark in currentColor, for any background
    site/assets/logo.svg             the mark and the word Botbuilder as live text
    site/assets/favicon.svg          the mark, for the browser tab
    site/assets/favicon-32.png       the same shapes drawn with Pillow
    site/assets/apple-touch-icon.png 180 px, on the masthead's pale green
    site/assets/logo-mark-96.png     96 px on white, an 8-bit PNG the recipe PDF can hold
    site/assets/social-preview.png   1280 x 640, the mark and the site's line
    site/assets/logo-preview.html    the mark at 16, 32, 64 and 256 px on light and dark

Pillow cannot read SVG, so the PNGs are drawn from the same shape list with
Pillow's own drawing calls at eight times the size and scaled down. The gear
is computed from a tooth count, so the teeth are even.

    python scripts/make_logo.py [--out DIR]
"""
import argparse
import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "site" / "assets"
# The site's colours (site/style.css): the accent and two neutrals.
GREEN = "#087f60"
INK = "#172c2c"
PAPER = "#ffffff"
PALE = "#e1f5eb"          # the masthead icon's background
PAGE = "#f7faf8"
MUTED = "#687b75"
TITLE = "Botbuilder: a robot head in a gear with a screwdriver"
LINE = "Build your own bot from the parts you have"

TEETH = 12
GEAR_CENTRE = (32.0, 37.5)
GEAR_TIP = 25.5
GEAR_ROOT = 20.0
HEAD = (13.5, 24.5, 37.0, 26.0, 8.0)          # x, y, width, height, corner radius
STROKE = 3.0


def gear_points() -> list:
    """Outline of a gear with TEETH even teeth: each tooth takes half its
    pitch at the root and narrows to the tip. A gap, not a tooth, is at the
    top, where the screwdriver stands."""
    pitch = 2.0 * math.pi / TEETH
    points = []
    for tooth in range(TEETH):
        mid = -math.pi / 2.0 + pitch / 2.0 + tooth * pitch
        for radius, offset in ((GEAR_ROOT, -0.27), (GEAR_TIP, -0.16), (GEAR_TIP, 0.16), (GEAR_ROOT, 0.27)):
            angle = mid + offset * pitch
            points.append((round(GEAR_CENTRE[0] + radius * math.cos(angle), 2), round(GEAR_CENTRE[1] + radius * math.sin(angle), 2)))
    return points


def shapes(mono: bool = False) -> list:
    """The mark, back to front. Colours are roles: accent, ink, paper."""
    x, y, w, h, r = HEAD
    eye_y = y + 11.5
    out = [
        {"kind": "polygon", "points": gear_points(), "fill": "accent", "cut_head": mono},
        # Screwdriver: blade into the head, shaft, handle on top.
        {"kind": "rect", "box": (30.5, 12.0, 3.0, 12.0), "radius": 0.0, "fill": "ink"},
        {"kind": "rect", "box": (29.0, 10.5, 6.0, 3.6), "radius": 1.2, "fill": "ink"},
        {"kind": "rect", "box": (26.8, 0.8, 10.4, 10.6), "radius": 3.4, "fill": "ink"},
        {"kind": "rect", "box": (x, y, w, h), "radius": r, "fill": None if mono else "paper", "stroke": "ink"},
        # Two round eyes, as the biped's round display.
        {"kind": "circle", "centre": (24.5, eye_y), "radius": 5.0, "fill": "ink"},
        {"kind": "circle", "centre": (39.5, eye_y), "radius": 5.0, "fill": "ink"},
        {"kind": "line", "from": (27.0, y + 20.0), "to": (37.0, y + 20.0), "stroke": "ink", "width": 2.4},
    ]
    if not mono:
        out.insert(4, {"kind": "circle", "centre": (26.2, eye_y - 1.7), "radius": 1.5, "fill": "paper", "over": True})
        out.insert(5, {"kind": "circle", "centre": (41.2, eye_y - 1.7), "radius": 1.5, "fill": "paper", "over": True})
        # Grip grooves on the handle.
        out.append({"kind": "line", "from": (30.3, 3.6), "to": (30.3, 8.2), "stroke": "paper", "width": 1.1})
        out.append({"kind": "line", "from": (33.7, 3.6), "to": (33.7, 8.2), "stroke": "paper", "width": 1.1})
        # Ear bolts on the gear, either side of the head.
        out.append({"kind": "circle", "centre": (9.6, 37.5), "radius": 2.2, "fill": "ink"})
        out.append({"kind": "circle", "centre": (54.4, 37.5), "radius": 2.2, "fill": "ink"})
        # The highlights are drawn after the eyes.
        over = [shape for shape in out if shape.get("over")]
        out = [shape for shape in out if not shape.get("over")] + over
    return out


def _n(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")


def svg_shapes(colours: dict, mono: bool, indent: str = "  ") -> list:
    lines = []
    for shape in shapes(mono):
        fill = colours[shape["fill"]] if shape.get("fill") else "none"
        if shape["kind"] == "polygon":
            path = "M" + " L".join(f"{_n(px)} {_n(py)}" for px, py in shape["points"]) + " Z"
            extra = ' mask="url(#head-gap)"' if shape.get("cut_head") else ""
            lines.append(f'{indent}<path d="{path}" fill="{fill}" stroke="{fill}" stroke-width="1" stroke-linejoin="round"{extra}/>')
        elif shape["kind"] == "rect":
            bx, by, bw, bh = shape["box"]
            stroke = (f' stroke="{colours[shape["stroke"]]}" stroke-width="{_n(STROKE)}" stroke-linejoin="round"'
                      if shape.get("stroke") else "")
            lines.append(f'{indent}<rect x="{_n(bx)}" y="{_n(by)}" width="{_n(bw)}" height="{_n(bh)}" rx="{_n(shape["radius"])}" '
                         f'fill="{fill}"{stroke}/>')
        elif shape["kind"] == "circle":
            cx, cy = shape["centre"]
            lines.append(f'{indent}<circle cx="{_n(cx)}" cy="{_n(cy)}" r="{_n(shape["radius"])}" fill="{fill}"/>')
        else:
            (x0, y0), (x1, y1) = shape["from"], shape["to"]
            lines.append(f'{indent}<path d="M{_n(x0)} {_n(y0)} L{_n(x1)} {_n(y1)}" fill="none" stroke="{colours[shape["stroke"]]}" '
                         f'stroke-width="{_n(shape["width"])}" stroke-linecap="round"/>')
    return lines


def mark_svg(mono: bool = False, title: str = TITLE) -> str:
    colours = ({"accent": "currentColor", "ink": "currentColor", "paper": "none"} if mono
               else {"accent": GREEN, "ink": INK, "paper": PAPER})
    lines = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" role="img" aria-labelledby="logo-title">',
             f'  <title id="logo-title">{title}</title>']
    if mono:
        x, y, w, h, r = HEAD
        gap = STROKE / 2.0 + 2.0
        lines += ['  <mask id="head-gap" maskUnits="userSpaceOnUse" x="0" y="0" width="64" height="64">',
                  '    <rect width="64" height="64" fill="#fff"/>',
                  f'    <rect x="{_n(x - gap)}" y="{_n(y - gap)}" width="{_n(w + 2 * gap)}" height="{_n(h + 2 * gap)}" '
                  f'rx="{_n(r + gap)}" fill="#000"/>',
                  '    <rect x="28" y="0" width="8" height="26" fill="#000"/>',
                  '  </mask>']
    lines += svg_shapes(colours, mono)
    lines.append("</svg>")
    return "\n".join(lines) + "\n"


def wordmark_svg() -> str:
    colours = {"accent": GREEN, "ink": INK, "paper": PAPER}
    lines = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 250 64" role="img" aria-labelledby="logo-title">',
             f'  <title id="logo-title">{TITLE}</title>']
    lines += svg_shapes(colours, False)
    lines += [f'  <text x="76" y="43" font-family="\'Space Grotesk\', system-ui, -apple-system, \'Segoe UI\', sans-serif" '
              f'font-size="30" font-weight="600" fill="{INK}">Bot<tspan font-weight="400" fill="{MUTED}">builder</tspan></text>',
              "</svg>"]
    return "\n".join(lines) + "\n"


def draw_mark(size: int, background=None) -> Image.Image:
    """The colour mark drawn with Pillow from the same shapes."""
    scale = 8
    side = size * scale
    unit = side / 64.0
    image = Image.new("RGBA", (side, side), background or (0, 0, 0, 0))
    pen = ImageDraw.Draw(image)
    colours = {"accent": GREEN, "ink": INK, "paper": PAPER}

    def box(bx, by, bw, bh):
        return [bx * unit, by * unit, (bx + bw) * unit, (by + bh) * unit]

    for shape in shapes(False):
        fill = colours[shape["fill"]] if shape.get("fill") else None
        if shape["kind"] == "polygon":
            points = [(px * unit, py * unit) for px, py in shape["points"]]
            pen.polygon(points, fill=fill)
            pen.line(points + points[:1], fill=fill, width=round(unit), joint="curve")
        elif shape["kind"] == "rect":
            bx, by, bw, bh = shape["box"]
            if shape.get("stroke"):
                half = STROKE / 2.0
                pen.rounded_rectangle(box(bx - half, by - half, bw + 2 * half, bh + 2 * half), radius=(shape["radius"] + half) * unit,
                                      fill=colours[shape["stroke"]])
                pen.rounded_rectangle(box(bx + half, by + half, bw - 2 * half, bh - 2 * half), radius=(shape["radius"] - half) * unit,
                                      fill=fill)
            else:
                pen.rounded_rectangle(box(bx, by, bw, bh), radius=shape["radius"] * unit, fill=fill)
        elif shape["kind"] == "circle":
            (cx, cy), radius = shape["centre"], shape["radius"]
            pen.ellipse(box(cx - radius, cy - radius, 2 * radius, 2 * radius), fill=fill)
        else:
            (x0, y0), (x1, y1), half = shape["from"], shape["to"], shape["width"] / 2.0
            pen.rounded_rectangle(box(x0 - half, y0 - half, x1 - x0 + 2 * half, y1 - y0 + 2 * half), radius=half * unit,
                                  fill=colours[shape["stroke"]])
    return image.resize((size, size), Image.LANCZOS)


def _font(weight: int, size: int):
    name = {400: "space-grotesk-latin-400-normal-LF3ZIHND.woff2", 600: "space-grotesk-latin-600-normal-27GH5ZT3.woff2"}[weight]
    try:
        return ImageFont.truetype(str(ASSETS / name), size)
    except OSError:                      # a FreeType without WOFF2: any sans-serif
        for fallback in ("DejaVuSans-Bold.ttf" if weight > 400 else "DejaVuSans.ttf", "arial.ttf"):
            try:
                return ImageFont.truetype(fallback, size)
            except OSError:
                continue
        return ImageFont.load_default()


def social_preview() -> Image.Image:
    card = Image.new("RGB", (1280, 640), PAGE)
    pen = ImageDraw.Draw(card)
    pen.rounded_rectangle([60, 60, 1220, 580], radius=28, fill=PAPER, outline="#d6e3dc", width=3)
    mark = draw_mark(340)
    card.paste(mark, (120, 150), mark)
    bold, light, small = _font(600, 112), _font(400, 112), _font(400, 34)
    pen.text((500, 205), "Bot", font=bold, fill=INK)
    pen.text((500 + pen.textlength("Bot", font=bold), 205), "builder", font=light, fill=MUTED)
    pen.text((504, 355), LINE, font=small, fill=INK)
    pen.rectangle([504, 420, 624, 428], fill=GREEN)
    return card.quantize(colors=64, dither=0)


def preview_html() -> str:
    """A standalone page to look at the mark: not linked from the site."""
    inner = [line for line in mark_svg(mono=True).splitlines()[1:-1] if "<title" not in line]
    sections = []
    for theme, background, colour in (("light", PAPER, INK), ("dark", INK, PAPER)):
        lines = [f'  <section style="background:{background};color:{colour}">',
                 f'    <h2>{"Colour, on light" if theme == "light" else "One colour (currentColor), on dark"}</h2>']
        for size in (16, 32, 64, 256):
            if theme == "light":
                lines.append(f'    <figure><img src="./logo-mark.svg" alt="The Botbuilder mark at {size} px" width="{size}" '
                             f'height="{size}"><figcaption>{size} px</figcaption></figure>')
                continue
            lines.append(f'    <figure><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="{size}" height="{size}" '
                         f'role="img" aria-label="The one-colour mark at {size} px">')
            lines += ["    " + line.replace("head-gap", f"head-gap-{size}") for line in inner]
            lines.append(f"    </svg><figcaption>{size} px</figcaption></figure>")
        lines.append("  </section>")
        sections += lines
    page = [
        "<!doctype html>",
        "<!-- SPDX-License-Identifier: MIT -->",
        "<!-- Written by scripts/make_logo.py. A page to look at the logo; nothing links to it. -->",
        '<html lang="en">',
        "<head>",
        '  <meta charset="utf-8">',
        '  <meta name="viewport" content="width=device-width,initial-scale=1">',
        '  <meta name="robots" content="noindex">',
        '  <link rel="icon" href="./favicon.svg" type="image/svg+xml">',
        "  <title>Botbuilder logo preview</title>",
        "  <style>",
        f'    body {{ margin: 0; font-family: "Space Grotesk", system-ui, sans-serif; color: {INK}; background: {PAGE}; }}',
        "    main { max-width: 900px; margin: auto; padding: 24px 16px; }",
        "    section { display: flex; flex-wrap: wrap; align-items: flex-end; gap: 24px; padding: 20px; margin: 0 0 18px; "
        "border: 1px solid #d6e3dc; border-radius: 10px; }",
        "    h1 { font-size: 24px; }",
        "    h2 { flex: 1 0 100%; margin: 0; font-size: 15px; }",
        "    figure { margin: 0; text-align: center; font-size: 12px; }",
        "    figcaption { margin-top: 6px; opacity: 0.8; }",
        "    img, svg { display: block; margin: auto; max-width: 100%; height: auto; }",
        f"    .word {{ background: {PAPER}; }}",
        "  </style>",
        "</head>",
        "<body>",
        "<main>",
        "  <h1>Botbuilder logo</h1>",
    ] + sections + [
        '  <section class="word">',
        "    <h2>With the word, and the PNG files</h2>",
        '    <figure><img src="./logo.svg" alt="The mark with the word Botbuilder" width="250" height="64"><figcaption>logo.svg, live text</figcaption></figure>',
        '    <figure><img src="./favicon-32.png" alt="The 32 px PNG" width="32" height="32"><figcaption>favicon-32.png</figcaption></figure>',
        '    <figure><img src="./apple-touch-icon.png" alt="The 180 px PNG" width="90" height="90"><figcaption>apple-touch-icon.png at half size</figcaption></figure>',
        '    <figure><img src="./social-preview.png" alt="The social preview picture" width="320" height="160"><figcaption>social-preview.png at quarter size</figcaption></figure>',
        "  </section>",
        "</main>",
        "</body>",
        "</html>",
    ]
    return chr(10).join(page) + chr(10)


def files() -> dict:
    """Every text file this script writes, by name."""
    return {"logo-mark.svg": mark_svg(), "logo-mark-mono.svg": mark_svg(mono=True), "logo.svg": wordmark_svg(),
            "favicon.svg": mark_svg(title="Botbuilder"), "logo-preview.html": preview_html()}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=ASSETS)
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    for name, text in files().items():
        (args.out / name).write_text(text, encoding="utf-8", newline="\n")
    draw_mark(32).save(args.out / "favicon-32.png", optimize=True)
    touch = Image.new("RGBA", (180, 180), PALE)
    mark = draw_mark(148)
    touch.paste(mark, (16, 16), mark)
    touch.convert("RGB").save(args.out / "apple-touch-icon.png", optimize=True)
    draw_mark(96, PAPER).convert("RGB").quantize(colors=32, dither=0).save(args.out / "logo-mark-96.png", optimize=True)
    social_preview().save(args.out / "social-preview.png", optimize=True)
    for path in sorted(args.out.glob("*")):
        if path.suffix in (".svg", ".png") and path.name.startswith(("logo", "favicon", "apple", "social")):
            print(f"{path.name}: {path.stat().st_size} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
