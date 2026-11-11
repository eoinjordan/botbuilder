# SPDX-License-Identifier: MIT
"""The Build yours page: static, relative paths, no external script or
tracker, carries the status and trademark lines, holds no combination of its
own, and is fed by the site build from the same JSON as the Python function."""
import json
import re
import subprocess
import sys

import pytest

from conftest import ROOT
from microduck import recipe

SITE = ROOT / "site"
PAGE_FILES = ("index.html", "build.js", "nav.js", "recipe.css")


def read(name):
    return (SITE / name).read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def built():
    subprocess.run([sys.executable, str(ROOT / "scripts" / "build_site.py")], check=True, capture_output=True)
    return SITE


def test_site_build_writes_the_recipe_data_from_the_same_json(built):
    shipped = json.loads((built / "data" / "recipe.json").read_text(encoding="utf-8"))
    assert shipped == recipe.bundle(ROOT)
    compat = json.loads((ROOT / "config" / "compat.json").read_text(encoding="utf-8"))
    preset = json.loads((ROOT / "config" / "assembly.json").read_text(encoding="utf-8"))["camera"]["preset"]
    assert compat["defaults"]["camera"] == "" and shipped["compat"]["defaults"]["camera"] == preset
    compat["defaults"]["camera"] = preset
    assert shipped["compat"] == compat
    assert shipped["bases"] == json.loads((ROOT / "config" / "bases.json").read_text(encoding="utf-8"))


def test_paths_are_relative_so_any_base_path_works():
    for name in PAGE_FILES:
        text = read(name)
        assert not re.search(r'(src|href)="/[^/]', text), name
        assert not re.search(r'url\("?/[^/]', text), name
        assert not re.search(r'fetch\(["`]/', text), name
    assert 'fetch("./data/recipe.json")' in read("build.js")
    # The repository name appears only in the source link, never in a site path.
    for name in ("index.html", "biped.html"):
        assert not re.search(r'(src|href)="[^"h][^"]*(botbuilder|microduck-braccio)', read(name)), name


def test_no_external_script_style_or_tracker():
    html = read("index.html")
    assert re.findall(r'<script[^>]*src="([^"]+)"', html) == ["./nav.js", "./build.js"]
    assert re.findall(r'<link[^>]*href="([^"]+)"', html) == ["./style.css", "./recipe.css"]
    assert "import " not in read("build.js").replace("import { ", "")
    text = "".join(read(name).lower() for name in PAGE_FILES)
    for needle in ("google-analytics", "googletagmanager", "gtag(", "plausible", "matomo", "facebook", "document.cookie",
                   "fonts.googleapis", "cdn."):
        assert needle not in text, needle
    assert set(re.findall(r"https://[a-z0-9.-]+", text)) <= {"https://github.com"}


def test_page_states_the_status_rule_and_the_trademarks():
    html = read("index.html")
    assert "No robot has been assembled or powered" in html
    assert "LEGO, Mindstorms and Technic are trademarks of the LEGO Group" in html
    assert "does not sponsor" in html
    assert "Raspberry Pi is a trademark of Raspberry Pi Ltd" in html
    assert "<img" not in html and "<svg" not in html  # no logos
    script = read("build.js")
    assert "recipe.not_built" in script and "recipe.status_label" in script and "recipe.trademarks" in script
    # The verdict is rendered before anything else in the recipe.
    assert script.index("recipe.status_label") < script.index("recipe.print.files")


def test_no_combination_is_written_into_the_page():
    compat = json.loads((ROOT / "config" / "compat.json").read_text(encoding="utf-8"))
    text = read("build.js") + read("index.html")
    for dim in compat["dimensions"]:
        for option in dim["options"]:
            assert f'"{option["id"]}"' not in read("build.js"), option["id"]
            if len(option["label"]) > 3:
                assert option["label"] not in text, option["label"]
    for rule in compat["rules"]:
        assert f'"{rule["id"]}"' not in text


def test_state_is_in_the_url_and_storage_is_guarded():
    script = read("build.js")
    assert "URLSearchParams(window.location.search)" in script
    assert "history.replaceState" in script
    stores = [m.start() for m in re.finditer(r"window\.localStorage", script)]
    assert len(stores) == 2
    for at in stores:
        assert "try {" in script[max(0, at - 120):at], "localStorage outside try"
    assert "innerHTML" not in script


def test_keyboard_print_and_phone_width():
    html = read("index.html")
    css = read("recipe.css")
    assert 'name="viewport"' in html
    assert 'aria-live="polite"' in html
    assert html.count('type="button"') == 4 and "<div onclick" not in html
    assert "label.htmlFor" in read("build.js").replace("name.htmlFor", "label.htmlFor")
    assert "@media print" in css and ".no-print" in css
    assert "@media (max-width: 860px)" in css
    assert "overflow-wrap: anywhere" in css and "max-width: 100%" in css


def test_the_configurator_is_the_landing_page():
    html = read("index.html")
    assert "<h1>Build your own bot from the parts you have</h1>" in html
    assert 'id="picker"' in html and 'id="recipe"' in html
    assert not (SITE / "build.html").exists()


def test_navigation_is_the_same_on_every_page_and_has_no_dead_link(built):
    blocks = []
    for name in ("index.html", "biped.html"):
        html = read(name)
        nav = re.search(r'<nav id="site-nav">(.*?)</nav>', html, re.S).group(1)
        blocks.append(nav.replace(' aria-current="page"', ""))
        assert html.count('aria-current="page"') == 1, name
        assert '<script type="module" src="./nav.js"></script>' in html, name
        for target, attributes in re.findall(r'<a href="\./([a-z]*\.html)"([^>]*)>', nav):
            if "data-page" in attributes:
                # A page another branch will add: hidden until the site build lists it.
                assert "hidden" in attributes and f'data-page="{target}"' in attributes, target
            else:
                assert (SITE / target).is_file(), target
    assert blocks[0] == blocks[1]
    pages = json.loads((built / "data" / "pages.json").read_text(encoding="utf-8"))
    assert pages == [name for name in ("walkers.html", "flash.html", "control.html") if (SITE / name).is_file()]
    script = read("nav.js")
    assert 'fetch("./data/pages.json")' in script and "link.hidden = false" in script


def test_the_biped_page_kept_its_anchors_and_scripts():
    html = read("biped.html")
    for anchor in ("what", "assembly", "viewer", "simulation", "real"):
        assert f'id="{anchor}"' in html, anchor
    for anchor in ("assembly", "viewer", "simulation", "real"):
        assert f'href="#{anchor}"' in html, anchor
    assert '<script type="module" src="./app.js"></script>' in html
    assert "microduck-braccio-unoq-sim" not in html + read("index.html")
    assert "https://github.com/eoinjordan/botbuilder/blob/main/docs/assembly.md" in html
