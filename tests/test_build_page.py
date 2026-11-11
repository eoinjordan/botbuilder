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
    # The source and status links, and the owner's arm project.
    assert set(re.findall(r"https://[a-z0-9.-]+", text)) <= {"https://github.com", "https://eoinjordan.github.io"}


def test_page_shows_the_tag_first_and_the_trademarks():
    html = read("index.html")
    assert "LEGO, Mindstorms and Technic are trademarks of the LEGO Group" in html
    assert "does not sponsor" in html
    assert "Raspberry Pi is a trademark of Raspberry Pi Ltd" in html
    assert "<img" not in html and "<svg" not in html  # no logos
    script = read("build.js")
    assert "recipe.not_built" not in script and "recipe.status_label" in script and "recipe.trademarks" in script
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
    assert html.count('type="button"') == 6 and "<div onclick" not in html
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
    names = sorted(path.name for path in SITE.glob("*.html"))
    assert {"index.html", "biped.html", "wheeled.html", "walkers.html", "flash.html", "control.html", "admin.html"} <= set(names)
    for name in names:
        html = read(name)
        nav = re.search(r'<nav id="site-nav" aria-label="Site">(.*?)</nav>', html, re.S).group(1)
        blocks.append(nav.replace(' aria-current="page"', ""))
        assert html.count('aria-current="page"') == (0 if name == "admin.html" else 1), name   # Admin is a footer link
        assert '<script type="module" src="./nav.js"></script>' in html, name
        targets = re.findall(r'<a href="\./([a-z]*\.html)"([^>]*)>', nav)
        # Tabs by robot type, then the tools, then the arm project as a marked link out, then the source.
        assert [target for target, _ in targets] == ["biped.html", "wheeled.html", "walkers.html", "flash.html", "control.html"], name
        for target, attributes in targets:
            if "data-page" in attributes:
                assert "hidden" in attributes and f'data-page="{target}"' in attributes, target
            else:
                assert (SITE / target).is_file(), target
        out = re.search(r'<a class="out" href="https://eoinjordan\.github\.io/unoq-braccio-sketchbot/"([^>]*)>Arms</a>', nav)
        assert out and 'target="_blank"' in out.group(1) and 'rel="noopener"' in out.group(1), name
        assert 'aria-label="Arms: Sketchbot, opens in a new tab"' in out.group(1), name
        assert nav.index(">Control</a>") < nav.index(">Arms</a>") < nav.index(">Source</a>"), name
        assert 'href="./admin.html">Admin</a>' in html.split("<footer>")[1] and "admin.html" not in nav, name
    assert all(block == blocks[0] for block in blocks), "every page carries the same navigation block"
    pages = json.loads((built / "data" / "pages.json").read_text(encoding="utf-8"))
    assert pages == [name for name in ("wheeled.html", "walkers.html", "flash.html", "control.html") if (SITE / name).is_file()]
    script = read("nav.js")
    assert 'fetch("./data/pages.json")' in script and "link.hidden = false" in script
    assert "flex-wrap: wrap" in read("style.css").split(".masthead nav {")[1].split("}")[0], "the tab row wraps on a phone"


def test_each_type_links_to_its_tab_and_back():
    compat = json.loads((ROOT / "config" / "compat.json").read_text(encoding="utf-8"))
    assert {key: value["page"] for key, value in compat["locomotion_pages"].items()} == {
        "biped": "biped.html", "wheeled": "wheeled.html", "crank": "walkers.html"}
    assert "data.compat.locomotion_pages[recipe.selection.locomotion]" in read("build.js")
    for key, value in compat["locomotion_pages"].items():
        assert (SITE / value["page"]).is_file()
        assert f'href="./?locomotion={key}"' in read(value["page"]), value["page"]
    index = read("index.html")
    assert "Looking for a robot arm?" in " ".join(index.split()) and "unoq-braccio-sketchbot" in index
    # A link naming only some fields keeps them and takes compatible values for the rest.
    assert "const fitted = search(data, sel, named);" in read("build.js")


def test_no_page_refers_to_a_file_that_is_not_there(built):
    """Every relative src and href of every page resolves in the built site,
    apart from the hidden links to pages that do not exist yet."""
    for path in sorted(built.glob("*.html")):
        html = path.read_text(encoding="utf-8")
        for tag, target in re.findall(r'<([a-z]+)[^>]*?(?:src|href)="\./([^"#?]*)[^"]*"', html):
            if not target:
                continue                                        # "./" is the landing page
            if re.search(rf'href="\./{re.escape(target)}"[^>]*data-page="{re.escape(target)}"[^>]*hidden', html) \
                    and not (built / target).is_file():
                continue
            assert (built / target).is_file(), f"{path.name}: {target}"
        for target in re.findall(r'<img[^>]*src="\./(images/[^"]+)"', html):
            assert (ROOT / "docs" / "images" / target.split("/", 1)[1]).is_file(), target


def test_switching_the_controller_takes_the_nearest_possible_selection():
    script = read("build.js")
    # The changed field and the controller stay; the rest moves to the nearest compatible state.
    assert 'const found = search(data, next, ["controller", event.target.name]);' in script
    assert "(not offered here)" not in script and "item.disabled = !state.enabled" in script and "item.title = state.short" in script
    assert "Why some options are greyed out" in script and 'id="greyed"' in read("index.html")
    # A link is never adjusted: the first evaluation after loading takes the address as it is.
    start = script[script.index("async function start()"):]
    assert start.index("show(window.location.search.length > 1)") > start.index("const controls = buildForm")
    # Only a link that names some of the fields is completed; one that names them all is taken as it is.
    assert "if (named.length && named.length < compat.dimensions.filter((dim) => !dim.only_for).length) {" in start


def test_the_biped_page_kept_its_anchors_and_scripts():
    html = read("biped.html")
    for anchor in ("what", "assembly", "viewer", "simulation", "real"):
        assert f'id="{anchor}"' in html, anchor
    for anchor in ("assembly", "viewer", "simulation", "real"):
        assert f'href="#{anchor}"' in html, anchor
    assert '<script type="module" src="./app.js"></script>' in html
    assert "microduck-braccio-unoq-sim" not in html + read("index.html")
    assert "https://github.com/eoinjordan/botbuilder/blob/main/docs/assembly.md" in html
