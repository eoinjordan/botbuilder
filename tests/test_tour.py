# SPDX-License-Identifier: MIT
"""The guided tour: its decisions as pure functions under Node, its steps as
data, and the tour itself in a headless Chrome across the pages, by keyboard
and at phone width.

The other page tests run with the tour switched off: the Browser of
test_control_page.py sets localStorage "botbuilder-tour" to "off" on every
page it opens. The browser here is started with tour=True, which leaves
that switch alone."""
import json
import re
import shutil
import subprocess
import sys
import time

import pytest

from conftest import ROOT
from test_control_page import Browser, find_chrome, site_url  # noqa: F401  (site_url is a fixture)
from test_tone import CAVEATS, CLAIMS

SITE = ROOT / "site"
STEPS = json.loads((ROOT / "config" / "tour.json").read_text(encoding="utf-8"))["steps"]
PAGES = sorted(path.name for path in SITE.glob("*.html"))
CARD = "document.querySelector('.tour-card')"
TITLE = "document.querySelector('.tour-card h2').textContent"
DRIVER = """
import { readFileSync, writeFileSync } from "node:fs";
import { plan, advance, anchorFor, stepAddress } from "./tour.mjs";
const cases = JSON.parse(readFileSync("cases.json", "utf8"));
writeFileSync("out.json", JSON.stringify({
  plan: cases.plan.map((env) => plan(env)),
  advance: cases.advance.map(([index, action, count]) => advance(index, action, count)),
  anchor: cases.anchor.map(([step, here, pages, shown]) => anchorFor(step, here, pages, (selector) => shown.includes(selector))),
  address: cases.address.map(([page, index]) => stepAddress(page, index)),
}));
"""


def env(**changes):
    base = {"params": {"tour": None, "tourstep": None}, "session": None, "seen": False, "off": False, "landing": True, "count": 11}
    base.update(changes)
    return base


