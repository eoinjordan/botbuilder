// SPDX-License-Identifier: MIT
// Drives the robot from a game controller, the keyboard or on-screen buttons.
//
// Part 1 is pure and has no DOM: pad state to a command, the motion engine
// that turns a command into six joint targets, and a copy of the firmware's
// control rules for the in-page playback. Node tests import it.
// Part 2 wires the page and runs only in a browser.
//
// deadzone() and the neutral gate follow web/src/input.js of
// unoq-braccio-sketchbot (MIT, see NOTICE). All paths are relative.

export const JOINTS = ["left_hip_roll", "left_hip_pitch", "left_knee", "right_hip_roll", "right_hip_pitch", "right_knee"];
export const JOINT_LABELS = ["Left hip roll", "Left hip pitch", "Left knee", "Right hip roll", "Right hip pitch", "Right knee"];
export const TICK_MS = 20;
// W3C "standard" gamepad mapping.
export const PAD = { stand: 0, stop: 1, sit: 2, jump: 3, enable: [4, 5], jogPlus: 12, jogMinus: 13, jointPrev: 14, jointNext: 15,
  axisTurn: 0, axisForward: 1, axisPan: 2, axisTilt: 3 };
export const SETTINGS = { deadzone: 0.2, jumpHoldMs: 800, sendMs: 50, approachDegS: 45, jogDegS: 15 };
export const CHECKLIST = ["supply", "stand", "calibrated", "switch", "clear"];

// ---------------------------------------------------------------- pad

export function deadzone(value, threshold) {
  if (!Number.isFinite(value) || !Number.isFinite(threshold) || threshold < 0 || threshold >= 1) return 0;
  const magnitude = Math.min(1, Math.abs(value));
  return magnitude <= threshold ? 0 : Math.sign(value) * (magnitude - threshold) / (1 - threshold);
}

export function idleIntent() {
  return { present: false, lost: false, stop: false, enable: false, forward: 0, turn: 0, pan: 0, tilt: 0,
    action: null, jog: 0, select: 0 };
}

// One pad sample to an intent. Stick up is forward, stick left is a left turn.
export function readPad(pad, settings = SETTINGS) {
  const intent = idleIntent();
  if (!pad || !pad.connected) return intent;
  intent.present = true;
  const pressed = (index) => Boolean(pad.buttons && pad.buttons[index] && pad.buttons[index].pressed);
  const axis = (index) => deadzone(pad.axes ? pad.axes[index] : 0, settings.deadzone);
  if (pressed(PAD.stop)) { intent.stop = true; return intent; }
  intent.enable = PAD.enable.some(pressed);
  if (!intent.enable) return intent;
  intent.forward = -axis(PAD.axisForward) || 0;
  intent.turn = -axis(PAD.axisTurn) || 0;
  intent.pan = axis(PAD.axisPan);
  intent.tilt = -axis(PAD.axisTilt) || 0;
  intent.action = pressed(PAD.jump) ? "jump" : pressed(PAD.sit) ? "sit" : pressed(PAD.stand) ? "stand" : null;
  intent.jog = (pressed(PAD.jogPlus) ? 1 : 0) - (pressed(PAD.jogMinus) ? 1 : 0);
  intent.select = (pressed(PAD.jointNext) ? 1 : 0) - (pressed(PAD.jointPrev) ? 1 : 0);
  return intent;
}

// A pad that appears with the enable button held or a stick deflected does
// nothing until it has been seen at rest once. A pad that was there and is
// gone reports lost, which the command step turns into a stop.
export class PadGate {
  constructor() { this.reset(); }
  reset() { this.ready = false; this.identity = null; }
  read(pad, settings = SETTINGS) {
    const intent = readPad(pad, settings);
    const identity = pad && pad.connected ? `${pad.index}:${pad.id}` : null;
    const lost = this.identity !== null && identity !== this.identity;
    if (identity !== this.identity) { this.ready = false; this.identity = identity; }
    if (lost) return { ...idleIntent(), present: Boolean(identity), lost: true };
    if (!identity) return intent;
    const enable = PAD.enable.some((index) => pad.buttons && pad.buttons[index] && pad.buttons[index].pressed);
    const neutral = [0, 1, 2, 3].every((index) => deadzone(pad.axes ? pad.axes[index] : 0, settings.deadzone) === 0);
    if (!enable && neutral && !intent.stop) this.ready = true;
    return this.ready ? intent : { ...idleIntent(), present: true, stop: intent.stop };
  }
}

const clip = (value, low, high) => Math.min(high, Math.max(low, value));

export function mergeIntents(intents) {
  const out = idleIntent();
  for (const intent of intents) {
    out.present = out.present || intent.present;
    out.lost = out.lost || intent.lost;
    out.stop = out.stop || intent.stop;
    out.enable = out.enable || intent.enable;
    out.forward = clip(out.forward + intent.forward, -1, 1);
    out.turn = clip(out.turn + intent.turn, -1, 1);
    out.pan = clip(out.pan + intent.pan, -1, 1);
    out.tilt = clip(out.tilt + intent.tilt, -1, 1);
    out.action = out.action || intent.action;
    out.jog = clip(out.jog + intent.jog, -1, 1);
    out.select = clip(out.select + intent.select, -1, 1);
  }
  return out;
}

