# SPDX-License-Identifier: MIT
"""The Flash and Control pages in a real browser, headless.

Uses an installed Chrome or Chromium driven over the DevTools protocol with
the websockets package; nothing is downloaded. Skipped when either is
missing. The game controller is synthetic: navigator.getGamepads is replaced
before the page loads. The real target is exercised only against the virtual
robot on 127.0.0.1.
"""
import functools
import http.server
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

import pytest

from conftest import ROOT
from test_control import bridge  # noqa: F401  (fixture)

SITE = ROOT / "site"
STAND = [0.0, 45.0, -45.0, 0.0, 45.0, -45.0]


def find_chrome():
    candidates = [os.environ.get("CHROME"), shutil.which("google-chrome"), shutil.which("chromium"), shutil.which("chromium-browser"),
                  shutil.which("chrome"), r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                  r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]
    return next((c for c in candidates if c and Path(c).is_file()), None)


class Browser:
    def __init__(self, chrome: str, profile: Path):
        from websockets.sync.client import connect
        self.process = subprocess.Popen(
            [chrome, "--headless=new", "--remote-debugging-port=0", f"--user-data-dir={profile}", "--no-first-run",
             "--no-default-browser-check", "--disable-extensions", "--enable-unsafe-swiftshader", "--window-size=1280,900",
             "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        port_file = profile / "DevToolsActivePort"
        deadline = time.monotonic() + 30
        port = None
        while port is None:
            if time.monotonic() > deadline or self.process.poll() is not None:
                self.process.kill()
                raise RuntimeError("Chrome did not start")
            time.sleep(0.1)
            try:                             # Chrome may still be writing the file
                port = int(port_file.read_text().splitlines()[0])
            except (OSError, IndexError, ValueError):
                port = None
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=5) as response:
            pages = [t for t in json.load(response) if t["type"] == "page"]
        self.socket = connect(pages[0]["webSocketDebuggerUrl"], max_size=None).__enter__()
        self.next_id = 0
        self.errors = []
        self.call("Page.enable")
        self.call("Runtime.enable")
        self.call("Emulation.setFocusEmulationEnabled", enabled=True)
        self.call("Page.addScriptToEvaluateOnNewDocument", source=(
            "window.__pad = null;"
            "Object.defineProperty(navigator, 'getGamepads', { configurable: true, value: () => [window.__pad] });"))

    def call(self, method: str, **params):
        self.next_id += 1
        self.socket.send(json.dumps({"id": self.next_id, "method": method, "params": params}))
        while True:
            message = json.loads(self.socket.recv(timeout=30))
            if message.get("method") == "Runtime.exceptionThrown":
                self.errors.append(message["params"]["exceptionDetails"].get("exception", {}).get("description", "exception"))
            if message.get("id") == self.next_id:
                if "error" in message:
                    raise RuntimeError(message["error"])
                return message.get("result", {})

    def js(self, expression: str):
        result = self.call("Runtime.evaluate", expression=expression, returnByValue=True, awaitPromise=True,
                           replMode=True)
        if "exceptionDetails" in result:
            raise RuntimeError(result["exceptionDetails"].get("exception", {}).get("description", str(result["exceptionDetails"])))
        return result["result"].get("value")

    def open(self, url: str, ready: str = "document.readyState === 'complete'"):
        self.call("Page.navigate", url=url)
        self.wait(f"location.href.startsWith({json.dumps(url.split('?')[0])}) && ({ready})")

    def wait(self, expression: str, seconds: float = 15.0):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            try:
                if self.js(expression):
                    return
            except RuntimeError:
                pass
            time.sleep(0.05)
        raise AssertionError(f"timed out waiting for: {expression}")

    def snapshot(self) -> dict:
        return self.js("window.microduckControl.snapshot()")

    def pad(self, buttons=(), axes=(0, 0, 0, 0)):
        self.js("window.__pad = { id: 'Synthetic pad (STANDARD GAMEPAD)', index: 0, connected: true, mapping: 'standard', "
                f"axes: {json.dumps(list(axes))}, buttons: Array.from({{ length: 17 }}, (_, i) => "
                f"({{ pressed: {json.dumps(list(buttons))}.includes(i), value: 0 }})) }}; true")

    def close(self):
        try:
            self.socket.close()
        except Exception:
            pass
        self.process.terminate()
        try:
            self.process.wait(10)
        except subprocess.TimeoutExpired:
            self.process.kill()


@pytest.fixture(scope="module")
def site_url():
    subprocess.run([sys.executable, str(ROOT / "scripts" / "build_site.py")], check=True, capture_output=True)

    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(SITE)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    # A repository base path, as on GitHub Pages, is covered by the relative-path test in test_site_pages.py.
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()


@pytest.fixture(scope="module")
def browser(tmp_path_factory):
    chrome = find_chrome()
    if not chrome:
        pytest.skip("no installed Chrome or Chromium")
    pytest.importorskip("websockets", reason="the websockets package is not installed")
    instance = Browser(chrome, tmp_path_factory.mktemp("chrome-profile"))
    yield instance
    instance.close()
    time.sleep(0.5)


READY = "document.documentElement.dataset.ready === '1'"


def test_control_page_in_simulator_target_with_a_synthetic_gamepad(browser, site_url):
    browser.open(f"{site_url}/control.html", READY)
    first = browser.snapshot()
    assert first["target"] == "sim" and first["board"] is False and first["realDisabled"] is True
    assert first["mode"] == "RELAX" and first["q"] == STAND and first["sent"] == 0
    assert "not served by the robot's server" in browser.js("document.getElementById('real-reason').textContent")
    assert "Playback, not physics" in browser.js("document.getElementById('view-note').textContent") or not first["viewer"]
    assert "not run on hardware" in browser.js("document.body.textContent")

    # what is missing is disabled and says why
    actions = browser.js("document.getElementById('actions').textContent")
    for reason in ("Sit: no sit trajectory", "Jump (hold): no jump trajectory", "Head pan and tilt: the head is fixed", "Turn: "):
        assert reason in actions, reason
    assert browser.js("document.querySelector('[data-hold=sit]').disabled && document.querySelector('[data-hold=jump]').disabled")
    assert browser.js("document.querySelector('[data-hold=sit]').title").startswith("no sit trajectory")
    assert browser.js("!document.querySelector('[data-hold=forward]').disabled && !document.querySelector('[data-hold=stand]').disabled")

    # stick forward without the shoulder button: nothing
    browser.pad()
    time.sleep(0.3)
    assert "Synthetic pad" in browser.js("document.getElementById('pad-name').textContent")
    browser.pad(axes=(0, -1, 0, 0))
    time.sleep(0.5)
    idle = browser.snapshot()
    assert idle["sent"] == 0 and idle["live"] is False and idle["command"]["type"] == "idle"

    # shoulder button held: the gait plays
    browser.pad(buttons=[4], axes=(0, -1, 0, 0))
    browser.wait("window.microduckControl.snapshot().sent > 25")
    walking = browser.snapshot()
    assert walking["live"] is True and walking["command"] == {"type": "walk", "forward": 1, "turn": 0}
    assert walking["lastLine"].startswith("J ") and walking["lastReply"] == "OK" and walking["mode"] == "RUN"
    assert max(abs(a - b) for a, b in zip(walking["q"], STAND)) > 1.0
    assert browser.js("document.getElementById('pad-button-4').classList.contains('on')")
    assert browser.js("document.getElementById('q-0').textContent") != ""

    # release: one stop, then the watchdog holds
    browser.pad(axes=(0, -1, 0, 0))
    browser.wait("window.microduckControl.snapshot().stops === 1")
    released = browser.snapshot()
    assert released["stopReason"] == "enable released" and released["live"] is False
    sent = released["sent"]
    browser.wait("window.microduckControl.snapshot().mode === 'HOLD'", 3)
    assert browser.snapshot()["sent"] == sent, "nothing is sent after the stop"

    # pad vanishes while moving
    browser.pad(buttons=[5], axes=(0, -1, 0, 0))
    browser.wait(f"window.microduckControl.snapshot().sent > {sent + 5}")
    browser.js("window.__pad = null; true")
    browser.wait("window.microduckControl.snapshot().stops === 2")
    assert browser.snapshot()["stopReason"] == "controller disconnected"

    # the stop button on the pad, then Escape, then the tab going hidden
    browser.pad()
    time.sleep(0.3)
    browser.pad(buttons=[4], axes=(0, -1, 0, 0))
    browser.wait("window.microduckControl.snapshot().live")
    browser.pad(buttons=[4, 1], axes=(0, -1, 0, 0))
    browser.wait("window.microduckControl.snapshot().stops === 3")
    browser.pad(buttons=[4], axes=(0, -1, 0, 0))
    time.sleep(0.4)
    latched = browser.snapshot()
    assert latched["live"] is False and "release" in latched["command"]["reason"]
    browser.pad()
    time.sleep(0.2)
    browser.pad(buttons=[4], axes=(0, -1, 0, 0))
    browser.wait("window.microduckControl.snapshot().live")
    for kind in ("keyDown", "keyUp"):
        browser.call("Input.dispatchKeyEvent", type=kind, key="Escape", code="Escape", windowsVirtualKeyCode=27)
    browser.wait("window.microduckControl.snapshot().stops === 4")
    assert browser.snapshot()["stopReason"] == "Escape key"
    browser.js("document.getElementById('stop').click(); true")
    assert browser.snapshot()["stops"] == 5 and browser.snapshot()["stopReason"] == "stop button"

    # keyboard: Shift is the enable control
    browser.pad()
    time.sleep(0.3)                      # the release has to be seen before the next enable
    browser.call("Input.dispatchKeyEvent", type="keyDown", key="Shift", code="ShiftLeft", windowsVirtualKeyCode=16)
    browser.call("Input.dispatchKeyEvent", type="keyDown", key="W", code="KeyW", windowsVirtualKeyCode=87, modifiers=8)
    browser.wait("window.microduckControl.snapshot().command.type === 'walk'")
    browser.call("Input.dispatchKeyEvent", type="keyUp", key="Shift", code="ShiftLeft", windowsVirtualKeyCode=16)
    browser.wait("window.microduckControl.snapshot().stops === 6")
    browser.call("Input.dispatchKeyEvent", type="keyUp", key="w", code="KeyW", windowsVirtualKeyCode=87)

    # on-screen: holding the button is the enable; expert jog stays inside the limits
    browser.js("document.getElementById('expert').click(); true")
    assert browser.js("document.querySelector('[data-hold=forward]').disabled && !document.querySelector('[data-hold=\"jog-minus\"]').disabled")
    browser.js("const b = document.querySelector('[data-hold=\"jog-plus\"]'); b.focus();"
               "b.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })); true")
    browser.wait("window.microduckControl.snapshot().command.type === 'jog'")
    time.sleep(0.6)
    jogged = browser.snapshot()
    assert 0 < jogged["q"][0] < 20, "15 deg/s, slowly"
    browser.js("document.querySelector('[data-hold=\"jog-plus\"]').dispatchEvent(new KeyboardEvent('keyup', { key: 'Enter', bubbles: true })); true")
    browser.wait("window.microduckControl.snapshot().stops === 7")
    assert browser.errors == []


def test_pages_fit_a_phone_and_flash_builds_commands(browser, site_url):
    browser.call("Emulation.setDeviceMetricsOverride", width=360, height=740, deviceScaleFactor=2, mobile=True)
    try:
        browser.open(f"{site_url}/control.html", READY)
        assert browser.js("document.documentElement.scrollWidth") <= 360
        browser.open(f"{site_url}/flash.html")
        assert browser.js("document.documentElement.scrollWidth") <= 360
        assert browser.js("document.querySelectorAll('#commands li').length") == 0, "nothing before the servo box is ticked"
        browser.js("document.getElementById('servo-off').click(); const h = document.getElementById('host'); h.value = 'unoq.local';"
                   "h.dispatchEvent(new Event('input', { bubbles: true })); true")
        commands = browser.js("[...document.querySelectorAll('#commands pre')].map((pre) => pre.textContent)")
        assert len(commands) == 8 and commands[0] == "ssh 'arduino@unoq.local'"
        assert commands[4] == "arduino-app-cli app start \"$HOME\"/'ArduinoApps/microduck_agent'"
        assert browser.js("document.documentElement.scrollWidth") <= 360, "long commands scroll inside their block"
        assert browser.js("document.querySelectorAll('#commands button.copy').length") == 8
        browser.js("const g = document.getElementById('host'); g.value = 'x; rm -rf ~'; g.dispatchEvent(new Event('input', { bubbles: true })); true")
        assert browser.js("document.querySelectorAll('#commands li').length") == 0
        assert browser.js("!document.getElementById('form-error').hidden")

        browser.open(f"{site_url}/flash.html?base=m5stack-core2&host=unoq.local")
        assert "M5Stack" in browser.js("document.getElementById('base-note').textContent")
        assert "Not written" in browser.js("document.getElementById('base-note').textContent")
        assert browser.js("document.getElementById('flash-form').hidden")
        assert browser.js("document.querySelectorAll('#commands li').length") == 0
        browser.open(f"{site_url}/flash.html?base=%3Cimg%20src%3Dx%20onerror%3Dalert(1)%3E")
        assert browser.js("document.querySelectorAll('#base-note img').length") == 0
        browser.open(f"{site_url}/flash.html?base=unoq&host=10.0.0.7")
        assert browser.js("document.getElementById('host').value") == "10.0.0.7"
        assert not browser.js("document.getElementById('flash-form').hidden")
    finally:
        browser.call("Emulation.clearDeviceMetricsOverride")
    assert browser.errors == []


def test_board_served_page_drives_the_virtual_robot(browser, bridge):  # noqa: F811
    base, server, _ = bridge
    browser.open(f"{base}/", READY)
    first = browser.snapshot()
    assert first["board"] is True and first["realDisabled"] is False and first["target"] == "sim", "simulator is the default"
    browser.js("document.getElementById('target-real').click(); true")
    browser.wait("window.microduckControl.snapshot().target === 'real'")
    browser.wait("!document.getElementById('arm').disabled")
    assert "not run on hardware" in browser.js("document.getElementById('target-label').textContent").lower()

    # not armed: a held pad does nothing
    browser.pad()
    time.sleep(0.3)
    browser.pad(buttons=[4], axes=(0, -1, 0, 0))
    time.sleep(0.5)
    assert browser.snapshot()["sent"] == 0
    assert server.control.sent == 0
    browser.pad()

    # the checklist gates arming
    browser.js("document.getElementById('arm').click(); true")
    assert browser.js("document.getElementById('preflight').open && document.getElementById('confirm-arm').disabled")
    browser.js("for (const box of document.querySelectorAll('#preflight input')) box.click(); true")
    assert browser.js("!document.getElementById('confirm-arm').disabled")
    browser.js("document.getElementById('confirm-arm').click(); true")
    browser.wait("window.microduckControl.snapshot().armed")

    browser.pad()
    time.sleep(0.3)
    browser.pad(buttons=[4], axes=(0, -1, 0, 0))
    browser.wait("window.microduckControl.snapshot().sent > 20")
    assert server.control.sent > 20
    state = server.control.state()
    assert state["robot"]["status"]["mode"] == "RUN" and state["armed"] is True
    assert max(abs(a - b) for a, b in zip(state["robot"]["status"]["q"], STAND)) > 1.0

    browser.pad(axes=(0, -1, 0, 0))
    browser.wait("window.microduckControl.snapshot().stops >= 1 && !window.microduckControl.snapshot().armed")
    deadline = time.monotonic() + 5
    while server.control.state()["armed"] and time.monotonic() < deadline:
        time.sleep(0.05)
    sent = server.control.sent
    time.sleep(0.9)
    state = server.control.state()
    assert state["armed"] is False and state["robot"]["status"]["mode"] == "HOLD"
    assert server.control.sent == sent
    assert browser.errors == []
    browser.open("about:blank")
