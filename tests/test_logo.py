# SPDX-License-Identifier: MIT
"""The logo: written by scripts/make_logo.py from one list of shapes, as
small valid SVG files and PNGs drawn from the same shapes, in the site's own
colours, and used on every page."""
import importlib.util
import math
import re
import xml.etree.ElementTree as ET

import pytest
from PIL import Image

from conftest import ROOT

ASSETS = ROOT / "site" / "assets"
SVG = "{http://www.w3.org/2000/svg}"
PAGES = sorted(path.name for path in (ROOT / "site").glob("*.html"))


@pytest.fixture(scope="module")
def logo():
    spec = importlib.util.spec_from_file_location("make_logo", ROOT / "scripts" / "make_logo.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def rgb(colour: str) -> tuple:
    return tuple(int(colour[i:i + 2], 16) for i in (1, 3, 5))


def near(pixel, colour: str, slack: int = 24) -> bool:
    return all(abs(a - b) <= slack for a, b in zip(pixel[:3], rgb(colour)))


def test_the_committed_files_are_what_the_script_writes(logo):
    for name, text in logo.files().items():
        assert (ASSETS / name).read_text(encoding="utf-8") == text, f"{name}: run python scripts/make_logo.py"


def test_the_svgs_are_small_valid_and_self_contained(logo):
    for name in ("logo-mark.svg", "logo-mark-mono.svg", "logo-mark-light.svg", "logo.svg", "favicon.svg"):
        text = (ASSETS / name).read_text(encoding="utf-8")
        assert len(text) < 4000 and text.isascii(), name
        root = ET.fromstring(text)
        assert root.tag == SVG + "svg" and root.get("role") == "img"
        title = root.find(SVG + "title")
        assert title is not None and title.text.startswith("Botbuilder") and root.get("aria-labelledby") == title.get("id")
        low = text.lower()
        for needle in ("<script", "href", "<image", "<foreignobject", "<style", "url(http", "data:"):
            assert needle not in low, f"{name}: {needle}"
        assert low.count("http") == 1, "only the SVG namespace"
        if name != "logo.svg":
            assert root.get("viewBox") == "0 0 64 64", "a square mark"
    word = ET.fromstring((ASSETS / "logo.svg").read_text(encoding="utf-8"))
    text = word.find(SVG + "text")
    assert "".join(text.itertext()) == "Botbuilder", "the word is live text"
    family = text.get("font-family")
    assert family.startswith("'Space Grotesk'") and "system-ui" in family and family.endswith("sans-serif"), "the site's face, then a system one"


def test_the_colours_are_the_sites_own(logo):
    css = (ROOT / "site" / "style.css").read_text(encoding="utf-8")
    assert f"--green: {logo.GREEN};" in css and f"--ink: {logo.INK};" in css and f"--muted: {logo.MUTED};" in css
    used = set(re.findall(r"#[0-9a-f]{6}", (ASSETS / "logo-mark.svg").read_text(encoding="utf-8")))
    assert used == {logo.GREEN, logo.INK, logo.PAPER}, "the accent and two neutrals"
    mono = (ASSETS / "logo-mark-mono.svg").read_text(encoding="utf-8")
    assert "currentColor" in mono and set(re.findall(r'(?:fill|stroke)="([^"]+)"', mono)) == {"currentColor", "none", "#fff", "#000"}
    strokes = set(re.findall(r'stroke-width="([^"]+)"', (ASSETS / "logo-mark.svg").read_text(encoding="utf-8")))
    assert "3" in strokes and len(strokes) <= 4
    assert 'stroke-linejoin="round"' in mono and 'stroke-linecap="round"' in mono


def test_the_gear_has_even_teeth(logo):
    points = logo.gear_points()
    assert len(points) == 4 * logo.TEETH and logo.TEETH >= 10
    cx, cy = logo.GEAR_CENTRE
    polar = [(math.hypot(x - cx, y - cy), math.degrees(math.atan2(y - cy, x - cx)) % 360.0) for x, y in points]
    for tooth in range(logo.TEETH):
        root_a, tip_a, tip_b, root_b = polar[4 * tooth:4 * tooth + 4]
        assert abs(root_a[0] - logo.GEAR_ROOT) < 0.02 and abs(root_b[0] - logo.GEAR_ROOT) < 0.02
        assert abs(tip_a[0] - logo.GEAR_TIP) < 0.02 and abs(tip_b[0] - logo.GEAR_TIP) < 0.02
        middle = (tip_a[1] + ((tip_b[1] - tip_a[1]) % 360.0) / 2.0) % 360.0
        expected = (-90.0 + (tooth + 0.5) * 360.0 / logo.TEETH) % 360.0
        assert abs((middle - expected + 180.0) % 360.0 - 180.0) < 0.2, "teeth are evenly spaced"
        assert abs(((tip_b[1] - tip_a[1]) % 360.0) - 0.32 * 360.0 / logo.TEETH) < 0.2, "and all the same width"
    # A gap at the top, where the screwdriver stands.
    assert not any(abs(angle - 270.0) < 3.0 and radius > logo.GEAR_ROOT + 1 for radius, angle in polar)


def test_the_pngs_are_drawn_from_the_same_shapes(logo):
    sizes = {"favicon-32.png": (32, 32), "apple-touch-icon.png": (180, 180), "logo-mark-96.png": (96, 96),
             "social-preview.png": (1280, 640)}
    for name, size in sizes.items():
        with Image.open(ASSETS / name) as image:
            assert image.size == size, name
    assert (ASSETS / "social-preview.png").stat().st_size < 300_000
    assert (ASSETS / "favicon-32.png").stat().st_size < 4_000 and (ASSETS / "apple-touch-icon.png").stat().st_size < 16_000
    with Image.open(ASSETS / "logo-mark-96.png") as image:
        assert image.mode == "P", "an 8-bit PNG the recipe PDF can hold"
    # The same picture as the SVG: sample the shapes where the SVG puts them.
    with Image.open(ASSETS / "favicon-32.png") as image:
        assert image.mode == "RGBA" and image.getpixel((0, 31))[3] == 0, "transparent outside the mark"
    big = logo.draw_mark(256).convert("RGBA")
    unit = 256 / 64.0

    def at(x, y):
        return big.getpixel((round(x * unit), round(y * unit)))
    x, y, w, h, _ = logo.HEAD
    assert near(at(24.5, y + 13.5), logo.INK), "an eye"
    assert near(at(x + w / 2.0, y + 6.0), logo.PAPER), "the head"
    assert near(at(x + w / 2.0, y - logo.STROKE / 2.0 + 0.2), logo.INK), "its outline"
    cx, cy = logo.GEAR_CENTRE
    angle = math.radians(-90.0 + 2.5 * 360.0 / logo.TEETH)
    radius = (logo.GEAR_TIP + logo.GEAR_ROOT) / 2.0
    assert near(at(cx + radius * math.cos(angle), cy + radius * math.sin(angle)), logo.GREEN), "a tooth"
    assert near(at(32.0, 6.0), logo.INK) and near(at(32.0, 18.0), logo.INK), "the screwdriver's handle and shaft"
    assert at(2.0, 2.0)[3] == 0
    with Image.open(ASSETS / "social-preview.png") as image:
        colours = image.convert("RGB")
        assert near(colours.getpixel((10, 10)), logo.PAGE) and near(colours.getpixel((640, 100)), logo.PAPER)


def test_every_page_carries_the_mark_the_icons_and_the_preview_picture():
    brand = ('<a class="brand" href="./"><img class="brand-icon" src="./assets/logo-mark-light.svg" alt="" width="44" height="44">'
             "<span>Bot<b>builder</b></span></a>")
    for name in PAGES:
        html = (ROOT / "site" / name).read_text(encoding="utf-8")
        assert brand in html and ">BB<" not in html, name
        head = html.split("</head>")[0]
        assert '<link rel="icon" href="./assets/favicon.svg" type="image/svg+xml">' in head, name
        assert '<link rel="icon" href="./assets/favicon-32.png" sizes="32x32" type="image/png">' in head, name
        assert '<link rel="apple-touch-icon" href="./assets/apple-touch-icon.png">' in head, name
        assert '<meta property="og:image" content="https://eoinjordan.github.io/botbuilder/assets/social-preview.png">' in head, name
        assert '<meta property="og:site_name" content="Botbuilder">' in head and '<meta name="twitter:card" content="summary_large_image">' in head
        assert "logo-preview.html" not in html, "the preview is not linked"
    css = (ROOT / "site" / "style.css").read_text(encoding="utf-8")
    assert ".brand-icon { width: 44px; height: 44px;" in css
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert readme.startswith("![Botbuilder](site/assets/logo.svg)\n")
    preview = (ASSETS / "logo-preview.html").read_text(encoding="utf-8")
    for size in (16, 32, 64, 256):
        assert preview.count(f'width="{size}" height="{size}"') >= 2, "on light and on dark"
    assert "https://" not in preview and "<script" not in preview
    # The recipe PDF and zip carry it too.
    script = (ROOT / "site" / "build.js").read_text(encoding="utf-8")
    export = (ROOT / "site" / "export.js").read_text(encoding="utf-8")
    assert '"./assets/logo-mark-96.png"' in script and "meta.logo" in export and '"botbuilder-logo.svg"' in script