// What can be offered, from the motion manifest (data/motions.json).
// options.target is "sim" or "real"; options.jumpEnabled is the flag the
// robot's server read from config/calibration.json.
export function availability(manifest, options = {}) {
  const missing = manifest.unavailable || {};
  const gait = manifest.gait || { forward: [0, 0], turn: [0, 0] };
  const item = (enabled, reason) => ({ enabled, reason: enabled ? "" : reason });
  const out = {
    stop: item(true, ""),
    forward: item(gait.forward[1] > 0, missing.forward || "no forward range in the motion manifest"),
    back: item(gait.forward[0] < 0, missing.back || "no backward range in the motion manifest"),
    turn: item(gait.turn[0] < 0 || gait.turn[1] > 0, missing.turn || "no turn range in the motion manifest"),
    head: item(false, missing.head || "this robot has no head joints"),
  };
  for (const name of ["stand", "sit", "jump"]) {
    out[name] = item(Boolean(manifest.motions && manifest.motions[name]), missing[name] || `no ${name} trajectory in the motion manifest`);
  }
  if (out.jump.enabled && options.target === "real" && !options.jumpEnabled) {
    out.jump = item(false, "off for the real robot until \"allow_jump\": true is set in config/calibration.json; " +
      "landing loads can strip servo gears and crack printed parts");
  }
  return out;
}

export function initialState() {
  return { live: false, latched: false, motion: null, jumpSince: null, lastAction: null, joint: 0, lastSelect: 0 };
}

// The pure step from input to command. Nothing in it is about legs: forward
// and turn are a plain twist, so a target with two driven wheels can take
// the same walk command and turn it into wheel speeds where MotionEngine
// turns it into a gait. Returns the next state and one of:
//   stop   send the stop sequence once; the watchdog then holds
//   idle   nothing is sent (enable not held, or waiting for a release)
//   hold   enable held but nothing asked for: nothing is sent
//   walk   { forward, turn } inside the manifest's gait ranges
//   motion { name } a manifest trajectory
//   jog    { joint, dir } expert mode, one joint
export function nextCommand(state, intent, nowMs, avail, options = {}) {
  const settings = options.settings || SETTINGS;
  const gait = options.gait || { forward: [0, 1], turn: [0, 0] };
  const rest = { ...state, live: false, motion: null, jumpSince: null, lastAction: null };
  // After a stop the enable control must be seen released before anything moves again.
  if (intent.stop) return { state: { ...rest, latched: true }, command: { type: "stop", reason: "stop" } };
  if (intent.lost) return { state: { ...rest, latched: false }, command: { type: "stop", reason: "controller disconnected" } };
  if (!intent.enable) {
    return { state: { ...rest, latched: false },
      command: state.live ? { type: "stop", reason: "enable released" } : { type: "idle", reason: "hold a shoulder button to move" } };
  }
  if (state.latched) return { state, command: { type: "idle", reason: "release the enable control once to continue" } };
  const next = { ...state, live: true };
  if (options.expert) {
    next.motion = null;
    if (intent.select !== 0 && state.lastSelect === 0) next.joint = (state.joint + intent.select + 6) % 6;
    next.lastSelect = intent.select;
    if (intent.jog !== 0) return { state: next, command: { type: "jog", joint: next.joint, dir: intent.jog } };
    return { state: next, command: { type: "hold" } };
  }
  if (intent.action === "jump") {
    if (next.jumpSince === null) next.jumpSince = nowMs;
    if (avail.jump.enabled && next.motion !== "jump" && nowMs - next.jumpSince >= settings.jumpHoldMs) next.motion = "jump";
  } else {
    next.jumpSince = null;
    if (intent.action && intent.action !== state.lastAction && avail[intent.action].enabled) next.motion = intent.action;
  }
  next.lastAction = intent.action;
  const forward = clip(intent.forward, avail.back.enabled ? gait.forward[0] : 0, avail.forward.enabled ? gait.forward[1] : 0);
  const turn = avail.turn.enabled ? clip(intent.turn, gait.turn[0], gait.turn[1]) : 0;
  if (forward !== 0 || turn !== 0) {
    next.motion = null;
    return { state: next, command: { type: "walk", forward, turn } };
  }
  if (next.motion) return { state: next, command: { type: "motion", name: next.motion } };
  return { state: next, command: { type: "hold" } };
}

// ---------------------------------------------------------------- motion

// One decimal, half away from zero, no negative zero: microduck/protocol.py fmt1.
export function fmt1(value) {
  const tenths = Math.floor(Math.abs(value) * 10 + 0.5);
  const sign = value < 0 && tenths ? "-" : "";
  return `${sign}${Math.floor(tenths / 10)}.${tenths % 10}`;
}

export function formatJoints(q) {
  if (q.length !== 6) throw new Error("six joint angles expected");
  return `J ${q.map(fmt1).join(" ")}`;
}

// microduck/gait.py with the step scaled per leg. forward 1, turn 0 and
// ts counted from the end of the lead-in give the committed gait.csv.
export function gaitPose(stand, params, ts, forward, turn) {
  const q = stand.slice();
  if (ts <= 0) return q;
  const ramp = Math.min(1, ts / params.period_s);
  const w = 2 * Math.PI * ts / params.period_s;
  const sway = Math.sin(w);
  const swing = Math.sin(w + params.step_phase_deg * Math.PI / 180);
  const roll = ramp * params.roll_amplitude_deg * sway;
  const left = ramp * params.step_amplitude_deg * clip(forward - turn, -1, 1) * swing;
  const right = ramp * params.step_amplitude_deg * clip(forward + turn, -1, 1) * swing;
  const leftLift = ramp * params.lift_deg * Math.max(0, -sway);
  const rightLift = ramp * params.lift_deg * Math.max(0, sway);
  q[0] += roll; q[3] += roll;
  q[1] += -left + leftLift; q[2] += left - 2 * leftLift;
  q[4] += right + rightLift; q[5] += -right - 2 * rightLift;
  return q;
}

