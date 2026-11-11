# SPDX-License-Identifier: MIT
"""What every page shares: the head tags, the masthead and the footer come
from microduck/sitechrome.py; the palette meets WCAG AA where text sits on
it; every page has a heading, a purpose, alt text and a way on; and in a
browser no page scrolls sideways or throws, at 1280 and at 360 px."""
import json
import re

import pytest
from PIL import Image

from conftest import ROOT
from microduck import sitechrome
from test_control_page import browser, site_url  # noqa: F401  (fixtures)

SITE = ROOT / "site"
PAGES = sorted(path.name for path in SITE.glob("*.html"))
CSS = (SITE / "style.css").read_text(encoding="utf-8")


def colour(name: str) -> str:
    return re.search(rf"--{name}: (#[0-9a-f]{{6}});", CSS).group(1)


def luminance(value: str) -> float:
    parts = [int(value[i:i + 2], 16) / 255.0 for i in (1, 3, 5)]
    parts = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in parts]
    return 0.2126 * parts[0] + 0.7152 * parts[1] + 0.0722 * parts[2]


def contrast(a: str, b: str) -> float:
    light, dark = sorted((luminance(a), luminance(b)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def test_the_pages_are_what_the_shared_module_writes():
    assert {"index.html", "biped.html", "wheeled.html", "walkers.html", "flash.html", "control.html", "admin.html", "credits.html",
            "about.html", "404.html"} == set(PAGES)
    mastheads = set()
    footers = set()
    for name in PAGES:
        text = (SITE / name).read_text(encoding="utf-8")
        assert sitechrome.apply(text, name) == text, f"{name}: run python -m microduck.sitechrome"
        mastheads.add(re.search(r"<!-- shared:masthead -->(.*?)<!-- /shared:masthead -->", text, re.S).group(1)
                      .replace(' aria-current="page"', ""))
        footers.add(re.search(r"<!-- shared:footer -->(.*?)<!-- /shared:footer -->", text, re.S).group(1))
        assert text.count("<header") == 1 and text.index("<!-- /shared:masthead -->") < text.index('<main id="content">')
    assert len(mastheads) == 1 and len(footers) == 1, "one masthead and one footer for the whole site"
    footer = footers.pop()
    for needle in ('data-tour>Take the tour</a>', '<a href="./about.html">About</a>', ">Status and assumptions</a>",
                   '<a href="./credits.html">Picture credits</a>', '<a href="./admin.html">Admin</a>', ">Source</a>",
                   ">Report a problem</a>", "MIT licence", "trademarks of the LEGO Group", "Raspberry Pi is a trademark"):
        assert needle in footer, needle
    compat = json.loads((ROOT / "config" / "compat.json").read_text(encoding="utf-8"))
    assert sitechrome.TRADEMARKS == compat["trademarks"], "the notice the recipes carry"


def test_the_palette_meets_aa_where_text_sits_on_it():
    green, deep, sun, ink, muted = (colour(name) for name in ("green", "green-deep", "sun", "ink", "muted"))
    white, page, soft = "#ffffff", "#f7faf8", colour("green-soft")
    # The masthead band runs from the deep green to the logo's green: white text on either end.
    assert "linear-gradient(100deg, var(--green-deep) 0%, var(--green) 100%)" in CSS
    assert contrast(white, green) >= 4.5 and contrast(white, deep) >= 7.0
    assert contrast(deep, white) >= 7.0, "the current tab: deep green on a white pill"
    # The focus ring and the accent line on the band are not text: 3 to 1.
    assert ".masthead a:focus-visible { outline: 3px solid var(--sun);" in CSS
    assert contrast(sun, green) >= 3.0 and contrast(sun, deep) >= 3.0
    # Text elsewhere: links, notes, tags, the step chips.
    for text, ground in ((green, white), (green, page), (deep, soft), (deep, sun), (muted, white), (muted, page), (ink, white),
                         (colour("warn"), white), (colour("red"), white)):
        assert contrast(text, ground) >= 4.5, (text, ground, round(contrast(text, ground), 2))
    assert "prefers-reduced-motion: reduce" in CSS and ".skip-link:focus { top: 8px; }" in CSS
    assert "@media print" in CSS and ".masthead { background: #fff;" in CSS


def test_every_page_has_a_heading_a_purpose_alt_text_and_a_way_on():
    for name in PAGES:
        text = (SITE / name).read_text(encoding="utf-8")
        head = text.split("</head>")[0]
        title = re.search(r"<title>(.+?)</title>", head).group(1)
        description = re.search(r'<meta name="description" content="([^"]+)">', head).group(1)
        assert "Botbuilder" in title and 40 <= len(description) <= 200, name
        assert f'<meta property="og:title" content="{title}">' in head and '<meta property="og:description"' in head, name
        assert '<html lang="en">' in text and 'name="viewport"' in head
        body = text.split("<body>")[1]
        assert body.lstrip().startswith("<!-- shared:masthead -->\n  <a class=\"skip-link\" href=\"#content\">Skip to content</a>"), name
        assert body.count("<h1") == 1, f"{name}: one main heading"
        levels = [int(level) for level in re.findall(r"<h([1-6])[\s>]", body)]
        assert levels[0] == 1 and all(b - a <= 1 for a, b in zip(levels, levels[1:])), f"{name}: headings in order {levels}"
        for tag in re.findall(r"<img[^>]*>", body):
            assert re.search(r'\balt="', tag), f"{name}: {tag}"
        main = body.split('<main id="content">')[1].split("</main>")[0]
        assert re.search(r'<a [^>]*href="\./[^"]*"', main) or name in ("admin.html", "credits.html"), f"{name}: a link to the next step"
    # Pictures drawn by the page scripts carry alt text too.
    for script in ("build.js", "admin.js"):
        code = (SITE / script).read_text(encoding="utf-8")
        assert code.count('createElement("img")') <= code.count(".alt = "), script


def test_about_and_not_found():
    about = (SITE / "about.html").read_text(encoding="utf-8")
    for needle in ('href="https://github.com/eoinjordan"', ">Eoin Jordan</a>", "unoq-braccio-sketchbot", "mindstorms-robot-creator",
                   'href="https://github.com/eoinjordan/botbuilder/issues"', "MIT licence", 'href="./credits.html"',
                   "SIL Open Font License"):
        assert needle in about, needle
    missing = (SITE / "404.html").read_text(encoding="utf-8")
    assert "<h1>That page is not here</h1>" in missing and 'name="robots" content="noindex"' in missing
    for target in ("./", "./biped.html", "./wheeled.html", "./walkers.html", "./flash.html", "./control.html", "./about.html"):
        assert f'<a href="{target}">' in missing.split('<main id="content">')[1], target
    assert not re.search(r'(src|href)="/[^/]', missing + about), "relative, so the base path works"


def test_the_fields_have_plain_hints_and_the_readme_shows_the_site(recipe_data):
    for dim in recipe_data["compat"]["dimensions"]:
        assert 15 <= len(dim["hint"]) <= 100 and dim["hint"].endswith(".") and "!" not in dim["hint"], dim["id"]
    script = (SITE / "build.js").read_text(encoding="utf-8")
    assert 'el("p", dim.hint, "field-hint")' in script and 'select.setAttribute("aria-describedby", hint.id)' in script
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    opening = readme.split("\n## ")[0]
    assert "![Botbuilder](site/assets/logo.svg)" in opening and "https://eoinjordan.github.io/botbuilder/" in opening
    assert "![The landing page: five finished builds as cards](docs/images/site-landing.png)" in opening
    shot = ROOT / "docs" / "images" / "site-landing.png"
    assert shot.stat().st_size < 90_000
    with Image.open(shot) as image:
        assert image.width == 960


def test_every_page_in_a_browser_at_both_widths(browser, site_url):  # noqa: F811
    seen = {}
    for width, height in ((1280, 900), (360, 740)):
        browser.call("Emulation.setDeviceMetricsOverride", width=width, height=height, deviceScaleFactor=1, mobile=width < 500)
        try:
            for name in PAGES:
                browser.open(f"{site_url}/assets/licenses/space-grotesk.txt")
                browser.open(f"{site_url}/{name}", "document.readyState === 'complete' && document.querySelector('.masthead') !== null")
                assert browser.js("document.documentElement.scrollWidth") <= width, f"{name} at {width}"
                band = browser.js("(() => { const m = document.querySelector('.masthead'); const s = getComputedStyle(m);"
                                  " return [m.getBoundingClientRect().height, s.backgroundImage.includes('gradient'),"
                                  " getComputedStyle(m.querySelector('.brand')).color,"
                                  " m.querySelector('.brand-icon').getBoundingClientRect().top === m.querySelector('.brand span').getBoundingClientRect().top"
                                  " || m.querySelector('.brand').getBoundingClientRect().height < 60]; })()")
                assert band[1] and band[2] == "rgb(255, 255, 255)" and band[3], f"{name}: logo and name on one line of the band"
                assert band[0] <= (110 if width == 360 else 100), f"{name}: the band stays compact ({band[0]} px)"
                seen.setdefault(width, set()).add(browser.js(
                    "document.querySelector('.masthead').innerHTML.replace(' aria-current=\"page\"', '').replace(/ hidden=\"\"/g, '')"))
        finally:
            browser.call("Emulation.clearDeviceMetricsOverride")
    assert all(len(found) == 1 for found in seen.values()), "the masthead is the same on every page"
    assert browser.errors == []


def test_the_keyboard_path_through_the_masthead(browser, site_url):  # noqa: F811
    browser.open(f"{site_url}/assets/licenses/space-grotesk.txt")
    browser.open(f"{site_url}/about.html", "document.readyState === 'complete'")
    order = []
    for _ in range(10):
        browser.call("Input.dispatchKeyEvent", type="keyDown", key="Tab", code="Tab", windowsVirtualKeyCode=9)
        browser.call("Input.dispatchKeyEvent", type="keyUp", key="Tab", code="Tab", windowsVirtualKeyCode=9)
        order.append(browser.js("document.activeElement.textContent.trim()"))
        if len(order) == 1:
            assert browser.js("document.activeElement.getBoundingClientRect().top") >= 0, "the skip link shows when focused"
        elif len(order) == 3:
            ring = browser.js("(() => { const s = getComputedStyle(document.activeElement); return [s.outlineStyle, s.outlineColor, s.outlineWidth]; })()")
            assert ring == ["solid", "rgb(255, 200, 87)", "3px"], "a visible focus ring on the green band"
    assert order == ["Skip to content", "Botbuilder", "Build yours", "Biped", "Two-wheeled", "Walkers", "Flash", "Control", "Arms", "Source"]
    # The skip link goes to the content.
    browser.open(f"{site_url}/assets/licenses/space-grotesk.txt")
    browser.open(f"{site_url}/about.html", "document.readyState === 'complete'")
    browser.call("Input.dispatchKeyEvent", type="keyDown", key="Tab", code="Tab", windowsVirtualKeyCode=9)
    browser.call("Input.dispatchKeyEvent", type="keyUp", key="Tab", code="Tab", windowsVirtualKeyCode=9)
    browser.js("document.activeElement.click(); true")
    assert browser.js("location.hash") == "#content"
    assert browser.errors == []
