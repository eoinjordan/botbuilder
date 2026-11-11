# SPDX-License-Identifier: MIT
"""The Flash page: the commands it builds name paths that exist, match the
manual steps in docs/flash.md, and survive hostile input when a real shell
reads them. No SSH connection is made: every program is a stand-in that
prints its arguments."""
import json
import re
import shutil
import subprocess

import pytest

from conftest import ROOT
from microduck import protocol

NODE = shutil.which("node")
SH = shutil.which("sh")
needs_node = pytest.mark.skipif(not NODE, reason="node is not installed")
needs_sh = pytest.mark.skipif(not (NODE and SH), reason="needs node and a POSIX sh")
REPO_DIR = "botbuilder"
HOSTILE = ["a'b", "'; touch pwned; '", "x; touch pwned", "`touch pwned`", "$(touch pwned)", "${HOME}", "$HOME", "-rf", "--help",
           "a b", "a|touch pwned", "a&touch pwned", "a>pwned", "a\\b", "\"; touch pwned; \"", "~root", "*", "'\\''", "'$(touch pwned)'",
           "a\\", "!!", "#x", "(x)", "a'b'c''d"]
CONTROL = ["a\nb", "a\rtouch pwned", "a\tb", "a\x00b", "a\x1bb", "a\x7fb", "x\ntouch pwned\n"]


def dump(tmp_path, request: dict) -> dict:
    path = tmp_path / "request.json"
    path.write_text(json.dumps(request), encoding="utf-8")
    done = subprocess.run([NODE, str(ROOT / "tests" / "js" / "dump_flash.mjs"), str(path)], capture_output=True, text=True,
                          encoding="utf-8", check=True)
    return json.loads(done.stdout)


def commands(plan: dict) -> list:
    return [step["command"] for step in plan["steps"]]


def run_script(tmp_path, lines: list) -> list:
    """Run the lines in sh with every program replaced by a stand-in that
    prints its name and each argument in brackets. Returns the output lines."""
    stubs = tmp_path / "bin"
    stubs.mkdir(exist_ok=True)
    stub = "#!/bin/sh\nprintf '[%s]' \"${0##*/}\"\nfor a in \"$@\"; do printf '[%s]' \"$a\"; done\nprintf '\\n'\n"
    for name in ("ssh", "git", "mkdir", "cp", "rm", "arduino-app-cli", "nc", "python3", "touch", "show"):
        (stubs / name).write_bytes(stub.encode("ascii"))
        (stubs / name).chmod(0o755)
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    script = tmp_path / "script.sh"
    # A relative PATH: a Windows path would be split at its drive colon.
    script.write_bytes(("HOME=/home/t\nPATH=../bin\n" + "\n".join(lines) + "\n").encode("utf-8"))
    done = subprocess.run([SH, "../script.sh"], cwd=work, capture_output=True, timeout=60)
    assert done.returncode == 0, done.stderr.decode("utf-8", "replace")
    assert list(work.iterdir()) == [], "a command created a file"
    return done.stdout.decode("utf-8").splitlines()


@needs_node
def test_node_suite_for_the_flash_page():
    done = subprocess.run([NODE, "--test", "tests/js/flash.test.mjs"], cwd=ROOT, capture_output=True, text=True)
    assert done.returncode == 0, done.stdout[-3000:]