export function parseTrajectory(text) {
  const lines = text.trim().split(/\r?\n/);
  if (lines[0] !== `t_ms,${JOINTS.join(",")}`) throw new Error("trajectory header must be t_ms and the six joint names");
  const rows = lines.slice(1).filter(Boolean).map((line) => {
    const cells = line.split(",").map(Number);
    if (cells.length !== 7 || !cells.every(Number.isFinite)) throw new Error("trajectory rows need seven numbers");
    return [cells[0], cells.slice(1)];
  });
  if (!rows.length || rows.some((row, i) => i && row[0] <= rows[i - 1][0])) throw new Error("trajectory t_ms must increase");
  return rows;
}

export function sampleTrajectory(rows, tMs) {
  if (tMs <= rows[0][0]) return rows[0][1].slice();
  for (let i = 1; i < rows.length; i++) {
    if (tMs <= rows[i][0]) {
      const f = (tMs - rows[i - 1][0]) / (rows[i][0] - rows[i - 1][0]);
      return rows[i][1].map((b, k) => rows[i - 1][1][k] + (b - rows[i - 1][1][k]) * f);
    }
  }
  return rows[rows.length - 1][1].slice();
}

export function clampJoints(q, limits) {
  return q.map((value, i) => clip(value, limits[i][0], limits[i][1]));
}

export function limitStep(from, to, maxStep) {
  return to.map((value, i) => from[i] + clip(value - from[i], -maxStep, maxStep));
}

const farthest = (a, b) => Math.max(...a.map((value, i) => Math.abs(value - b[i])));

// Commands in, joint targets out. Targets never leave the soft limits and
// never move faster than the robot's speed limit; the approach to the start
// of a motion and the jog are slower still.
export class MotionEngine {
  constructor(robot, gait, trajectories = {}, settings = SETTINGS) {
    this.stand = robot.stand_deg.slice();
    this.limits = robot.limits_deg;
    this.maxSpeed = robot.max_speed_deg_s;
    this.gait = gait;
    this.trajectories = trajectories;
    this.settings = settings;
    this.reset(this.stand);
  }

  reset(q) {
    this.q = q.slice();
    this.gaitT = null;
    this.motion = null;
  }

  _approach(goal, dtMs) {
    this.q = limitStep(this.q, clampJoints(goal, this.limits), this.settings.approachDegS * dtMs / 1000);
    return farthest(this.q, clampJoints(goal, this.limits)) < 0.05;
  }

  step(command, dtMs) {
    if (command.type !== "walk") this.gaitT = null;
    if (command.type !== "motion") this.motion = null;
    const full = this.maxSpeed * dtMs / 1000;
    if (command.type === "walk") {
      if (this.gaitT === null) {
        if (!this._approach(this.stand, dtMs)) return { q: this.q.slice(), done: false, phase: "to stand" };
        this.gaitT = 0;
      }
      this.gaitT += dtMs / 1000;
      const goal = gaitPose(this.stand, this.gait, this.gaitT, command.forward, command.turn);
      this.q = limitStep(this.q, clampJoints(goal, this.limits), full);
      return { q: this.q.slice(), done: false, phase: "gait" };
    }
    if (command.type === "motion") {
      const rows = this.trajectories[command.name];
      if (!rows) return { q: null, done: true, phase: "missing" };
      if (!this.motion || this.motion.name !== command.name) this.motion = { name: command.name, t: null };
      if (this.motion.t === null) {
        if (!this._approach(rows[0][1], dtMs)) return { q: this.q.slice(), done: false, phase: "to start" };
        this.motion.t = rows[0][0];
      }
      this.motion.t += dtMs;
      this.q = limitStep(this.q, clampJoints(sampleTrajectory(rows, this.motion.t), this.limits), full);
      const done = this.motion.t >= rows[rows.length - 1][0];
      if (done) this.motion = null;
      return { q: this.q.slice(), done, phase: "play" };
    }
    if (command.type === "jog") {
      const goal = this.q.slice();
      goal[command.joint] += command.dir * this.settings.jogDegS * dtMs / 1000;
      this.q = clampJoints(goal, this.limits);
      return { q: this.q.slice(), done: false, phase: "jog" };
    }
    return { q: null, done: false, phase: command.type };
  }
}

// ---------------------------------------------------------------- playback

const NUMBER = /^[-+]?[0-9]{1,6}(\.[0-9]{0,6})?$/;

// The rules of microduck/protocol.py Controller for the lines this page
// sends (J, E, R, S, W): soft limits, speed limit, watchdog. It moves the
// joints of the 3D view. It is playback of the commands, not physics: there
// is no gravity, no contact and no falling here.
export class PlaybackController {
  constructor(robot) {
    this.limits = robot.limits_deg;
    this.maxSpeed = robot.max_speed_deg_s;
    this.watchdogMs = robot.watchdog_ms;
    this.watchdogRelax = robot.watchdog_action === "relax";
    this.mode = "RELAX";
    this.current = robot.stand_deg.slice();
    this.target = robot.stand_deg.slice();
    this.lastCmdMs = 0;
    this.armed = false;
  }

