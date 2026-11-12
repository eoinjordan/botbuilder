# SPDX-License-Identifier: MIT
"""The landing page in a real browser, headless: the finished builds as
cards, the sidebar that drills into a custom build and back, the short
address, the PDF and the zip, at desktop width and at 360 px. Uses the
installed Chrome the control page test uses; skipped without it."""
import json

import pytest

from conftest import ROOT
from microduck import recipe
from test_control_page import browser, site_url  # noqa: F401  (fixtures)

LOADED = "document.querySelectorAll('#builds [role=radio]').length > 0 && document.querySelector('#recipe .verdict') !== null"
CHECKED = "(document.querySelector('#builds [aria-checked=true]') || { dataset: {} }).dataset.build || ''"
SAVE_HOOK = ("window.__saved = []; const keep = URL.createObjectURL.bind(URL);"
             "URL.createObjectURL = (blob) => { window.__saved.push(blob); return keep(blob); }; true")


@pytest.fixture(scope="module")
def builds():
    return recipe.bundle(ROOT)["builds"]


def fresh(browser, url):  # noqa: F811
    """Open the page with nothing remembered from the test before."""
    origin = url.split("/?")[0].rstrip("/")
    browser.open(f"{origin}/assets/licenses/space-grotesk.txt")      # same origin, loads nothing else
    browser.js("window.localStorage.clear(); true")
    browser.open(url, LOADED)


def set_field(browser, name, value):  # noqa: F811
    browser.js(f"const s = document.getElementById('pick-{name}'); s.value = {json.dumps(value)};"
               "s.dispatchEvent(new Event('change', { bubbles: true })); true")


def test_cards_select_and_show_their_recipes(browser, site_url, builds):  # noqa: F811
    fresh(browser, f"{site_url}/")
    ids = [item["id"] for item in builds["list"]]
    assert browser.js("[...document.querySelectorAll('#builds [role=radio]')].map((card) => card.dataset.build)") == ids
    assert browser.js(CHECKED) == builds["default"], "one card is selected before anything is clicked"
    assert browser.js("document.getElementById('custom-note').hidden")
    assert browser.js("document.querySelector('main').firstElementChild.querySelector('#builds') !== null"), "cards come first"
    assert browser.js("document.getElementById('customise').open"), "the sidebar is open on a wide screen"
    assert browser.js("document.title") == "Botbuilder" and browser.js("document.querySelector('h1').textContent") == "Botbuilder"
    for item in builds["list"]:
        browser.js(f"document.querySelector('#builds [data-build={json.dumps(item['id'])}]').click(); true")
        assert browser.js(CHECKED) == item["id"]
        assert browser.js("location.search") == f"?build={item['id']}"
        assert browser.js("document.querySelector('#recipe .verdict h2').textContent") == "Simulated"
        assert browser.js("document.getElementById('recipe-name').textContent") == item["name"]
        assert browser.js("document.querySelectorAll('#recipe .part-card img').length") > 0
        assert browser.js("[...document.querySelectorAll('#recipe .recipe-block h3')].map((h) => h.textContent)") == [
            "What this is", "Files to print", "Parts", "Wiring", "Power and supply sizing", "Firmware and software", "Analysis",
            "Assembly", "Maker documentation for this base"]
        for name, value in item["selection"].items():
            assert browser.js(f"document.getElementById('pick-{name}').value") == value, "the sidebar shows the build"
        browser.wait(f"document.querySelector('#builds [data-build={json.dumps(item['id'])}] img').naturalWidth === 400")
    assert browser.errors == []


def test_arrow_keys_move_through_the_cards(browser, site_url, builds):  # noqa: F811
    fresh(browser, f"{site_url}/")
    ids = [item["id"] for item in builds["list"]]
    assert browser.js("[...document.querySelectorAll('#builds [role=radio]')].filter((card) => card.tabIndex === 0).length") == 1
    browser.js("document.querySelector('#builds [aria-checked=true]').focus(); true")
    for key, expected in (("ArrowRight", ids[1]), ("ArrowDown", ids[2]), ("ArrowLeft", ids[1]), ("ArrowUp", ids[0]), ("ArrowLeft", ids[-1])):
        browser.call("Input.dispatchKeyEvent", type="keyDown", key=key, code=key)
        browser.call("Input.dispatchKeyEvent", type="keyUp", key=key, code=key)
        assert browser.js(CHECKED) == expected
        assert browser.js("document.activeElement.dataset.build") == expected
    outline = browser.js("getComputedStyle(document.activeElement).outlineStyle")
    assert outline not in ("none", ""), "focus is visible on a card"
    assert browser.errors == []


