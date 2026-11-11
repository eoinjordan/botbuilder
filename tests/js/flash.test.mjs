// SPDX-License-Identifier: MIT
import test from "node:test";
import assert from "node:assert/strict";
import { loadSite } from "./load.mjs";

const flash = await loadSite("flash.js");
const HOSTILE = ["a'b", "'; rm -rf ~; '", "x; reboot", "`id`", "$(id)", "${HOME}", "a\nb", "a\rb", "-rf", "--help",
  "a b", "a|b", "a&b", "a>b", "a\\b", "\"x\"", "~root", "*", "a\u0000b", "../..", "a/../b", "/etc/passwd", ""];

test("shellQuote wraps in single quotes and escapes the single quote", () => {
  assert.equal(flash.shellQuote("plain"), "'plain'");
  assert.equal(flash.shellQuote("a'b"), "'a'\\''b'");
  assert.equal(flash.shellQuote("$(id) `id` ; x"), "'$(id) `id` ; x'");
  assert.equal(flash.shellQuote(""), "''");
});

test("shellQuote refuses control characters, so no newline can split a command", () => {
  for (const text of ["a\nb", "a\rb", "a\u0000b", "a\tb", "a\u001bb", "a\u007fb"]) assert.throws(() => flash.shellQuote(text));
});

test("every hostile value is refused as host, user and path", () => {
  for (const value of HOSTILE) {
    assert.throws(() => flash.validHost(value), undefined, `host ${JSON.stringify(value)}`);
    assert.throws(() => flash.validUser(value), undefined, `user ${JSON.stringify(value)}`);
    assert.throws(() => flash.validHomePath(value), undefined, `path ${JSON.stringify(value)}`);
    for (const field of ["host", "user", "repoDir", "appsDir"]) {
      assert.throws(() => flash.flashPlan({ host: "unoq.local", [field]: value }), undefined, `${field} ${JSON.stringify(value)}`);
    }
  }
});

test("ordinary values are accepted", () => {
  for (const host of ["unoq.local", "UNOQ.local", "192.168.1.42", "unoq", "fe80::1", "my-board.lan"]) flash.validHost(host);
  for (const host of ["-x.local", "a..b", "a_b", "user@host", "host:22", "[::1]", "a.-b"]) assert.throws(() => flash.validHost(host), undefined, host);
  for (const user of ["arduino", "pi", "_svc", "eoin-j"]) flash.validUser(user);
  for (const user of ["Root", "-x", "a b", "0day", "a".repeat(33)]) assert.throws(() => flash.validUser(user), undefined, user);
  for (const path of ["ArduinoApps", "src/microduck", "a.b_c-d/e"]) flash.validHomePath(path);
});

test("install plan: one command per step, typed values quoted, nothing else in the command", () => {
  const plan = flash.flashPlan({ host: "unoq.local" });
  assert.deepEqual(plan.steps.map((step) => step.id), ["ssh", "clone", "mkdir", "copy", "start", "logs", "status", "control"]);
  assert.equal(plan.steps[0].command, "ssh 'arduino@unoq.local'");
  assert.equal(plan.steps[0].where, "computer");
  for (const step of plan.steps) {
    assert.ok(!step.command.includes("\n"), step.id);
    assert.ok(!/&&|;|\|\|/.test(step.command), `${step.id} is one command`);
  }
  assert.equal(plan.steps.find((step) => step.id === "start").command, "arduino-app-cli app start \"$HOME\"/'ArduinoApps/microduck_agent'");
});

test("update plan stops, removes only the app copy, copies and starts again", () => {
  const plan = flash.flashPlan({ host: "10.0.0.5", mode: "update", appsDir: "apps/lab" });
  assert.deepEqual(plan.steps.map((step) => step.id), ["ssh", "pull", "stop", "remove", "copy", "start", "logs", "status", "control"]);
  assert.equal(plan.steps.find((step) => step.id === "remove").command, "rm -rf \"$HOME\"/'apps/lab/microduck_agent'");
});

test("computer mode wraps each board command in one quoted ssh argument", () => {
  const plan = flash.flashPlan({ host: "unoq.local", user: "pi", where: "computer" });
  assert.ok(!plan.steps.some((step) => step.id === "ssh"));
  for (const step of plan.steps) assert.ok(step.command.startsWith("ssh 'pi@unoq.local' '"), step.command);
});

test("no command asks for or carries a password, key or token", () => {
  const text = [flash.flashPlan({ host: "h" }), flash.flashPlan({ host: "h", mode: "update", where: "computer" })]
    .flatMap((plan) => plan.steps.map((step) => step.command)).join(" | ");
  for (const needle of ["sshpass", "password", "passwd", " -i ", "token", "curl", "wget", "sudo"]) assert.ok(!text.toLowerCase().includes(needle), needle);
});

test("base: only the UNO Q has steps; the others say not written and give no command", () => {
  for (const base of [undefined, "", "unoq", "UNO-Q", "arduino_uno_q", "arduino-unoq"]) assert.equal(flash.resolveBase(base).key, "unoq", String(base));
  const cases = { "esp-eye": "espeye", "ESP_EYE": "espeye", "esp32-cam": "esp32cam", "ESP32_CAM_AI_THINKER": "esp32cam", "raspberry-pi-5": "raspberrypi", rpi: "raspberrypi",
    "lego-spike": "lego", ev3: "lego", "m5stack-core2": "m5stack", m5stack_nxt: "m5stack", "something else": "other", "<script>": "other" };
  for (const [base, key] of Object.entries(cases)) {
    assert.equal(flash.resolveBase(base).key, key, base);
    const plan = flash.flashPlan({ base, host: "unoq.local" });
    assert.equal(plan.written, false);
    assert.deepEqual(plan.steps, []);
    assert.match(plan.message, /not written/);
  }
  assert.match(flash.BASES.esp32cam.note, /Arduino IDE/);
  // The camera board has a route, by hand: the note gives it and names where the stream is.
  assert.match(flash.BASES.espeye.note, /Arduino IDE/);
  assert.match(flash.BASES.espeye.note, /esp_eye_camera/);
  assert.match(flash.BASES.espeye.note, /esp-eye\.local\/stream/);
});