  tick(nowMs) {
    if (this.mode === "RUN" && this.armed && nowMs - this.lastCmdMs > this.watchdogMs) {
      if (this.watchdogRelax) this.mode = "RELAX";
      else { this.mode = "HOLD"; this.target = this.current.slice(); }
      this.armed = false;
    }
    if (this.mode !== "RUN") return;
    this.current = limitStep(this.current, this.target, this.maxSpeed * TICK_MS / 1000);
  }

  handle(line, nowMs) {
    const parts = line.trim().split(/\s+/).filter(Boolean);
    if (!parts.length) return "ERR EMPTY";
    const [cmd, ...args] = parts;
    const arity = { J: 6, E: 0, R: 0, S: 0, W: 2, C: 1, N: 1, Z: 0, X: 0 };
    if (!(cmd in arity)) return "ERR UNKNOWN";
    if (args.length !== arity[cmd]) return "ERR ARGS";
    if (cmd === "J") {
      if (!args.every((a) => NUMBER.test(a))) return "ERR ARGS";
      const values = args.map(Number);
      if (values.some((v) => Math.abs(v) > 1000)) return "ERR ARGS";
      if (this.mode === "RELAX") return "ERR DISABLED";
      const clamped = clampJoints(values, this.limits);
      const count = values.filter((v, i) => v !== clamped[i]).length;
      this.target = clamped;
      this.mode = "RUN"; this.armed = true; this.lastCmdMs = nowMs;
      return count ? `OK CLAMP ${count}` : "OK";
    }
    if (cmd === "E") {
      if (this.mode === "RELAX") { this.target = this.current.slice(); this.mode = "RUN"; this.armed = false; }
      return "OK";
    }
    if (cmd === "R") { this.mode = "RELAX"; this.armed = false; return "OK"; }
    if (cmd === "S") {
      return `STAT mode=${this.mode} age_ms=${nowMs - this.lastCmdMs} wd=${this.watchdogMs} q=${this.current.map(fmt1).join(",")}`;
    }
    if (cmd === "W") {
      if (!/^[0-9]{1,6}$/.test(args[0]) || !["hold", "relax"].includes(args[1])) return "ERR ARGS";
      const value = Number(args[0]);
      if (value < 100 || value > 10000) return "ERR ARGS";
      this.watchdogMs = value; this.watchdogRelax = args[1] === "relax";
      return "OK";
    }
    return "ERR PLAYBACK";   // calibration lines are not part of the playback
  }
}

export function parseStatus(reply) {
  const match = /^STAT mode=(\S+) age_ms=(-?\d+) wd=(\d+) q=(\S+)$/.exec(reply.trim());
  if (!match) throw new Error(`unexpected status reply: ${reply}`);
  const q = match[4].split(",").map(Number);
  if (q.length !== 6 || !q.every(Number.isFinite)) throw new Error("status did not carry six joint angles");
  return { mode: match[1], age_ms: Number(match[2]), wd: Number(match[3]), q };
}

// The stop sequence, the same one the robot's server sends: ask for the
// status and, if the board is running, command the angles it reports.
export function stopOn(send) {
  const status = parseStatus(send("S"));
  if (status.mode !== "RUN") return { held: false, status };
  return { held: send(formatJoints(status.q)).startsWith("OK"), status };
}

// ---------------------------------------------------------------- page

const COLORS = { print: 0xecc878, servo: 0x3c424a, horn: 0xe1e4e6, board: 0x14786e, shield: 0x285aa0 };

// The robot as site/app.js draws it: links, boxes and cylinders from
// data/model.json, one hinge per joint. Returns null if three.js or WebGL
// is not available; the joint table still shows the pose.
async function makeViewer(canvas, model) {
  let THREE;
  try { THREE = await import("three"); } catch (error) { return null; }
  let renderer;
  try { renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true }); } catch (error) { return null; }
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  const scene = new THREE.Scene();
  scene.add(new THREE.HemisphereLight(0xffffff, 0x8a9a94, 1.6));
  const sun = new THREE.DirectionalLight(0xffffff, 1.4);
  sun.position.set(3, 6, 4);
  scene.add(sun);
  const camera = new THREE.PerspectiveCamera(35, 1, 0.1, 100);
  const root = new THREE.Group();
  root.rotation.x = -Math.PI / 2;
  root.scale.setScalar(0.01);
  scene.add(root);
  scene.add(new THREE.GridHelper(8, 16, 0x9fb5ab, 0xd6e3dc));
  const groups = {};
  const hinges = {};
  for (const link of model.links) {
    const group = new THREE.Group();
    groups[link.name] = group;
    if (link.parent) {
      group.position.fromArray(link.origin_mm);
      groups[link.parent].add(group);
      hinges[link.joint] = { group, axis: new THREE.Vector3().fromArray(link.axis) };
    } else {
      root.add(group);
    }
    for (const shape of link.shapes) {
      const material = new THREE.MeshStandardMaterial({ color: COLORS[shape.kind], roughness: 0.75, metalness: 0.05 });
      let mesh;
      if (shape.type === "box") {
        const size = shape.max.map((v, i) => v - shape.min[i]);
        mesh = new THREE.Mesh(new THREE.BoxGeometry(size[0], size[1], size[2]), material);
        mesh.position.set((shape.min[0] + shape.max[0]) / 2, (shape.min[1] + shape.max[1]) / 2, (shape.min[2] + shape.max[2]) / 2);
      } else {
        const a = new THREE.Vector3().fromArray(shape.from);
        const b = new THREE.Vector3().fromArray(shape.to);
        mesh = new THREE.Mesh(new THREE.CylinderGeometry(shape.radius, shape.radius, a.distanceTo(b), 24), material);
        mesh.position.copy(a).add(b).multiplyScalar(0.5);
        mesh.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), b.clone().sub(a).normalize());
      }
      group.add(mesh);
    }
  }
  const box = new THREE.Box3();
  const orbit = { azimuth: 0.9, elevation: 0.28, distance: 9.5, target: new THREE.Vector3(0.5, 1.5, 0) };
  function draw() {
    const width = canvas.clientWidth;
    const height = canvas.clientHeight;
    if (!width || !height) return;
    if (canvas.width !== Math.floor(width * renderer.getPixelRatio()) || canvas.height !== Math.floor(height * renderer.getPixelRatio())) {
      renderer.setSize(width, height, false);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
    }
    const c = Math.cos(orbit.elevation);
    camera.position.set(orbit.target.x + orbit.distance * c * Math.sin(orbit.azimuth),
      orbit.target.y + orbit.distance * Math.sin(orbit.elevation),
      orbit.target.z + orbit.distance * c * Math.cos(orbit.azimuth));
    camera.lookAt(orbit.target);
    renderer.render(scene, camera);
  }
  let drag = null;
  canvas.addEventListener("pointerdown", (event) => { drag = { x: event.clientX, y: event.clientY }; canvas.setPointerCapture(event.pointerId); });
  canvas.addEventListener("pointerup", () => { drag = null; });
  canvas.addEventListener("pointermove", (event) => {
    if (!drag) return;
    orbit.azimuth -= (event.clientX - drag.x) * 0.008;
    orbit.elevation = clip(orbit.elevation + (event.clientY - drag.y) * 0.006, -0.2, 1.4);
    drag = { x: event.clientX, y: event.clientY };
    draw();
  });
  window.addEventListener("resize", draw);
  return {
    setPose(q) {
      JOINTS.forEach((name, i) => hinges[name].group.quaternion.setFromAxisAngle(hinges[name].axis, q[i] * Math.PI / 180));
      // The lowest point rests on the grid: the view has no physics.
      root.position.y = 0;
      root.updateMatrixWorld(true);
      box.setFromObject(root);
      root.position.y = -box.min.y;
      draw();
    },
  };
}