def test_the_sidebar_makes_a_custom_build_and_a_card_brings_it_back(browser, site_url, builds):  # noqa: F811
    fresh(browser, f"{site_url}/?build={builds['default']}")
    assert browser.js("document.getElementById('picker').getAttribute('aria-labelledby')") == "pick-heading"
    set_field(browser, "lego", "off")
    assert browser.js(CHECKED) == "", "no card is selected for a custom build"
    assert not browser.js("document.getElementById('custom-note').hidden")
    assert browser.js("document.getElementById('recipe-name').textContent") == "Custom build"
    assert "lego=off" in browser.js("location.search") and "build=" not in browser.js("location.search")
    browser.js(f"document.querySelector('#builds [data-build={json.dumps(builds['default'])}]').click(); true")
    assert browser.js(CHECKED) == builds["default"] and browser.js("document.getElementById('pick-lego').value") == "on"
    set_field(browser, "lego", "off")
    browser.js("document.getElementById('reset').click(); true")
    assert browser.js(CHECKED) == builds["default"]
    assert browser.errors == []


def test_short_and_long_addresses(browser, site_url, builds):  # noqa: F811
    data = recipe.bundle(ROOT)
    for item in builds["list"]:
        fresh(browser, f"{site_url}/?build={item['id']}")
        assert browser.js(CHECKED) == item["id"]
        long_form = recipe.query(data["compat"], recipe.build_selection(data, item))
        fresh(browser, f"{site_url}/?{long_form}")
        assert browser.js(CHECKED) == item["id"], "the long form of a finished build marks its card"
    # An old link to any selection still shows that selection.
    fresh(browser, f"{site_url}/?controller=m5core&locomotion=wheeled&drive=basex_ev3&camera=none&head=fixed&lego=on&wheels=front&support=skid&wheel=lego")
    assert browser.js(CHECKED) == "" and browser.js("document.getElementById('pick-controller').value") == "m5core"
    assert browser.js("document.getElementById('pick-wheels').value") == "front"
    # A type page's link names one field and is completed.
    fresh(browser, f"{site_url}/?locomotion=wheeled")
    assert browser.js("document.getElementById('pick-locomotion').value") == "wheeled"
    # A build with one field changed, and an unknown build.
    fresh(browser, f"{site_url}/?build={builds['list'][-1]['id']}&lego=off")
    assert browser.js(CHECKED) == "" and browser.js("document.getElementById('pick-lego').value") == "off"
    assert browser.js("document.getElementById('pick-controller').value") == builds["list"][-1]["selection"]["controller"]
    fresh(browser, f"{site_url}/?build=no-such-build")
    assert browser.js(CHECKED) == builds["default"]
    assert browser.errors == []


def test_pdf_and_zip_are_built_for_a_finished_build(browser, site_url, builds):  # noqa: F811
    browser.call("Browser.setDownloadBehavior", behavior="deny")
    fresh(browser, f"{site_url}/?build={builds['list'][1]['id']}")
    browser.js(SAVE_HOOK)
    browser.js("document.getElementById('download-pdf').click(); true")
    browser.wait("document.getElementById('action-note').textContent === 'PDF saved.'")
    head = browser.js("await window.__saved[0].slice(0, 5).text()")
    assert head == "%PDF-" and browser.js("window.__saved[0].size") > 20000
    browser.js("document.getElementById('download-all').click(); true")
    browser.wait("document.getElementById('action-note').textContent.startsWith('Zip saved')", 60)
    assert browser.js("await window.__saved[1].slice(0, 2).text()") == "PK" and browser.js("window.__saved[1].size") > 100000
    listing = browser.js("await window.__saved[1].text()")
    assert "recipe.pdf" in listing and "README.txt" in listing and f"?build={builds['list'][1]['id']}" in listing
    assert browser.errors == []


def test_phone_width_has_no_sideways_scroll_and_a_collapsed_sidebar(browser, site_url, builds):  # noqa: F811
    browser.call("Emulation.setDeviceMetricsOverride", width=360, height=740, deviceScaleFactor=2, mobile=True)
    try:
        fresh(browser, f"{site_url}/")
        assert browser.js("document.documentElement.scrollWidth") <= 360
        assert not browser.js("document.getElementById('customise').open"), "behind its control on a phone"
        assert browser.js("document.getElementById('builds').scrollWidth") > 360, "the cards scroll inside their own row"
        assert browser.js("document.getElementById('builds').getBoundingClientRect().top") < 400, "the cards are the first thing"
        browser.js("document.querySelector('#customise > summary').click(); true")
        assert browser.js("document.getElementById('customise').open")
        set_field(browser, "lego", "off")
        assert browser.js(CHECKED) == "" and browser.js("document.getElementById('customise').open")
        assert browser.js("document.documentElement.scrollWidth") <= 360
        for item in builds["list"]:
            browser.js(f"document.querySelector('#builds [data-build={json.dumps(item['id'])}]').click(); true")
            assert browser.js(CHECKED) == item["id"]
            assert browser.js("document.documentElement.scrollWidth") <= 360, item["id"]
    finally:
        browser.call("Emulation.clearDeviceMetricsOverride")
    assert browser.errors == []


