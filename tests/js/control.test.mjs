// SPDX-License-Identifier: MIT
import test from "node:test";
import assert from "node:assert/strict";
import { loadSite } from "./load.mjs";

const c = await loadSite("control.js");

const pad = () => ({ id: "Test pad (STANDARD GAMEPAD)", index: 0, connected: true, mapping: "standard", axes: [0, 0, 0, 0],
  buttons: Array.from({ length: 17 }, () => ({ pressed: false, value: 0 })) });
const press = (p, ...indexes) => { for (const i of indexes) p.buttons[i].pressed = true; return p; };
const ROBOT = { max_speed_deg_s: 120, watchdog_ms: 500, watchdog_action: "hold", allow_jump: false, stand_deg: [0, 45, -45, 0, 45, -45],
  limits_deg: [[-52, 90], [-90, 90], [-90, 90], [-90, 52], [-90, 90], [-90, 90]] };
const GAIT = { period_s: 1, roll_amplitude_deg: 8, step_amplitude_deg: 8, lift_deg: 6, step_phase_deg: 90, lead_in_s: 1 };
const BASE = { gait: { forward: [0, 1], turn: [0, 0], params: GAIT }, motions: { stand: { file: "trajectories/stand.csv" } },
  unavailable: { sit: "no sit trajectory in the repository yet", head: "the head is fixed" }, robot: ROBOT };
const FULL = { gait: { forward: [-0.5, 1], turn: [-1, 1], params: GAIT },
  motions: { stand: {}, sit: {}, jump: {} }, unavailable: {}, robot: ROBOT };
const run = (state, intent, now, manifest, options = {}) =>
  c.nextCommand(state, intent, now, c.availability(manifest, options), { gait: manifest.gait, ...options });

test("dead zone: drift, missing and non-finite axes are zero; the rest is rescaled to full range", () => {
  for (const value of [0, 0.19, -0.2, undefined, NaN, Infinity]) assert.equal(c.deadzone(value, 0.2), 0);
  assert.equal(c.deadzone(1, 0.2), 1);
  assert.equal(c.deadzone(-1, 0.2), -1);
  assert.ok(Math.abs(c.deadzone(0.6, 0.2) - 0.5) < 1e-12);
  assert.equal(c.deadzone(3, 0.2), 1);
});

test("pad to intent: nothing without a held shoulder button", () => {
  const p = pad(); p.axes[1] = -1; press(p, 0);
  const idle = c.readPad(p);
  assert.equal(idle.enable, false);
  assert.equal(idle.forward, 0);
  assert.equal(idle.action, null);
  for (const shoulder of [4, 5]) {
    const q = pad(); q.axes[1] = -1; press(q, shoulder);
    assert.equal(c.readPad(q).enable, true);
    assert.equal(c.readPad(q).forward, 1);
  }
});

test("pad to intent: stick directions, scaling and buttons", () => {
  const p = press(pad(), 4); p.axes = [0.6, 0.6, -1, 1];
  const intent = c.readPad(p);
  assert.ok(Math.abs(intent.forward + 0.5) < 1e-12, "stick down is backward");
  assert.ok(Math.abs(intent.turn + 0.5) < 1e-12, "stick right is a right turn");
  assert.equal(intent.pan, -1);
  assert.equal(intent.tilt, -1);
  assert.equal(c.readPad(press(press(pad(), 5), 0)).action, "stand");
  assert.equal(c.readPad(press(press(pad(), 5), 2)).action, "sit");
  assert.equal(c.readPad(press(press(pad(), 5), 3)).action, "jump");
  assert.equal(c.readPad(press(press(pad(), 4), 12)).jog, 1);
  assert.equal(c.readPad(press(press(pad(), 4), 15)).select, 1);
});

test("stop button wins over everything, enable included", () => {
  const p = press(pad(), 1, 4, 0); p.axes[1] = -1;
  const intent = c.readPad(p);
  assert.equal(intent.stop, true);
  assert.equal(intent.enable, false);
  assert.equal(intent.forward, 0);
  assert.equal(run(c.initialState(), intent, 0, BASE).command.type, "stop");
});

test("no pad, or a disconnected pad, is an idle intent", () => {
  for (const p of [null, undefined, { ...pad(), connected: false }]) {
    const intent = c.readPad(p);
    assert.equal(intent.present, false);
    assert.equal(intent.enable, false);
  }
});

test("a pad that appears with enable held or a stick over must rest once first", () => {
  const gate = new c.PadGate();
  const p = press(pad(), 4); p.axes[1] = -1;
  assert.equal(gate.read(p).enable, false);
  p.buttons[4].pressed = false; p.axes[1] = 0;
  gate.read(p);
  p.buttons[4].pressed = true; p.axes[1] = -1;
  assert.equal(gate.read(p).forward, 1);
});