@needs_node
def test_every_path_a_command_names_exists(tmp_path):
    out = dump(tmp_path, {"plans": {"install": {"host": "unoq.local"}, "update": {"host": "unoq.local", "mode": "update"}}})
    constants = out["constants"]
    app = ROOT / constants["APP_PATH"]
    assert app.is_dir() and app.name == constants["APP_NAME"]
    for name in ("app.yaml", "python/main.py", "sketch/sketch.ino", "sketch/sketch.yaml"):
        assert (app / name).is_file(), name
    assert (ROOT / constants["SERVER_PATH"]).is_file()
    named = set()
    for plan in out["plans"].values():
        for command in commands(plan):
            named.update(re.findall(rf"'{REPO_DIR}/([^']+)'", command))
    assert named == {constants["APP_PATH"], constants["SERVER_PATH"]}
    for path in named:
        assert (ROOT / path).exists(), path
    remote = subprocess.run(["git", "remote", "get-url", "origin"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    if remote:
        assert remote.removesuffix(".git") == constants["REPOSITORY"].removesuffix(".git")


@needs_node
def test_ports_and_banner_match_the_agent(tmp_path):
    constants = dump(tmp_path, {})["constants"]
    main = (ROOT / "app_lab" / "microduck_agent" / "python" / "main.py").read_text(encoding="utf-8")
    assert f"PORT = {constants['AGENT_PORT']}" in main
    assert 'print(f"Microduck agent listening on {PORT}")' in main
    assert constants["AGENT_BANNER"] == f"Microduck agent listening on {constants['AGENT_PORT']}"
    server = (ROOT / constants["SERVER_PATH"]).read_text(encoding="utf-8")
    assert f'"--port", type=int, default={constants["CONTROL_PORT"]}' in server
    unit = (ROOT / "app_lab" / "microduck_agent" / "microduck-control.service").read_text(encoding="utf-8")
    assert f"--port {constants['CONTROL_PORT']}" in unit and constants["SERVER_PATH"] in unit


def doc_blocks(heading: str) -> list:
    text = (ROOT / "docs" / "flash.md").read_text(encoding="utf-8")
    section = text.split(f"## {heading}\n", 1)[1].split("\n## ", 1)[0]
    return [line[4:] for line in section.splitlines() if line.startswith("    ")]


@needs_node
def test_commands_match_the_manual_steps_in_the_document(tmp_path):
    out = dump(tmp_path, {"plans": {"install": {"host": "unoq.local"}, "update": {"host": "unoq.local", "mode": "update"},
                                    "computer": {"host": "unoq.local", "where": "computer"}}})
    assert doc_blocks("Manual steps") == commands(out["plans"]["install"])
    update = {step["id"]: step["command"] for step in out["plans"]["update"]["steps"]}
    assert doc_blocks("Updating") == [update[key] for key in ("pull", "stop", "remove", "copy", "start")]
    wrapped = {step["id"]: step["command"] for step in out["plans"]["computer"]["steps"]}
    assert doc_blocks("From your computer instead") == [wrapped["mkdir"]]
    html = (ROOT / "site" / "flash.html").read_text(encoding="utf-8")
    assert "not run on hardware" in html.lower()
    assert "sends nothing anywhere" in html


def test_post_flash_reply_is_what_the_protocol_answers():
    reply = protocol.Controller(protocol.load_calibration()).handle("S", 1234)
    assert reply == "STAT mode=RELAX age_ms=1234 wd=500 q=0.0,42.0,-42.0,0.0,42.0,-42.0"
    assert reply in (ROOT / "docs" / "flash.md").read_text(encoding="utf-8")
    assert reply in (ROOT / "site" / "flash.html").read_text(encoding="utf-8")


def test_page_has_no_secret_fields_and_makes_no_requests():
    html = (ROOT / "site" / "flash.html").read_text(encoding="utf-8")
    script = (ROOT / "site" / "flash.js").read_text(encoding="utf-8")
    assert not re.search(r'type="password"', html)
    assert not re.search(r'<input[^>]*(name|id)="[^"]*(pass|key|token|secret)', html, re.I)
    for needle in ("fetch(", "XMLHttpRequest", "WebSocket", "sendBeacon", "navigator.serial", "navigator.usb", "localStorage", "<form action"):
        assert needle not in script and needle not in html, needle
    for item in ("servo supply is physically disconnected", "on a stand or lying down", "before calibration", "starts relaxed"):
        assert item in html, item


@needs_sh
def test_a_shell_reads_each_command_as_intended(tmp_path):
    out = dump(tmp_path, {"plans": {"install": {"host": "unoq.local", "user": "pi", "repoDir": "src/duck", "appsDir": "Apps"},
                                    "update": {"host": "unoq.local", "mode": "update"}}})
    lines = run_script(tmp_path, commands(out["plans"]["install"]))
    assert lines == [
        "[ssh][pi@unoq.local]",
        "[git][clone][--depth][1][https://github.com/eoinjordan/botbuilder.git][/home/t/src/duck]",
        "[mkdir][-p][/home/t/Apps]",
        "[cp][-R][/home/t/src/duck/app_lab/microduck_agent][/home/t/Apps/microduck_agent]",
        "[arduino-app-cli][app][start][/home/t/Apps/microduck_agent]",
        "[arduino-app-cli][app][logs][/home/t/Apps/microduck_agent]",
        "[nc][-w][2][127.0.0.1][8766]",
        "[python3][/home/t/src/duck/app_lab/microduck_agent/control_server.py][--bind][0.0.0.0][--port][7101]",
    ]
    lines = run_script(tmp_path, commands(out["plans"]["update"]))
    assert "[rm][-rf][/home/t/ArduinoApps/microduck_agent]" in lines
    assert "[git][-C][/home/t/botbuilder][pull][--ff-only][origin][main]" in lines


@needs_sh
def test_ssh_wrapping_delivers_the_same_command_as_one_argument(tmp_path):
    for mode in ("install", "update"):
        out = dump(tmp_path, {"plans": {"session": {"host": "unoq.local", "mode": mode},
                                        "computer": {"host": "unoq.local", "mode": mode, "where": "computer"}}})
        session = [c for c in commands(out["plans"]["session"]) if not c.startswith("ssh ")]
        lines = run_script(tmp_path, commands(out["plans"]["computer"]))
        assert lines == [f"[ssh][arduino@unoq.local][{command}]" for command in session]


@needs_sh
def test_hostile_text_arrives_as_one_plain_argument(tmp_path):
    out = dump(tmp_path, {"quote": HOSTILE + CONTROL})
    quoted, paths = out["quoted"], out["homePaths"]
    assert quoted[len(HOSTILE):] == [None] * len(CONTROL), "control characters must be refused"
    assert paths[len(HOSTILE):] == [None] * len(CONTROL)
    lines = [f"show {q}" for q in quoted[:len(HOSTILE)]] + [f"show {p}" for p in paths[:len(HOSTILE)]]
    lines += [f"ssh x {out['quoted'][i]}" for i in range(len(HOSTILE))]
    result = run_script(tmp_path, lines)
    assert result[:len(HOSTILE)] == [f"[show][{text}]" for text in HOSTILE]
    assert result[len(HOSTILE):2 * len(HOSTILE)] == [f"[show][/home/t/{text}]" for text in HOSTILE]
    assert not any("pwned" in line and line.startswith("[touch]") for line in result)


@needs_node
def test_hostile_input_never_reaches_a_plan(tmp_path):
    plans = {}
    for index, text in enumerate(HOSTILE + CONTROL + ["", "..", "a/../b", "/etc", "a//b", "-x/y"]):
        for field in ("host", "user", "repoDir", "appsDir"):
            plans[f"{field}-{index}"] = {"host": "unoq.local", field: text}
    out = dump(tmp_path, {"plans": plans})["plans"]
    assert all("error" in plan and "steps" not in plan for plan in out.values())


@needs_node
def test_every_configurator_base_resolves(tmp_path):
    """config/bases.json ids, as a recipe link would pass them in ?base=."""
    path = ROOT / "config" / "bases.json"
    if not path.is_file():
        pytest.skip("no config/bases.json on this branch")
    bases = list(json.loads(path.read_text(encoding="utf-8"))["bases"])
    out = dump(tmp_path, {"plans": {base: {"base": base, "host": "unoq.local"} for base in bases}})["plans"]
    assert {base: plan["base"]["key"] for base, plan in out.items()} == {
        "unoq_braccio": "unoq", "pi_servo": "raspberrypi", "hub51515": "lego", "ev3": "lego", "m5_basex_ev3": "m5stack",
        "pi_buildhat_51515": "raspberrypi"}
    assert [base for base, plan in out.items() if plan["written"]] == ["unoq_braccio"]