def test_pictures_of_the_choices_and_the_bought_parts(browser, site_url, builds):  # noqa: F811
    fresh(browser, f"{site_url}/?build={builds['list'][-1]['id']}")
    # The chosen option's picture beside every field, named by the component.
    shown = browser.js("[...document.querySelectorAll('#picker .field')].map((field) => {"
                       " const img = field.querySelector('.field-picture'); return [field.querySelector('select').name, img.hidden, img.alt]; })")
    assert len(shown) == 11 and all(not hidden and alt for _, hidden, alt in shown), shown
    browser.wait("[...document.querySelectorAll('#picker .field-picture')].every((img) => img.complete && img.naturalWidth > 0)")
    # The options as pictures: buttons that set the native select, greyed where the select is.
    browser.js("document.querySelector('#picker .option-pictures').open = true; true")
    labels = browser.js("[...document.querySelectorAll('#picker .field')[0].querySelectorAll('.option-card')].map((card) => card.textContent)")
    assert labels == browser.js("[...document.getElementById('pick-controller').options].map((option) => option.textContent)")
    browser.js("[...document.querySelectorAll('#picker .field')[0].querySelectorAll('.option-card')]"
               ".find((card) => card.textContent.includes('EV3')).click(); true")
    assert browser.js("document.getElementById('pick-controller').value") == "ev3"
    assert browser.js("document.querySelector('#picker .option-card[aria-pressed=true]').textContent").startswith("LEGO EV3")
    assert browser.js(CHECKED) == "", "choosing by picture makes a custom build like the list does"
    off = browser.js("[...document.querySelectorAll('#picker .field')[2].querySelectorAll('.option-card')]"
                     ".filter((card) => card.getAttribute('aria-disabled') === 'true').map((card) => card.title)")
    assert off and all(off), "a greyed option keeps its reason"
    before = browser.js("location.search")
    browser.js("[...document.querySelectorAll('#picker .field')[2].querySelectorAll('.option-card')]"
               ".find((card) => card.getAttribute('aria-disabled') === 'true').click(); true")
    assert browser.js("location.search") == before, "a greyed picture does nothing"
    # The parts list: a picture beside each bought part, and a link to the credits.
    rows = browser.js("[...document.querySelectorAll('#recipe table tr')].slice(1).map((tr) => {"
                      " const img = tr.querySelector('td.part-picture img'); return [tr.children[1].textContent, img ? img.alt : '']; })")
    assert rows and all(alt for _, alt in rows), rows
    assert browser.js("document.querySelector('#recipe a[href=\"./credits.html\"]') !== null")
    browser.call("Browser.setDownloadBehavior", behavior="deny")
    browser.js(SAVE_HOOK)
    browser.js("document.getElementById('download-pdf').click(); true")
    browser.wait("document.getElementById('action-note').textContent === 'PDF saved.'")
    pdf = browser.js("await window.__saved[0].text()")
    assert "(Picture credits) Tj" in pdf and "credits.html" in pdf and "photograph by" in pdf
    browser.open(f"{site_url}/credits.html")
    assert browser.js("document.querySelectorAll('table.credits tr').length") > 40
    browser.wait("[...document.querySelectorAll('table.credits img')].slice(0, 6).every((img) => img.complete && img.naturalWidth === 320)")
    browser.call("Emulation.setDeviceMetricsOverride", width=360, height=740, deviceScaleFactor=2, mobile=True)
    try:
        browser.open(f"{site_url}/credits.html")
        assert browser.js("document.documentElement.scrollWidth") <= 360
        fresh(browser, f"{site_url}/?build={builds['list'][0]['id']}")
        browser.js("document.getElementById('customise').open = true;"
                   "for (const more of document.querySelectorAll('#picker .option-pictures')) more.open = true; true")
        assert browser.js("document.documentElement.scrollWidth") <= 360
    finally:
        browser.call("Emulation.clearDeviceMetricsOverride")
    assert browser.errors == []
