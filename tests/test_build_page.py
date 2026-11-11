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
PAGE_FILES = ("build.html", "build.js", "recipe.css")


def read(name):
    return (SITE / name).read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def built():
    subprocess.run([sys.executable, str(ROOT / "scripts" / "build_site.py")], check=True, capture_output=True)
    return SITE


def test_site_build_writes_the_recipe_data_from_the_same_json(built):
    shipped = json.loads((built / "data" / "recipe.json").read_text(encoding="utf-8"))
    assert shipped == recipe.bundle(ROOT)
    assert shipped["compat"] == json.loads((ROOT / "config" / "compat.json").read_text(encoding="utf-8"))
    assert shipped["bases"] == json.loads((ROOT / "config" / "bases.json").read_text(encoding="utf-8"))


def test_paths_are_relative_so_any_base_path_works():
    for name in PAGE_FILES:
        text = read(name)
        assert not re.search(r'(src|href)="/[^/]', text), name
        assert not re.search(r'url\("?/[^/]', text), name
        assert not re.search(r'fetch\(["`]/', text), name
    assert 'fetch("./data/recipe.json")' in read("build.js")
    # The repository name appears only in the source link, never in a site path.
    assert not re.search(r'(src|href)="[^"h][^"]*(botbuilder|microduck-braccio)', read("build.html"))


def test_no_external_script_style_or_tracker():
    html = read("build.html")
    assert re.findall(r'<script[^>]*src="([^"]+)"', html) == ["./build.js"]
    assert re.findall(r'<link[^>]*href="([^"]+)"', html) == ["./style.css", "./recipe.css"]
    assert "import " not in read("build.js").replace("import { ", "")
    text = "".join(read(name).lower() for name in PAGE_FILES)
    for needle in ("google-analytics", "googletagmanager", "gtag(", "plausible", "matomo", "facebook", "document.cookie",
                   "fonts.googleapis", "cdn."):
        assert needle not in text, needle
    assert set(re.findall(r"https://[a-z0-9.-]+", text)) <= {"https://github.com"}


def test_page_states_the_status_rule_and_the_trademarks():
    html = read("build.html")
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
    text = read("build.js") + read("build.html")
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
    html = read("build.html")
    css = read("recipe.css")
    assert 'name="viewport"' in html
    assert 'aria-live="polite"' in html
    assert html.count('type="button"') == 4 and "<div onclick" not in html
    assert "label.htmlFor" in read("build.js").replace("name.htmlFor", "label.htmlFor")
    assert "@media print" in css and ".no-print" in css
    assert "@media (max-width: 860px)" in css
    assert "overflow-wrap: anywhere" in css and "max-width: 100%" in css


def test_index_links_to_the_page():
    assert 'href="./build.html"' in read("index.html")
