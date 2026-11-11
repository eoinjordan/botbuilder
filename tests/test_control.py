# SPDX-License-Identifier: MIT
"""Browser control: the motion manifest, the page's pure logic against the
Python reference, the safety layer, and the HTTP bridge against the virtual
robot. Nothing here opens a serial port or a socket to another machine."""
import importlib.util
import json
import shutil
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request

import pytest

from conftest import ROOT
from microduck import gait, motions, player, protocol, sim, webcontrol

NODE = shutil.which("node")
needs_node = pytest.mark.skipif(not NODE, reason="node is not installed")
ALL = list(webcontrol.CHECKLIST)


def load(name: str, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def cal():
    return protocol.load_calibration()


def dump(tmp_path, request: dict) -> dict:
    path = tmp_path / "request.json"
    path.write_text(json.dumps(request), encoding="utf-8")
    done = subprocess.run([NODE, str(ROOT / "tests" / "js" / "dump_control.mjs"), str(path)], capture_output=True, text=True,
                          encoding="utf-8", check=True)
    return json.loads(done.stdout)


# ---------------------------------------------------------------- manifest

def test_manifest_without_a_file_offers_only_what_exists(cal):
    manifest = motions.load_manifest()
    if (ROOT / motions.MANIFEST).is_file():
        pytest.skip("trajectories/manifest.json is present; the built-in manifest is not in use")
    assert list(manifest["motions"]) == ["stand"]
    assert manifest["gait"]["forward"] == [0.0, 1.0] and manifest["gait"]["turn"] == [0.0, 0.0]
    assert manifest["gait"]["params"]["period_s"] == gait.load_params()["period_s"]
    for name in ("sit", "jump", "back", "turn", "head"):
        assert len(manifest["unavailable"][name]) > 10, name
    assert manifest["robot"]["allow_jump"] is False
    assert manifest["robot"]["stand_deg"] == cal.stand_deg
    assert manifest["robot"]["limits_deg"][0] == [cal.joints[0].min_deg, cal.joints[0].max_deg]


def fake_root(tmp_path, manifest: dict, calibration_extra: dict | None = None):
    for folder in ("config", "robot", "trajectories"):
        (tmp_path / folder).mkdir()
    calibration = json.loads((ROOT / "config" / "calibration.json").read_text(encoding="utf-8"))
    calibration.update(calibration_extra or {})
    (tmp_path / "config" / "calibration.json").write_text(json.dumps(calibration), encoding="utf-8")
    shutil.copyfile(ROOT / "config" / "gait.json", tmp_path / "config" / "gait.json")
    shutil.copyfile(ROOT / "robot" / "joints.json", tmp_path / "robot" / "joints.json")
    (tmp_path / "trajectories" / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return tmp_path


def test_manifest_file_is_checked_and_bad_motions_are_disabled_with_a_reason(tmp_path, cal):
    root = fake_root(tmp_path, {
        "version": 1,
        "gait": {"params": "config/gait.json", "forward": [-0.5, 1.0], "turn": [-1.0, 1.0]},
        "motions": {"stand": {"file": "trajectories/stand.csv"}, "sit": {"file": "trajectories/sit.csv", "label": "Sit down"},
                    "jump": {"file": "trajectories/jump.csv"}, "dance": {"file": "trajectories/sit.csv"}},
    }, {"allow_jump": True})
    stand = list(cal.stand_deg)
    gait.write_csv(root / "trajectories" / "sit.csv", [(0, stand), (20, [stand[0], stand[1] + 1.0] + stand[2:])])
    gait.write_csv(root / "trajectories" / "jump.csv", [(0, stand), (20, [stand[0], stand[1] + 8.0] + stand[2:])])
    manifest = motions.load_manifest(root)
    assert manifest["source"] == "trajectories/manifest.json"
    assert list(manifest["motions"]) == ["sit"]
    assert manifest["motions"]["sit"] == {"label": "Sit down", "file": "trajectories/sit.csv", "duration_ms": 20,
                                          "source": "trajectories/sit.csv"}
    assert "deg/s" in manifest["unavailable"]["jump"], "over the speed limit"
    assert "not playable" in manifest["unavailable"]["stand"], "file missing"
    assert "dance" in manifest["unavailable"]
    assert manifest["gait"]["forward"] == [-0.5, 1.0]
    assert "back" not in manifest["unavailable"] and "turn" not in manifest["unavailable"]
    assert manifest["robot"]["allow_jump"] is True
    exported = motions.export(tmp_path / "out", root)
    assert (tmp_path / "out" / "trajectories" / "sit.csv").is_file()
    assert json.loads((tmp_path / "out" / "motions.json").read_text(encoding="utf-8")) == exported


@pytest.mark.parametrize("bad", [
    {"version": 2},
    {"version": 1, "gait": {"forward": [0.0, 2.0]}},
    {"version": 1, "gait": {"turn": [0.5, 1.0]}},
    {"version": 1, "gait": {"params": "../secret.json"}},
])
def test_malformed_manifest_is_refused(tmp_path, bad):
    with pytest.raises(ValueError):
        motions.load_manifest(fake_root(tmp_path, bad))


def test_manifest_cannot_name_a_file_outside_trajectories(tmp_path):
    root = fake_root(tmp_path, {"version": 1, "motions": {"sit": {"file": "config/gait.json"}, "jump": {"file": "../x.csv"}}})
    manifest = motions.load_manifest(root)
    assert manifest["motions"] == {}
    assert "not under trajectories" in manifest["unavailable"]["sit"]


# ---------------------------------------------------------------- page logic

@needs_node
def test_node_suite_for_the_control_page():
    done = subprocess.run([NODE, "--test", "tests/js/control.test.mjs"], cwd=ROOT, capture_output=True, text=True)
    assert done.returncode == 0, done.stdout[-3000:]


@needs_node
def test_page_gait_is_the_python_gait(tmp_path, cal):
    params = gait.load_params()
    reference = [(t, q) for t, q in gait.gait(cal.stand_deg, params, 4.0) if t / 1000.0 > params["lead_in_s"]]
    times = [t / 1000.0 - params["lead_in_s"] for t, _ in reference]
    out = dump(tmp_path, {"gait": {"stand": cal.stand_deg, "params": params, "times": times, "forward": 1.0, "turn": 0.0}})
    assert out["gait"] == [[protocol.fmt1(v) for v in q] for _, q in reference]


@needs_node
def test_page_playback_controller_is_the_python_controller(tmp_path, cal):
    manifest = motions.load_manifest()
    script = [[0, "S"], [0, "J 0 45 -45 0 45 -45"], [10, "E"], [20, "J 30 45.5 -45 0 45 -45"], [45, "S"], [100, "J -80 0 0 80 0 0"],
              [130, "J 1 2 3"], [140, "J 1e2 0 0 0 0 0"], [150, "Q"], [160, ""], [170, "W 50 hold"], [180, "W 300 hold"],
              [200, "J 0.05 -0.05 10 0 0 0"], [620, "S"], [640, "J 0 45 -45 0 45 -45"], [700, "S"], [720, "W 400 relax"],
              [1300, "S"], [1310, "J 0 0 0 0 0 0"], [1320, "E"], [1330, "R"], [1340, "S"], [1350, "J +5 .5 0 0 0 0"]]
    out = dump(tmp_path, {"robot": manifest["robot"], "script": script})["script"]
    controller = protocol.Controller(cal)
    now, replies = 0, []
    for t, line in script:
        while now + protocol.TICK_MS <= t:
            now += protocol.TICK_MS
            controller.tick(now)
        replies.append(controller.handle(line, t))
    assert out["replies"] == replies
    assert out["mode"] == controller.mode
    assert out["current"] == pytest.approx(controller.current, abs=1e-9)
    assert any(r.startswith("OK CLAMP") for r in replies) and "ERR DISABLED" in replies and any("mode=HOLD" in r for r in replies)


@needs_node
def test_lines_from_a_synthetic_pad_keep_the_simulated_robot_up(tmp_path, cal):
    """Shoulder button held and the stick forward for four seconds, then the
    button released: the J lines the page would send, played into MuJoCo."""
    out = dump(tmp_path, {"drive": {"manifest": motions.load_manifest(), "ms": 5000, "release_ms": 4100}})["drive"]
    lines = [(t, line) for t, line in out if line != "STOP"]
    stops = [t for t, line in out if line == "STOP"]
    assert stops == [4100], "one stop, at the release"
    assert lines[0][0] == 100 and lines[-1][0] == 4050, "nothing before the button, nothing after the release"
    assert [b[0] - a[0] for a, b in zip(lines, lines[1:])] == [50] * (len(lines) - 1), "20 lines a second"
    duck = sim.DuckSim()
    assert duck.send("E") == "OK"
    start = [protocol.parse_joints(line) for _, line in lines][0]
    assert start == pytest.approx(cal.stand_deg, abs=1.0)
    for t, line in lines:
        while duck.now_ms < t:
            duck.tick()
        assert duck.send(line) == "OK", "inside the soft limits: nothing clamped"
    moved = max(abs(a - b) for a, b in zip(duck.controller.current, cal.stand_deg))
    assert moved > 2.0
    # the stop sequence, then silence: the watchdog holds
    status = webcontrol.parse_status(duck.send("S"))
    assert duck.send(protocol.format_joints(status["q"])) == "OK"
    while duck.now_ms < 6000:
        duck.tick()
    assert duck.controller.mode == protocol.HOLD
    assert duck.fell_at is None


# ---------------------------------------------------------------- safety layer

class FakeLink:
    """protocol.Controller behind the link interface, with a clock the test owns."""

    def __init__(self, cal, clock):
        self.controller = protocol.Controller(cal)
        self.clock = clock
        self.lines = []
        self.fail = False
        self.closed = False

    def send(self, line):
        if self.fail:
            raise ConnectionError("link closed")
        now = int(self.clock() * 1000)
        self.lines.append(line.strip())
        return self.controller.handle(line.strip(), now)

    def close(self):
        self.closed = True


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def make_app(cal, allow_motion=True, manifest=None):
    clock = Clock()
    link = FakeLink(cal, clock)
    app = webcontrol.ControlApp(lambda: link, allow_motion=allow_motion, cal=cal, clock=clock, manifest=manifest)
    return app, link, clock


def test_motion_is_off_unless_the_server_was_started_with_it(cal):
    app, link, _ = make_app(cal, allow_motion=False)
    with pytest.raises(ValueError, match="disabled"):
        app.arm(True, ALL)
    with pytest.raises(ValueError):
        app.joints({"token": "x", "held": True, "q": cal.stand_deg})
    with pytest.raises(ValueError):
        app.relax(True)
    state = app.state()
    assert state["robot"]["status"]["mode"] == "RELAX" and state["motion_enabled"] is False
    assert state["run_on_hardware"] is False
    assert app.stop() == {"ok": True, "armed": False, "held": False}
    assert link.lines == ["S"], "status only"


def test_arming_needs_the_confirmation_and_the_whole_checklist(cal):
    app, link, _ = make_app(cal)
    with pytest.raises(ValueError, match="confirmation"):
        app.arm(False, ALL)
    for checklist in (None, [], ALL[:-1], "all"):
        with pytest.raises(ValueError, match="checklist"):
            app.arm(True, checklist)
    assert link.lines == []
    armed = app.arm(True, ALL)
    assert link.lines == ["S", "E", "S"] and armed["status"]["mode"] == "RUN"
    with pytest.raises(ValueError, match="already armed"):
        app.arm(True, ALL)


def test_moves_need_the_token_and_a_held_enable(cal):
    app, link, clock = make_app(cal)
    token = app.arm(True, ALL)["token"]
    sent = len(link.lines)
    for body in ({"q": cal.stand_deg}, {"token": token, "q": cal.stand_deg}, {"token": token, "held": False, "q": cal.stand_deg},
                 {"token": "wrong", "held": True, "q": cal.stand_deg}, {"token": token, "held": "yes", "q": cal.stand_deg}):
        with pytest.raises(ValueError, match="held enable"):
            app.joints(body)
    assert len(link.lines) == sent
    assert app.joints({"token": token, "held": True, "q": cal.stand_deg, "motion": "walk"})["reply"] == "OK"
    assert link.lines[-1] == protocol.format_joints(cal.stand_deg).strip()


def test_moves_are_validated_clamped_and_rate_limited(cal):
    app, link, clock = make_app(cal)
    token = app.arm(True, ALL)["token"]
    ok = {"token": token, "held": True}
    for q in ([0] * 5, [0] * 7, "x", [0, 0, 0, 0, 0, float("nan")], [0, 0, 0, 0, 0, float("inf")], [0, 0, 0, 0, 0, "1"],
              [0, 0, 0, 0, 0, True], [2000, 0, 0, 0, 0, 0], None):
        with pytest.raises(ValueError, match="six finite"):
            app.joints({**ok, "q": q})
    with pytest.raises(ValueError, match="Unknown motion"):
        app.joints({**ok, "q": cal.stand_deg, "motion": "dance"})
    clock.t += 1.0
    result = app.joints({**ok, "q": [-80.0, 45.0, -45.0, 80.0, 45.0, -45.0]})
    assert result["clamped"] == 2 and result["q"][0] == cal.joints[0].min_deg and result["q"][3] == cal.joints[3].max_deg
    sent = len(link.lines)
    clock.t += 0.01
    with pytest.raises(webcontrol.ControlBusy, match="rate limited"):
        app.joints({**ok, "q": cal.stand_deg})
    assert len(link.lines) == sent, "nothing was queued"
    clock.t += 0.03
    assert app.joints({**ok, "q": cal.stand_deg})["ok"] is True


def test_jump_and_missing_motions_are_refused_by_the_server(cal):
    manifest = motions.load_manifest()
    app, link, clock = make_app(cal, manifest=manifest)
    token = app.arm(True, ALL)["token"]
    assert app.jump_enabled is False
    for name in ("jump", "sit"):
        if name in manifest["motions"]:
            continue
        with pytest.raises(ValueError, match="not available"):
            app.joints({"token": token, "held": True, "q": cal.stand_deg, "motion": name})
    with_jump = json.loads(json.dumps(manifest))
    with_jump["motions"]["jump"] = {"label": "Jump", "file": "trajectories/jump.csv", "duration_ms": 1000, "source": "trajectories/jump.csv"}
    app, link, clock = make_app(cal, manifest=with_jump)
    token = app.arm(True, ALL)["token"]
    with pytest.raises(ValueError, match="gears"):
        app.joints({"token": token, "held": True, "q": cal.stand_deg, "motion": "jump"})
    with_jump["robot"]["allow_jump"] = True
    app, link, clock = make_app(cal, manifest=with_jump)
    token = app.arm(True, ALL)["token"]
    assert app.joints({"token": token, "held": True, "q": cal.stand_deg, "motion": "jump"})["ok"] is True


def test_stop_holds_in_place_and_disarms(cal):
    app, link, clock = make_app(cal)
    token = app.arm(True, ALL)["token"]
    app.joints({"token": token, "held": True, "q": [30.0, 45.0, -45.0, 0.0, 45.0, -45.0]})
    for _ in range(5):
        clock.t += 0.02
        link.controller.tick(int(clock.t * 1000))
    link.lines.clear()
    assert app.stop() == {"ok": True, "armed": False, "held": True}
    assert link.lines == ["S", "J 12.0 45.0 -45.0 0.0 45.0 -45.0"], "status, then the reported angles"
    clock.t += 0.02
    link.controller.tick(int(clock.t * 1000))
    assert link.controller.current[0] == pytest.approx(12.0)
    with pytest.raises(ValueError, match="held enable"):
        app.joints({"token": token, "held": True, "q": cal.stand_deg})
    assert app.state()["armed"] is False


def test_lease_expires_and_a_link_error_disarms(cal):
    app, link, clock = make_app(cal)
    token = app.arm(True, ALL)["token"]
    clock.t += webcontrol.LEASE_S + 0.1
    with pytest.raises(ValueError, match="expired"):
        app.joints({"token": token, "held": True, "q": cal.stand_deg})
    token = app.arm(True, ALL)["token"]
    clock.t += 1
    link.fail = True
    with pytest.raises(OSError):
        app.joints({"token": token, "held": True, "q": cal.stand_deg})
    assert link.closed
    assert app.stop()["held"] is False, "stop never raises, even with a dead link"
    state = app.state()
    assert state["robot"]["connected"] is False and state["armed"] is False


def test_relax_asks_for_a_confirmation(cal):
    app, link, _ = make_app(cal)
    app.arm(True, ALL)
    with pytest.raises(ValueError, match="fall"):
        app.relax(False)
    assert app.relax(True)["reply"] == "OK"
    assert link.controller.mode == protocol.RELAX and app.state()["armed"] is False


def test_calibration_mode_blocks_arming(cal):
    app, link, _ = make_app(cal)
    link.controller.handle("E", 0)
    link.controller.handle("C 0", 0)
    with pytest.raises(ValueError, match="calibration"):
        app.arm(True, ALL)


# ---------------------------------------------------------------- HTTP bridge

def request(base, path, body=None, headers=None, method=None):
    data = None if body is None else (body if isinstance(body, bytes) else json.dumps(body).encode("utf-8"))
    req = urllib.request.Request(base + path, data=data, method=method or ("POST" if data is not None else "GET"),
                                 headers={"Content-Type": "application/json", **(headers or {})} if data is not None else (headers or {}))
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            raw = response.read()
            return response.status, raw, response.headers
    except urllib.error.HTTPError as error:
        return error.code, error.read(), error.headers


@pytest.fixture()
def bridge():
    """The virtual robot (MuJoCo behind the board's socket) and the control
    server in front of it, both on 127.0.0.1 with ports the system picks."""
    virtual = load("virtual_robot", ROOT / "scripts" / "virtual_robot.py")
    server_module = load("control_server", ROOT / "app_lab" / "microduck_agent" / "control_server.py")
    port, ready = [], threading.Event()
    robot = threading.Thread(target=virtual.serve, daemon=True,
                             kwargs={"port": 0, "once": True, "ready": lambda p: (port.append(p), ready.set())})
    robot.start()
    assert ready.wait(20)
    server = server_module.make_server("127.0.0.1", 0, "127.0.0.1", port[0], allow_motion=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}", server, server_module
    server.shutdown()
    server.control.close()
    server.server_close()
    try:                                   # let a robot that never had a client finish
        socket.create_connection(("127.0.0.1", port[0]), 2).close()
    except OSError:
        pass
    robot.join(10)


def test_bridge_serves_the_same_page_and_data(bridge):
    base, server, _ = bridge
    status, body, headers = request(base, "/")
    assert status == 200 and body == (ROOT / "site" / "control.html").read_bytes()
    assert headers["X-Content-Type-Options"] == "nosniff"
    for path, name in (("/control.js", "control.js"), ("/style.css", "style.css"), ("/flash.html", "flash.html")):
        assert request(base, path)[1] == (ROOT / "site" / name).read_bytes()
    assert json.loads(request(base, "/data/motions.json")[1]) == motions.load_manifest()
    assert json.loads(request(base, "/data/model.json")[1])["meshes_published"] is False
    assert request(base, "/data/trajectories/stand.csv")[1] == (ROOT / "trajectories" / "stand.csv").read_bytes()
    assert request(base, "/assets/licenses/space-grotesk.txt")[0] == 200
    for path in ("/assets/../../README.md", "/assets/%2e%2e/%2e%2e/README.md", "/data/trajectories/../../README.md",
                 "/data/trajectories/gait_best.csv", "/README.md", "/api/nothing"):
        assert request(base, path)[0] == 404, path


def test_bridge_drives_the_virtual_robot_and_stops(bridge, cal):
    base, server, _ = bridge
    state = json.loads(request(base, "/api/state")[1])
    assert state["microduck_control"] == 1 and state["robot"]["status"]["mode"] == "RELAX"
    assert state["hardware"] is False and state["motion_enabled"] is True and state["armed"] is False

    assert request(base, "/api/joints", {"token": "x", "held": True, "q": cal.stand_deg})[0] == 422
    assert request(base, "/api/arm", {"confirmed": True, "checklist": []})[0] == 422
    assert request(base, "/api/arm", {"confirmed": True, "checklist": ALL}, {"Origin": "https://eoinjordan.github.io"})[0] == 403
    assert request(base, "/api/arm", {"confirmed": True, "checklist": ALL}, {"Sec-Fetch-Site": "cross-site"})[0] == 403
    assert request(base, "/api/arm", b"confirmed=1", {"Content-Type": "text/plain"})[0] == 415
    assert json.loads(request(base, "/api/state")[1])["robot"]["status"]["mode"] == "RELAX", "nothing got through"

    status, body, _ = request(base, "/api/arm", {"confirmed": True, "checklist": ALL})
    assert status == 200
    token = json.loads(body)["token"]
    params = gait.load_params()
    trajectory = gait.gait(cal.stand_deg, params, 2.5)
    start = time.monotonic()
    accepted = busy = 0
    for t, q in trajectory[::3]:                         # every 60 ms
        delay = t / 1000.0 - (time.monotonic() - start)
        if delay > 0:
            time.sleep(delay)
        status, body, _ = request(base, "/api/joints", {"token": token, "held": True, "q": q, "motion": "walk"})
        assert status in (200, 409), body
        accepted += status == 200
        busy += status == 409
    assert accepted > 20
    state = json.loads(request(base, "/api/state")[1])
    assert state["robot"]["status"]["mode"] == "RUN" and state["armed"] is True
    moved = max(abs(a - b) for a, b in zip(state["robot"]["status"]["q"], cal.stand_deg))
    assert moved > 1.0

    status, body, _ = request(base, "/api/stop", b"", {"Content-Type": "text/plain"})
    assert status == 200 and json.loads(body) == {"ok": True, "armed": False, "held": True}
    held = json.loads(request(base, "/api/state")[1])["robot"]["status"]["q"]
    assert request(base, "/api/joints", {"token": token, "held": True, "q": cal.stand_deg})[0] == 422, "the token died with the stop"
    time.sleep(0.8)
    state = json.loads(request(base, "/api/state")[1])
    assert state["robot"]["status"]["mode"] == "HOLD", "no more lines: the watchdog holds"
    # The stop reads the commanded position and then sends it back as the hold target, two lines
    # on the socket. If a 20 ms controller tick falls between them, the position read straight
    # after the stop is one tick of travel past the target and settles back onto it.
    one_tick = cal.max_speed_deg_s * protocol.TICK_MS / 1000.0
    assert state["robot"]["status"]["q"] == pytest.approx(held, abs=one_tick + 0.3)
    time.sleep(0.2)
    assert json.loads(request(base, "/api/state")[1])["robot"]["status"]["q"] == state["robot"]["status"]["q"], "and stays there"


def test_bridge_refuses_a_remote_robot_without_the_flag(bridge):
    _, _, server_module = bridge
    with pytest.raises(player.HardwareNotAllowed):
        server_module.make_server("127.0.0.1", 0, "192.0.2.1", 8766)