async function getJson(path, timeoutMs = 4000) {
  const abort = new AbortController();
  const timer = setTimeout(() => abort.abort(), timeoutMs);
  try {
    const response = await fetch(path, { signal: abort.signal, cache: "no-store" });
    if (!response.ok) throw new Error(`${path}: ${response.status}`);
    return await response.json();
  } finally { clearTimeout(timer); }
}

async function start() {
  const byId = (id) => document.getElementById(id);
  const say = (id, text) => { byId(id).textContent = text; };
  let manifest;
  let model;
  const trajectories = {};
  try {
    [manifest, model] = await Promise.all([getJson("./data/motions.json"), getJson("./data/model.json")]);
    for (const [name, entry] of Object.entries(manifest.motions)) {
      const response = await fetch(`./data/${entry.file}`);
      if (!response.ok) throw new Error(`${entry.file}: ${response.status}`);
      trajectories[name] = parseTrajectory(await response.text());
    }
  } catch (error) {
    say("message", `Could not load the robot data: ${error.message}`);
    return;
  }
  const robot = manifest.robot;
  const engine = new MotionEngine(robot, manifest.gait.params, trajectories);
  const playback = new PlaybackController(robot);
  const gate = new PadGate();
  const started = performance.now();
  const now = () => Math.round(performance.now() - started);

  // Is this page served by the robot's own server? Only then is there an API.
  let board = null;
  try {
    const state = await getJson("./api/state", 2500);
    if (state && state.microduck_control === 1) board = state;
  } catch (error) { board = null; }

  const page = { target: "sim", state: initialState(), command: { type: "idle" }, token: null, busy: false, sent: 0,
    lastLine: "", lastReply: "", stops: 0, stopReason: "", checked: false, shown: robot.stand_deg.slice(), log: [] };
  const viewer = await makeViewer(byId("view"), model);
  if (!viewer) say("view-note", "The 3D view needs three.js from the CDN and WebGL, which are not available here. The joint table shows the same pose.");

  function log(line, reply) {
    page.lastLine = line; page.lastReply = reply;
    page.log.push(`${line}  ->  ${reply}`);
    if (page.log.length > 8) page.log.shift();
    say("log", page.log.join("\n"));
  }

  let drawn = "";
  function show(q) {
    const key = q.map(fmt1).join(",");
    if (key === drawn) return;
    drawn = key;
    page.shown = q.slice();
    if (viewer) viewer.setPose(q);
    q.forEach((value, i) => {
      say(`q-${i}`, fmt1(value));
      const span = robot.limits_deg[i][1] - robot.limits_deg[i][0];
      byId(`bar-${i}`).style.width = `${clip((value - robot.limits_deg[i][0]) / span, 0, 1) * 100}%`;
    });
  }

  // ---- joint table, actions, pad view ----
  const table = byId("joints");
  JOINT_LABELS.forEach((label, i) => {
    const row = document.createElement("tr");
    row.innerHTML = `<td></td><td id="q-${i}" class="num"></td><td class="num"></td><td><span class="meter"><span id="bar-${i}"></span></span></td>`;
    row.children[0].textContent = label;
    row.children[2].textContent = `${robot.limits_deg[i][0]} to ${robot.limits_deg[i][1]}`;
    table.append(row);
    const option = document.createElement("option");
    option.value = String(i); option.textContent = label;
    byId("jog-joint").append(option);
  });
  const padAxes = ["Left stick x (turn)", "Left stick y (walk)", "Right stick x (head pan)", "Right stick y (head tilt)"].map((label, i) => {
    const row = document.createElement("div");
    row.className = "axis";
    row.innerHTML = `<span></span><span class="meter mid"><span id="axis-${i}"></span></span>`;
    row.children[0].textContent = label;
    byId("pad-axes").append(row);
    return row;
  });
  const padNames = { 0: "A stand", 1: "B stop", 2: "X sit", 3: "Y jump", 4: "LB enable", 5: "RB enable", 12: "Up jog +", 13: "Down jog -", 14: "Left joint", 15: "Right joint" };
  for (const [index, label] of Object.entries(padNames)) {
    const chip = document.createElement("span");
    chip.className = "chip"; chip.id = `pad-button-${index}`; chip.textContent = label;
    byId("pad-buttons").append(chip);
  }

  function avail() {
    return availability(manifest, { target: page.target, jumpEnabled: Boolean(board && board.jump_enabled) });
  }

  function renderAvailability() {
    const a = avail();
    const rows = [["forward", "Walk forward"], ["back", "Walk back"], ["turn", "Turn"], ["stand", "Stand"], ["sit", "Sit"],
      ["jump", "Jump (hold)"], ["head", "Head pan and tilt"], ["stop", "Stop"]];
    const list = byId("actions");
    list.textContent = "";
    for (const [key, label] of rows) {
      const item = document.createElement("li");
      item.className = a[key].enabled ? "ok" : "fit";
      const name = document.createElement("b");
      name.textContent = a[key].enabled ? "available" : "disabled";
      item.append(name, document.createTextNode(a[key].enabled ? label : `${label}: ${a[key].reason}`));
      list.append(item);
    }
    const expert = byId("expert").checked;
    const usable = { forward: a.forward, back: a.back, left: a.turn, right: a.turn, stand: a.stand, sit: a.sit, jump: a.jump };
    for (const button of document.querySelectorAll("[data-hold]")) {
      const key = button.dataset.hold;
      const jog = key.startsWith("jog");
      const state = jog ? { enabled: expert, reason: "expert mode is off" } : usable[key];
      const ready = page.target === "sim" || Boolean(page.token);
      button.disabled = !state.enabled || !ready || (!jog && expert);
      button.title = !state.enabled ? state.reason : !ready ? "arm the real robot first" : (!jog && expert) ? "expert mode is on" : "";
    }
    byId("jog-joint").disabled = !expert;
  }

  // ---- targets ----
  function simSend(line) {
    const reply = playback.handle(line, now());
    log(line, reply);
    return reply;
  }

  async function post(path, body) {
    const response = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    let payload = {};
    try { payload = await response.json(); } catch (error) { payload = {}; }
    return { status: response.status, payload };
  }

  function sendTarget(q, command) {
    const line = formatJoints(q);
    if (page.target === "sim") {
      if (playback.mode === "RELAX") simSend("E");
      if (simSend(line).startsWith("OK")) page.sent += 1;
      return;
    }
    if (!page.token || page.busy) return;
    page.busy = true;
    const motion = command.type === "motion" ? command.name : command.type;
    post("./api/joints", { token: page.token, held: true, q, motion }).then(({ status, payload }) => {
      page.busy = false;
      if (status === 200) { page.sent += 1; log(line, payload.reply); show(payload.q); return; }
      if (status === 409) return;            // rate limited or busy: nothing was queued
      log(line, `refused: ${payload.error || status}`);
      stopNow(payload.error || "the robot's server refused the move");
    }).catch(() => { page.busy = false; stopNow("connection to the robot's server lost"); });
  }

  // Stop is always available: it ends the motion here, tells the target to
  // hold where it is, and (real robot) gives up the armed session.
  function stopNow(reason) {
    const wasLive = page.state.live;
    page.state = { ...initialState(), joint: page.state.joint, latched: true };
    page.command = { type: "stop", reason };
    page.stops += 1; page.stopReason = reason;
    releasePointer();
    if (page.target === "sim") {
      const result = stopOn(simSend);
      engine.reset(result.status.q);
    } else {
      const hadToken = Boolean(page.token);
      page.token = null;
      if (hadToken || wasLive) {
        fetch("./api/stop", { method: "POST", keepalive: true }).then(() => log("stop", "sent; the watchdog holds")).catch(() => log("stop", "could not reach the server; the watchdog holds"));
      }
      engine.reset(page.shown);
    }
    say("message", `Stopped: ${reason}.`);
    renderAvailability(); renderReal();
  }

  // ---- real target ----
  function renderReal() {
    const real = byId("target-real");
    if (!board) {
      real.disabled = true;
      say("real-reason", location.protocol === "https:"
        ? "Not reachable from this page. An https page cannot call http or ws on your network, and no page can open a TCP socket. Run the robot's own server and open the page it serves; see below."
        : "Not reachable from this page: it is not served by the robot's server. Run app_lab/microduck_agent/control_server.py and open the page it serves; see below.");
      byId("real-panel").hidden = true;
      return;
    }
    real.disabled = false;
    say("real-reason", `This page is served by the robot's server (robot socket ${board.target}${board.hardware ? ", hardware" : ", this machine"}).`);
    byId("real-panel").hidden = page.target !== "real";
    const status = board.robot.connected ? `mode ${board.robot.status.mode}, watchdog ${board.robot.status.wd} ms` : `not connected: ${board.robot.error}`;
    say("real-status", `Robot: ${status}. Motion ${board.motion_enabled ? "allowed by the server" : "disabled on the server (start it with --allow-motion)"}. ` +
      `Session ${page.token ? "armed" : "not armed"}.`);
    byId("arm").disabled = !board.motion_enabled || !board.robot.connected || Boolean(page.token);
    byId("relax").disabled = !board.motion_enabled || !board.robot.connected;
  }

  async function pollBoard() {
    if (!board || page.target !== "real" || document.hidden) return;
    try {
      board = await getJson("./api/state", 2500);
      if (page.token && !board.armed) { page.token = null; say("message", "The session is no longer armed."); }
      if (board.robot.connected && !page.state.live) { show(board.robot.status.q); engine.reset(board.robot.status.q); }
    } catch (error) {
      if (page.token || page.state.live) stopNow("connection to the robot's server lost");
      board = { ...board, robot: { connected: false, status: null, error: "server not answering" } };
    }
    renderReal(); renderAvailability();
  }

  const preflight = byId("preflight");
  const boxes = [...preflight.querySelectorAll("input[type=checkbox]")];
  const allTicked = () => boxes.every((box) => box.checked);
  boxes.forEach((box) => box.addEventListener("change", () => { byId("confirm-arm").disabled = !allTicked(); }));
  byId("arm").addEventListener("click", () => {
    byId("confirm-arm").disabled = !allTicked();
    if (typeof preflight.showModal === "function") preflight.showModal(); else preflight.setAttribute("open", "");
  });
  byId("cancel-arm").addEventListener("click", () => preflight.close());
  byId("confirm-arm").addEventListener("click", async () => {
    if (!allTicked()) return;
    preflight.close();
    try {
      const { status, payload } = await post("./api/arm", { confirmed: true, checklist: boxes.map((box) => box.dataset.key) });
      if (status !== 200) throw new Error(payload.error || `refused (${status})`);
      page.token = payload.token; page.checked = true;
      page.state = { ...initialState(), latched: true };
      show(payload.status.q); engine.reset(payload.status.q);
      log("arm", `armed, mode ${payload.status.mode}`);
      say("message", "Armed. Hold a shoulder button, Shift or an on-screen button to move. Escape stops.");
    } catch (error) { say("message", `Not armed: ${error.message}`); }
    renderReal(); renderAvailability();
  });
  byId("relax").addEventListener("click", async () => {
    if (!window.confirm("Relax stops all servo pulses. A standing robot falls. Is the robot supported?")) return;
    page.token = null;
    try {
      const { payload } = await post("./api/relax", { confirmed: true });
      log("R", payload.reply || payload.error || "");
    } catch (error) { log("R", "could not reach the server"); }
    pollBoard();
  });

  function setTarget(target) {
    if (page.state.live || page.token) stopNow("target changed");
    page.target = target === "real" && board ? "real" : "sim";
    byId(page.target === "real" ? "target-real" : "target-sim").checked = true;
    page.state = initialState();
    say("target-label", page.target === "sim"
      ? "Simulator: playback of the joint commands in this page. Not physics: nothing falls or slips here."
      : "Real robot through the robot's server. Not run on hardware: this path has only been tested against the virtual robot.");
    if (page.target === "sim") { engine.reset(playback.current); show(playback.current); } else pollBoard();
    renderReal(); renderAvailability();
  }
  byId("target-sim").addEventListener("change", () => setTarget("sim"));
  byId("target-real").addEventListener("change", () => setTarget("real"));

  // ---- keyboard and on-screen input ----
  const keys = new Set();
  let pointer = idleIntent();
  function releasePointer() {
    pointer = idleIntent();
    for (const button of document.querySelectorAll(".holding")) button.classList.remove("holding");
  }
  const HOLDS = { forward: { forward: 1 }, back: { forward: -1 }, left: { turn: 1 }, right: { turn: -1 }, stand: { action: "stand" },
    sit: { action: "sit" }, jump: { action: "jump" }, "jog-minus": { jog: -1 }, "jog-plus": { jog: 1 } };
  for (const button of document.querySelectorAll("[data-hold]")) {
    const press = () => { pointer = { ...idleIntent(), present: true, enable: true, ...HOLDS[button.dataset.hold] }; button.classList.add("holding"); };
    button.addEventListener("pointerdown", (event) => {
      if (button.disabled || event.button !== 0) return;
      event.preventDefault(); button.setPointerCapture(event.pointerId); press();
    });
    for (const name of ["pointerup", "pointercancel", "lostpointercapture", "blur"]) button.addEventListener(name, releasePointer);
    button.addEventListener("keydown", (event) => {
      if (![" ", "Enter"].includes(event.key) || event.repeat || button.disabled) return;
      event.preventDefault(); press();
    });
    button.addEventListener("keyup", (event) => { if ([" ", "Enter"].includes(event.key)) releasePointer(); });
    button.addEventListener("contextmenu", (event) => event.preventDefault());
  }
  byId("stop").addEventListener("click", () => stopNow("stop button"));
  byId("expert").addEventListener("change", () => { if (page.state.live) stopNow("mode changed"); renderAvailability(); });
  byId("jog-joint").addEventListener("change", () => { page.state = { ...page.state, joint: Number(byId("jog-joint").value) }; });

  const typing = (event) => ["INPUT", "SELECT", "TEXTAREA"].includes(event.target.tagName) && event.target.type !== "checkbox" && event.target.type !== "radio";
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") { stopNow("Escape key"); return; }
    if (typing(event) || preflight.open) return;
    keys.add(event.code);
    if (event.shiftKey && event.code.startsWith("Arrow")) event.preventDefault();
  });
  document.addEventListener("keyup", (event) => { keys.delete(event.code); });
  function keyIntent() {
    const intent = idleIntent();
    if (!keys.size) return intent;
    const down = (...names) => names.some((name) => keys.has(name));
    intent.present = true;
    // Key positions (event.code), so the layout and the Shift state do not matter.
    intent.enable = down("ShiftLeft", "ShiftRight");
    intent.forward = (down("KeyW", "ArrowUp") ? 1 : 0) - (down("KeyS", "ArrowDown") ? 1 : 0);
    intent.turn = (down("KeyA", "ArrowLeft") ? 1 : 0) - (down("KeyD", "ArrowRight") ? 1 : 0);
    intent.action = down("Digit3") ? "jump" : down("Digit2") ? "sit" : down("Digit1") ? "stand" : null;
    intent.jog = (down("Equal") ? 1 : 0) - (down("Minus") ? 1 : 0);
    intent.select = (down("BracketRight") ? 1 : 0) - (down("BracketLeft") ? 1 : 0);
    return intent;
  }

  // Leaving the page, hiding the tab, losing focus or losing the pad stops.
  const leave = (reason) => { keys.clear(); if (page.state.live || page.token) stopNow(reason); };
  document.addEventListener("visibilitychange", () => { if (document.hidden) leave("tab hidden"); });
  window.addEventListener("pagehide", () => leave("page closed"));
  window.addEventListener("blur", () => leave("window lost focus"));
  window.addEventListener("gamepaddisconnected", () => leave("controller disconnected"));
  window.addEventListener("gamepadconnected", () => gate.reset());

  // ---- loops ----
  function readPads() {
    let pads = [];
    try { pads = [...(navigator.getGamepads ? navigator.getGamepads() : [])].filter((pad) => pad && pad.connected); } catch (error) { pads = []; }
    const pad = pads.find((item) => item.mapping === "standard") || pads[0] || null;
    say("pad-name", pad ? `${pad.id}${pad.mapping === "standard" ? "" : " (not the standard mapping: buttons may differ)"}`
      : (navigator.getGamepads ? "No controller seen. Pair it in the operating system, then press any button on it." : "This browser has no Gamepad API. Use the keyboard or the buttons."));
    for (let i = 0; i < 4; i++) {
      const value = pad && Number.isFinite(pad.axes[i]) ? pad.axes[i] : 0;
      byId(`axis-${i}`).style.left = `${50 + clip(value, -1, 1) * 46}%`;
    }
    for (const index of Object.keys(padNames)) {
      byId(`pad-button-${index}`).classList.toggle("on", Boolean(pad && pad.buttons[index] && pad.buttons[index].pressed));
    }
    return pad;
  }

  let last = now();
  function tick() {
    const t = now();
    const dt = clip(t - last, 1, 200);
    last = t;
    const pad = readPads();
    const intent = document.hidden ? { ...idleIntent(), stop: true } : mergeIntents([gate.read(pad), keyIntent(), pointer]);
    if (page.target === "real" && !page.token && !intent.stop) {
      page.command = { type: "idle", reason: "arm the real robot first" };
    } else {
      const expert = byId("expert").checked;
      const step = nextCommand(page.state, intent, t, avail(), { gait: manifest.gait, expert });
      if (step.command.type === "stop") {
        // Once per stop: a held stop button does not repeat the sequence.
        if (page.command.type !== "stop") stopNow(step.command.reason === "stop" ? "stop pressed" : step.command.reason);
        page.state = step.state;
      } else {
        page.state = step.state;
        page.command = step.command;
        const result = engine.step(step.command, dt);
        if (result.q) sendTarget(result.q, step.command);
        if (result.done) page.state = { ...page.state, motion: null };
        if (expert && Number(byId("jog-joint").value) !== page.state.joint) byId("jog-joint").value = String(page.state.joint);
      }
    }
    const c = page.command;
    say("command", c.type === "walk" ? `walk forward ${c.forward.toFixed(2)} turn ${c.turn.toFixed(2)}`
      : c.type === "motion" ? `motion ${c.name}` : c.type === "jog" ? `jog ${JOINT_LABELS[c.joint]} ${c.dir > 0 ? "+" : "-"}`
        : c.reason ? `${c.type}: ${c.reason}` : c.type);
    byId("live").classList.toggle("on", page.state.live);
    say("live", page.state.live ? "enabled" : "not enabled");
    if (intent.pan !== 0 || intent.tilt !== 0) say("message", `Head: ${avail().head.reason}.`);
  }

  setInterval(tick, SETTINGS.sendMs);
  setInterval(() => {
    playback.tick(now());
    if (page.target === "sim") { show(playback.current); say("sim-mode", playback.mode); }
  }, TICK_MS);
  setInterval(pollBoard, 1000);

  window.microduckControl = {
    snapshot: () => ({ target: page.target, board: Boolean(board), live: page.state.live, command: page.command, sent: page.sent,
      stops: page.stops, stopReason: page.stopReason, lastLine: page.lastLine, lastReply: page.lastReply, armed: Boolean(page.token),
      mode: playback.mode, q: playback.current.slice(), shown: page.shown.slice(), viewer: Boolean(viewer), availability: avail(),
      realDisabled: byId("target-real").disabled }),
    stop: stopNow,
  };
  setTarget("sim");
  say("message", "Ready. Hold a shoulder button on the controller, or Shift, or an on-screen button, to move.");
  document.documentElement.dataset.ready = "1";
}

if (typeof document !== "undefined") start();