test("pad disconnect is reported as lost and becomes a stop", () => {
  const gate = new c.PadGate();
  const p = pad();
  gate.read(p);
  press(p, 4); p.axes[1] = -1;
  let step = run(c.initialState(), gate.read(p), 0, BASE);
  assert.equal(step.command.type, "walk");
  const lost = gate.read(null);
  assert.equal(lost.lost, true);
  step = run(step.state, lost, 50, BASE);
  assert.deepEqual(step.command, { type: "stop", reason: "controller disconnected" });
  assert.equal(step.state.live, false);
  assert.equal(run(step.state, gate.read(null), 100, BASE).command.type, "idle");
});

test("dead-man: release while moving is one stop, then idle", () => {
  const moving = c.mergeIntents([{ ...c.idleIntent(), present: true, enable: true, forward: 1 }]);
  let step = run(c.initialState(), moving, 0, BASE);
  assert.deepEqual(step.command, { type: "walk", forward: 1, turn: 0 });
  step = run(step.state, { ...moving, enable: false }, 50, BASE);
  assert.deepEqual(step.command, { type: "stop", reason: "enable released" });
  step = run(step.state, { ...moving, enable: false }, 100, BASE);
  assert.equal(step.command.type, "idle");
});

test("after a stop with enable still held, nothing moves until it is released once", () => {
  const moving = { ...c.idleIntent(), present: true, enable: true, forward: 1 };
  let step = run(c.initialState(), { ...moving, stop: true }, 0, BASE);
  assert.equal(step.command.type, "stop");
  step = run(step.state, moving, 50, BASE);
  assert.equal(step.command.type, "idle");
  step = run(step.state, { ...moving, enable: false }, 100, BASE);
  step = run(step.state, moving, 150, BASE);
  assert.equal(step.command.type, "walk");
});

test("walk is scaled and clipped to the manifest's gait ranges", () => {
  const intent = (forward, turn) => ({ ...c.idleIntent(), present: true, enable: true, forward, turn });
  assert.equal(run(c.initialState(), intent(-1, 0), 0, BASE).command.type, "hold", "no backward range: nothing");
  assert.equal(run(c.initialState(), intent(0, 1), 0, BASE).command.type, "hold", "no turn range: nothing");
  assert.deepEqual(run(c.initialState(), intent(0.4, 1), 0, BASE).command, { type: "walk", forward: 0.4, turn: 0 });
  assert.deepEqual(run(c.initialState(), intent(-1, 0.3), 0, FULL).command, { type: "walk", forward: -0.5, turn: 0.3 });
});

test("availability: missing motions are disabled with the manifest's reason", () => {
  const a = c.availability(BASE, { target: "sim" });
  assert.equal(a.forward.enabled, true);
  assert.equal(a.stand.enabled, true);
  assert.equal(a.stop.enabled, true);
  for (const key of ["back", "turn", "sit", "jump", "head"]) {
    assert.equal(a[key].enabled, false, key);
    assert.ok(a[key].reason.length > 10, key);
  }
  assert.equal(a.sit.reason, "no sit trajectory in the repository yet");
  assert.equal(c.availability(FULL, { target: "sim" }).head.enabled, false, "six joints, no head");
});

test("an unavailable action does nothing", () => {
  const sit = { ...c.idleIntent(), present: true, enable: true, action: "sit" };
  assert.equal(run(c.initialState(), sit, 0, BASE).command.type, "hold");
  assert.deepEqual(run(c.initialState(), sit, 0, FULL).command, { type: "motion", name: "sit" });
});

test("jump needs a hold, and on the real target the calibration flag", () => {
  const jump = { ...c.idleIntent(), present: true, enable: true, action: "jump" };
  let step = run(c.initialState(), jump, 1000, FULL, { target: "sim" });
  assert.equal(step.command.type, "hold");
  step = run(step.state, jump, 1700, FULL, { target: "sim" });
  assert.equal(step.command.type, "hold", "0.7 s is not long enough");
  step = run(step.state, jump, 1800, FULL, { target: "sim" });
  assert.deepEqual(step.command, { type: "motion", name: "jump" });
  step = run(c.initialState(), jump, 0, FULL, { target: "sim" });
  step = run(step.state, { ...jump, action: null }, 400, FULL, { target: "sim" });
  step = run(step.state, jump, 900, FULL, { target: "sim" });
  assert.equal(step.command.type, "hold", "releasing restarts the hold");

  const real = c.availability(FULL, { target: "real", jumpEnabled: false });
  assert.equal(real.jump.enabled, false);
  assert.match(real.jump.reason, /allow_jump/);
  assert.match(real.jump.reason, /gears/);
  step = run(c.initialState(), jump, 0, FULL, { target: "real", jumpEnabled: false });
  step = run(step.state, jump, 5000, FULL, { target: "real", jumpEnabled: false });
  assert.equal(step.command.type, "hold");
  assert.equal(c.availability(FULL, { target: "real", jumpEnabled: true }).jump.enabled, true);
});