def test_the_step_logic_under_node(tmp_path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is not installed; site/tour.js was not run")
    step = {"page": "index.html", "anchor": ["#a", "#b"]}
    panel = {"page": "index.html", "anchor": "#picker", "open": "#customise"}
    away = {"page": "flash.html", "anchor": "#flash-form"}
    pages = ["index.html", "biped.html", "flash.html"]
    cases = {
        "plan": [
            env(),                                                        # 0 first visit to the landing page
            env(seen=True),                                               # 1 seen before
            env(seen=None),                                               # 2 storage cannot be read
            env(landing=False),                                           # 3 first visit, another page
            env(seen=True, params={"tour": "1", "tourstep": None}),       # 4 brought back by the address
            env(session=4, seen=True, landing=False),                     # 5 a move between pages
            env(params={"tour": None, "tourstep": "7"}, seen=None, landing=False),  # 6 the same with nothing saved
            env(params={"tour": None, "tourstep": "99"}, seen=True),      # 7 a step that does not exist
            env(off=True),                                                # 8 the switch
            env(off=True, params={"tour": "1", "tourstep": None}),        # 9 the switch wins
            env(params={"tour": "0", "tourstep": None}),                  # 10 switched off in the address
            env(session=4, params={"tour": "1", "tourstep": None}),       # 11 starting again beats a saved step
            env(params={"tour": None, "tourstep": "x"}),                  # 12 not a number
        ],
        "advance": [[0, "next", 11], [9, "next", 11], [10, "next", 11], [0, "back", 11], [5, "back", 11], [3, "skip", 11], [3, "close", 11]],
        "anchor": [
            [step, "index.html", pages, ["#a", "#b"]],                    # the first control found
            [step, "index.html", pages, ["#b"]],                          # the next when the first is missing
            [step, "index.html", pages, []],                              # none: a centred card
            [panel, "index.html", pages, []],                             # hidden in a closed panel: open it, point at it
            [away, "index.html", pages, []],                              # on another page: go there
            [away, "index.html", ["index.html"], ["#flash-form"]],        # a page that is not built: a centred card here
            [away, "flash.html", pages, ["#flash-form"]],
        ],
        "address": [["index.html", 3], ["biped.html", 6]],
    }
    shutil.copyfile(SITE / "tour.js", tmp_path / "tour.mjs")
    (tmp_path / "driver.mjs").write_text(DRIVER, encoding="utf-8")
    (tmp_path / "cases.json").write_text(json.dumps(cases), encoding="utf-8")
    subprocess.run([node, "driver.mjs"], cwd=tmp_path, check=True, capture_output=True, timeout=60)
    got = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
    none, offer = {"action": "none"}, {"action": "offer"}
    assert got["plan"] == [offer, none, offer, none, {"action": "run", "index": 0}, {"action": "run", "index": 4},
                           {"action": "run", "index": 7}, none, none, none, none, {"action": "run", "index": 0}, offer]
    assert got["advance"] == [{"index": 1, "done": False}, {"index": 10, "done": False}, {"index": 10, "done": True},
                              {"index": 0, "done": False}, {"index": 4, "done": False}, {"index": 3, "done": True},
                              {"index": 3, "done": True}]
    assert got["anchor"] == [{"open": None, "target": "#a"}, {"open": None, "target": "#b"}, {"open": None, "target": None},
                             {"open": "#customise", "target": "#picker"}, {"navigate": "flash.html"},
                             {"open": None, "target": None}, {"open": None, "target": "#flash-form"}]
    assert got["address"] == ["./?tourstep=3", "./biped.html?tourstep=6"]


def test_the_steps_are_short_content_about_real_controls():
    assert 9 <= len(STEPS) <= 12
    assert len({step["id"] for step in STEPS}) == len(STEPS)
    assert STEPS[0]["page"] == "index.html", "it starts where a new visitor lands"
    assert {step["page"] for step in STEPS} == {"index.html", "biped.html", "flash.html", "control.html", "admin.html"}
    script = (SITE / "build.js").read_text(encoding="utf-8")
    for step in STEPS:
        assert (SITE / step["page"]).is_file(), step["id"]
        html = (SITE / step["page"]).read_text(encoding="utf-8")
        assert 3 <= len(step["title"]) <= 40 and 40 <= len(step["text"]) <= 220, step["id"]
        text = step["title"] + " " + step["text"]
        assert text.isascii() and "!" not in text, step["id"]
        for phrase in CAVEATS:
            assert phrase not in text.lower(), f"{step['id']}: {phrase}"
        if step["id"] != "admin":                       # the one step that says what the maker's mark is
            assert not CLAIMS.search(text), step["id"]
        anchors = [step["anchor"]] if isinstance(step["anchor"], str) else step["anchor"]
        for selector in anchors + ([step["open"]] if "open" in step else []):
            for name in re.findall(r"#([a-z-]+)", selector):
                assert f'id="{name}"' in html, f"{step['id']}: #{name} is not on {step['page']}"
            for name in re.findall(r"\.([a-z-]+)", selector):
                assert name in html or name in script, f"{step['id']}: .{name}"
    words = " ".join(step["title"] + " " + step["text"] for step in STEPS)
    for feature in ("card", "status tag", "fit pieces", "Download PDF", "Download all", "greyed out", "Pictures", "3D",
                    "Two-wheeled and Walkers", "Robot Creator", "game controller", "simulator", "Enable", "printed and checked",
                    "Sketchbot", "Take the tour"):
        assert feature in words, feature


def test_every_page_loads_the_tour_after_its_own_script_and_links_to_it():
    for name in PAGES:
        html = (SITE / name).read_text(encoding="utf-8")
        scripts = re.findall(r'<script type="module" src="([^"]+)"></script>', html)
        assert scripts[0] == "./nav.js" and scripts[-1] == "./tour.js", name
        assert '<a href="./?tour=1" data-tour>Take the tour</a>' in html.split("<footer>")[1], name
    script = (SITE / "tour.js").read_text(encoding="utf-8")
    assert "import " not in script, "no library"
    assert script.count("fetch(") == 2 and 'fetch("./data/tour.json")' in script and 'fetch("./data/pages.json")' in script
    # Storage is reached only by name inside the guarded read and write.
    assert "window.localStorage" not in script and "window.sessionStorage" not in script
    assert script.count("window[name]") == 3 and script.count("} catch (error) {") >= 3
    assert "prefers-reduced-motion" in script and 'setAttribute("aria-hidden", "true")' in script
    assert 'setAttribute("role", "dialog")' in script and 'setAttribute("aria-labelledby", "tour-title")' in script
    css = (SITE / "style.css").read_text(encoding="utf-8")
    assert ".tour-card.tour-docked" in css and "prefers-reduced-motion: reduce" in css
    # The landing page's own script leaves the tour's parameters alone.
    assert "delete linked.tour;" in (SITE / "build.js").read_text(encoding="utf-8")
    subprocess.run([sys.executable, str(ROOT / "scripts" / "build_site.py")], check=True, capture_output=True)
    assert json.loads((SITE / "data" / "tour.json").read_text(encoding="utf-8"))["steps"] == STEPS


# --- in a browser ---------------------------------------------------------------

@pytest.fixture(scope="module")
def touring(tmp_path_factory):
    chrome = find_chrome()
    if not chrome:
        pytest.skip("no installed Chrome or Chromium")
    pytest.importorskip("websockets", reason="the websockets package is not installed")
    try:
        instance = Browser(chrome, tmp_path_factory.mktemp("chrome-tour"), tour=True)
    except (RuntimeError, OSError) as error:
        pytest.skip(f"Chrome did not start headless here: {error}")
    yield instance
    instance.close()
    time.sleep(0.5)


def new_visitor(browser, site_url):  # noqa: F811
    browser.open(f"{site_url}/assets/licenses/space-grotesk.txt")
    browser.js("window.localStorage.clear(); window.sessionStorage.clear(); true")


def reopen(browser, url, ready="document.readyState === 'complete'"):
    """Load a page again from scratch: by way of a plain file, so that the wait is for the new document."""
    browser.open(url.split("/?")[0].rsplit("/", 1)[0] + "/assets/licenses/space-grotesk.txt")
    browser.open(url, ready)


def key(browser, name, text=None, shift=False):
    code = {"Enter": 13, "Tab": 9, "Escape": 27}[name]
    extra = {"text": text} if text else {}
    browser.call("Input.dispatchKeyEvent", type="keyDown", key=name, code=name, windowsVirtualKeyCode=code,
                 modifiers=8 if shift else 0, **extra)
    browser.call("Input.dispatchKeyEvent", type="keyUp", key=name, code=name, windowsVirtualKeyCode=code, modifiers=8 if shift else 0)


def test_a_new_visitor_is_offered_the_tour_and_can_send_it_away(touring, site_url):  # noqa: F811
    new_visitor(touring, site_url)
    touring.open(f"{site_url}/")
    touring.wait("document.querySelector('.tour-offer') !== null")
    assert touring.js(f"{CARD} === null"), "offered, not opened over the page"
    assert touring.js("document.querySelector('.tour-offer').getAttribute('role')") == "region"
    touring.wait("document.querySelectorAll('#builds [role=radio]').length > 0")
    touring.js("document.querySelector('#builds [role=radio]:last-child').click(); true")
    assert touring.js("location.search").startswith("?build="), "the page works with the offer on it"
    touring.js("[...document.querySelectorAll('.tour-offer button')].find((b) => b.textContent === 'No thanks').click(); true")
    assert touring.js("document.querySelector('.tour-offer') === null")
    reopen(touring, f"{site_url}/", "document.querySelectorAll('#builds [role=radio]').length > 0")
    assert touring.js("document.querySelector('.tour-offer') === null") and touring.js(f"{CARD} === null")
    # Another page never offers it by itself.
    new_visitor(touring, site_url)
    touring.open(f"{site_url}/biped.html")
    assert touring.js("document.querySelector('.tour-offer') === null") and touring.js(f"{CARD} === null")
    assert touring.errors == []


def test_skip_stops_it_and_take_the_tour_brings_it_back(touring, site_url):  # noqa: F811
    new_visitor(touring, site_url)
    touring.open(f"{site_url}/")
    touring.wait("document.querySelector('.tour-offer') !== null")
    touring.js("[...document.querySelectorAll('.tour-offer button')].find((b) => b.textContent === 'Take the tour').click(); true")
    touring.wait(f"{CARD} !== null")
    assert touring.js("document.querySelector('.tour-count').textContent") == f"Step 1 of {len(STEPS)}"
    assert touring.js(TITLE) == STEPS[0]["title"]
    assert touring.js(f"{CARD}.getAttribute('aria-modal')") == "true"
    assert touring.js("document.querySelector('.tour-spot').getAttribute('aria-hidden')") == "true"
    assert touring.js(f"{CARD}.contains(document.activeElement)"), "focus moves into the card"
    touring.js("[...document.querySelectorAll('.tour-card button')].find((b) => b.textContent === 'Skip').click(); true")
    assert touring.js(f"{CARD} === null") and touring.js("document.querySelector('.tour-spot') === null")
    reopen(touring, f"{site_url}/", "document.querySelectorAll('#builds [role=radio]').length > 0")
    assert touring.js(f"{CARD} === null") and touring.js("document.querySelector('.tour-offer') === null"), "it does not come back by itself"
    # From the footer of the landing page, and from another page's footer.
    touring.js("document.querySelector('footer a[data-tour]').click(); true")
    touring.wait(f"{CARD} !== null")
    assert touring.js(TITLE) == STEPS[0]["title"]
    key(touring, "Escape")
    assert touring.js(f"{CARD} === null")
    touring.open(f"{site_url}/flash.html")
    touring.js("document.querySelector('footer a[data-tour]').click(); true")
    touring.wait(f"location.pathname.endsWith('/') && {CARD} !== null")
    assert touring.js(TITLE) == STEPS[0]["title"]
    key(touring, "Escape")
    assert touring.errors == []


def test_the_keyboard_alone_goes_through_every_step_across_the_pages(touring, site_url):  # noqa: F811
    new_visitor(touring, site_url)
    touring.open(f"{site_url}/")
    touring.wait("document.querySelector('footer a[data-tour]') !== null && document.querySelector('.tour-offer') !== null")
    touring.js("document.querySelector('.tour-offer').remove(); document.querySelector('footer a[data-tour]').focus(); true")
    key(touring, "Enter", "\r")
    touring.wait(f"{CARD} !== null")
    # Focus is held in the card: Tab and Shift+Tab go round its buttons.
    seen = set()
    for _ in range(5):
        key(touring, "Tab")
        assert touring.js(f"{CARD}.contains(document.activeElement)")
        seen.add(touring.js("document.activeElement.textContent"))
    assert seen == {"Next", "Skip"}, "Back is disabled on the first step"
    key(touring, "Tab", shift=True)
    assert touring.js(f"{CARD}.contains(document.activeElement)")
    # Escape closes it and focus goes back to where it was.
    key(touring, "Escape")
    assert touring.js(f"{CARD} === null")
    assert touring.js("document.activeElement.hasAttribute('data-tour')")
    key(touring, "Enter", "\r")
    touring.wait(f"{CARD} !== null")
    visited = []
    for index, step in enumerate(STEPS):
        page = "" if step["page"] == "index.html" else step["page"]
        touring.wait(f"location.pathname.endsWith('/{page}') && {CARD} !== null && {TITLE} === {json.dumps(step['title'])}")
        assert touring.js("document.querySelector('.tour-count').textContent") == f"Step {index + 1} of {len(STEPS)}"
        assert touring.js("document.querySelector('#tour-text').textContent") == step["text"]
        assert touring.js("document.documentElement.scrollWidth <= window.innerWidth")
        if "open" in step:
            assert touring.js(f"document.querySelector({json.dumps(step['open'])}).open")
        if step["id"] in ("builds", "customise", "flash", "admin"):
            touring.wait("!document.querySelector('.tour-spot').hidden")           # it points at the control
        touring.wait(f"(() => {{ const b = {CARD}.getBoundingClientRect(); return b.left >= 0 && b.top >= 0"
                     " && b.right <= window.innerWidth + 1 && b.bottom <= window.innerHeight + 1; })()", 5)   # the card is on the screen
        visited.append(touring.js("location.pathname.split('/').pop() || 'index.html'"))
        touring.wait(f"{CARD}.contains(document.activeElement)")
        label = touring.js("document.activeElement.textContent")
        assert label == ("Finish" if index + 1 == len(STEPS) else "Next"), "focus is on the way forward"
        key(touring, "Enter", "\r")
    touring.wait(f"{CARD} === null")
    assert visited == [step["page"] for step in STEPS]
    assert touring.js("window.localStorage.getItem('botbuilder-tour-seen')") == "1"
    assert touring.js("window.sessionStorage.getItem('botbuilder-tour-step')") is None
    assert touring.errors == []


def test_a_step_carried_in_the_address_and_a_missing_control(touring, site_url):  # noqa: F811
    new_visitor(touring, site_url)
    index = next(i for i, step in enumerate(STEPS) if step["page"] == "biped.html")
    touring.open(f"{site_url}/biped.html?tourstep={index}")
    touring.wait(f"{CARD} !== null && {TITLE} === {json.dumps(STEPS[index]['title'])}")
    # Back goes to the step before, on its own page.
    touring.js("[...document.querySelectorAll('.tour-card button')].find((b) => b.textContent === 'Back').click(); true")
    touring.wait(f"location.pathname.endsWith('/') && {CARD} !== null && {TITLE} === {json.dumps(STEPS[index - 1]['title'])}")
    # A control that is not there: the card is centred and nothing is pointed at.
    touring.js("document.querySelector('#site-nav a.out').remove(); window.botbuilderTour.start(%d); true" % (len(STEPS) - 1))
    touring.wait(f"{CARD} !== null && {TITLE} === {json.dumps(STEPS[-1]['title'])}")
    assert touring.js("document.querySelector('.tour-spot').hidden") and touring.js(f"{CARD}.classList.contains('tour-centred')")
    key(touring, "Escape")
    assert touring.errors == []


def test_on_a_phone_the_card_docks_and_the_sidebar_opens(touring, site_url):  # noqa: F811
    touring.call("Emulation.setDeviceMetricsOverride", width=360, height=740, deviceScaleFactor=2, mobile=True)
    try:
        new_visitor(touring, site_url)
        touring.open(f"{site_url}/")
        touring.wait("document.querySelector('.tour-offer') !== null")
        assert touring.js("document.documentElement.scrollWidth") <= 360
        touring.js("[...document.querySelectorAll('.tour-offer button')].find((b) => b.textContent === 'Take the tour').click(); true")
        for step in STEPS:
            if step["page"] != "index.html":
                break
            touring.wait(f"{CARD} !== null && {TITLE} === {json.dumps(step['title'])}")
            assert touring.js(f"{CARD}.classList.contains('tour-docked')")
            box = touring.js(f"(() => {{ const b = {CARD}.getBoundingClientRect(); return [b.left, b.right, b.bottom]; }})()")
            assert box[0] >= 0 and box[1] <= 360 and 700 <= box[2] <= 740, "docked to the bottom of the screen"
            assert touring.js("document.documentElement.scrollWidth") <= 360, step["id"]
            if "open" in step:
                assert touring.js("document.getElementById('customise').open"), "the collapsed sidebar is opened for the step"
            touring.js("[...document.querySelectorAll('.tour-card button')].find((b) => b.textContent === 'Next').click(); true")
        touring.wait(f"location.pathname.endsWith('/biped.html') && {CARD} !== null")
        assert touring.js("document.documentElement.scrollWidth") <= 360
        key(touring, "Escape")
    finally:
        touring.call("Emulation.clearDeviceMetricsOverride")
    assert touring.errors == []


def test_the_switch_turns_it_off(touring, site_url):  # noqa: F811
    new_visitor(touring, site_url)
    touring.js("window.localStorage.setItem('botbuilder-tour', 'off'); true")
    touring.open(f"{site_url}/?tour=1")
    touring.wait("document.querySelectorAll('#builds [role=radio]').length > 0 && document.querySelector('#recipe .verdict') !== null")
    assert touring.js(f"{CARD} === null") and touring.js("document.querySelector('.tour-offer') === null")
    touring.js("window.localStorage.clear(); true")
    assert touring.errors == []