test("expert mode: select a joint on the press edge, jog only while held", () => {
  const base = { ...c.idleIntent(), present: true, enable: true };
  let step = run(c.initialState(), { ...base, select: 1 }, 0, BASE, { expert: true });
  assert.equal(step.state.joint, 1);
  step = run(step.state, { ...base, select: 1 }, 50, BASE, { expert: true });
  assert.equal(step.state.joint, 1, "held select does not repeat");
  step = run(step.state, { ...base, jog: -1, forward: 1, action: "stand" }, 100, BASE, { expert: true });
  assert.deepEqual(step.command, { type: "jog", joint: 1, dir: -1 });
  assert.equal(run(step.state, base, 150, BASE, { expert: true }).command.type, "hold");
  assert.equal(run(step.state, { ...base, enable: false, jog: 1 }, 150, BASE, { expert: true }).command.type, "stop");
});

test("engine: targets stay inside the soft limits and under the speed limit", () => {
  const engine = new c.MotionEngine(ROBOT, GAIT, {});
  let previous = engine.q.slice();
  for (let i = 0; i < 400; i++) {
    const out = engine.step({ type: "walk", forward: 1, turn: 0 }, 50);
    out.q.forEach((value, k) => {
      assert.ok(value >= ROBOT.limits_deg[k][0] && value <= ROBOT.limits_deg[k][1]);
      assert.ok(Math.abs(value - previous[k]) <= 120 * 0.05 + 1e-9);
    });
    previous = out.q;
  }
  assert.ok(Math.max(...previous.map((v, k) => Math.abs(v - ROBOT.stand_deg[k]))) > 1, "the gait moved the joints");
});

test("engine: jog is slow and stops at the limit", () => {
  const engine = new c.MotionEngine(ROBOT, GAIT, {});
  const first = engine.step({ type: "jog", joint: 0, dir: -1 }, 50).q;
  assert.ok(Math.abs(first[0] + 0.75) < 1e-9, "15 deg/s for 50 ms");
  for (let i = 0; i < 2000; i++) engine.step({ type: "jog", joint: 0, dir: -1 }, 50);
  assert.equal(engine.q[0], -52);
  assert.deepEqual(engine.q.slice(1), ROBOT.stand_deg.slice(1));
});

test("engine: a motion is approached slowly, played once, and reports done", () => {
  const rows = [[0, [0, 20, -20, 0, 20, -20]], [1000, [0, 60, -60, 0, 60, -60]]];
  const engine = new c.MotionEngine(ROBOT, GAIT, { sit: rows });
  let out = engine.step({ type: "motion", name: "sit" }, 50);
  assert.equal(out.phase, "to start");
  assert.ok(Math.abs(out.q[1] - (45 - 45 * 0.05)) < 1e-9, "approach at 45 deg/s");
  let steps = 0;
  while (!out.done && steps++ < 400) out = engine.step({ type: "motion", name: "sit" }, 50);
  assert.ok(out.done);
  assert.ok(Math.abs(out.q[1] - 60) < 0.01);
  assert.equal(engine.step({ type: "hold" }, 50).q, null, "hold sends nothing");
  assert.equal(engine.step({ type: "motion", name: "nope" }, 50).q, null);
});

test("playback: relaxed until E, clamps, limits speed, watchdog holds", () => {
  const p = new c.PlaybackController(ROBOT);
  assert.equal(p.handle("J 0 45 -45 0 45 -45", 0), "ERR DISABLED");
  assert.equal(p.handle("E", 0), "OK");
  assert.equal(p.handle("J 200 45 -45 0 45 -45", 20), "OK CLAMP 1");
  p.tick(40);
  assert.ok(Math.abs(p.current[0] - 2.4) < 1e-9, "120 deg/s is 2.4 deg per tick");
  for (let t = 60; t <= 600; t += 20) p.tick(t);
  assert.equal(p.mode, "HOLD");
  const held = p.current[0];
  p.tick(620);
  assert.equal(p.current[0], held);
  assert.match(p.handle("S", 640), /^STAT mode=HOLD age_ms=620 wd=500 q=/);
  assert.equal(p.handle("J 1e3 0 0 0 0 0", 660), "ERR ARGS");
  assert.equal(p.handle("Q", 0), "ERR UNKNOWN");
});

test("stop sequence: status, then the reported angles as the target", () => {
  const p = new c.PlaybackController(ROBOT);
  const sent = [];
  const send = (line) => { sent.push(line); return p.handle(line, 100); };
  assert.equal(c.stopOn(send).held, false, "relaxed: nothing to hold");
  assert.deepEqual(sent, ["S"]);
  p.handle("E", 0); p.handle("J 30 45 -45 0 45 -45", 0); p.tick(20); p.tick(40);
  sent.length = 0;
  assert.equal(c.stopOn(send).held, true);
  assert.deepEqual(sent, ["S", "J 4.8 45.0 -45.0 0.0 45.0 -45.0"]);
  p.tick(120);
  assert.ok(Math.abs(p.current[0] - 4.8) < 1e-9, "it stays where it was");
});

test("fmt1 matches the firmware's rounding", () => {
  assert.deepEqual([0, -0.04, 0.05, -0.05, 12.34, -45, 99.95].map(c.fmt1), ["0.0", "0.0", "0.1", "-0.1", "12.3", "-45.0", "100.0"]);
  assert.equal(c.formatJoints([0, 45, -45, 0, 45, -45]), "J 0.0 45.0 -45.0 0.0 45.0 -45.0");
});
