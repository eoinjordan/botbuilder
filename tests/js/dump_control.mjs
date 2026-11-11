// SPDX-License-Identifier: MIT
// For the Python tests: runs site/control.js on a request and prints JSON.
//   gait      the gait pose at each time, to compare with microduck/gait.py
//   script    [t_ms, line] pairs through the playback controller, with a
//             tick every 20 ms, to compare with microduck/protocol.py
//   drive     a pad held forward for some time: the J lines the page would send
import { readFileSync } from "node:fs";
import { loadSite } from "./load.mjs";

const c = await loadSite("control.js");
const request = JSON.parse(readFileSync(process.argv[2], "utf-8"));
const out = {};

if (request.gait) {
  const { stand, params, times, forward, turn } = request.gait;
  out.gait = times.map((ts) => c.gaitPose(stand, params, ts, forward, turn).map(c.fmt1));
}

if (request.script) {
  const controller = new c.PlaybackController(request.robot);
  const replies = [];
  let now = 0;
  for (const [t, line] of request.script) {
    while (now + c.TICK_MS <= t) { now += c.TICK_MS; controller.tick(now); }
    replies.push(controller.handle(line, t));
  }
  out.script = { replies, mode: controller.mode, current: controller.current };
}

if (request.drive) {
  const manifest = request.drive.manifest;
  const engine = new c.MotionEngine(manifest.robot, manifest.gait.params, {});
  const avail = c.availability(manifest, { target: "sim" });
  const gate = new c.PadGate();
  const pad = { id: "synthetic", index: 0, connected: true, mapping: "standard", axes: [0, 0, 0, 0],
    buttons: Array.from({ length: 17 }, () => ({ pressed: false })) };
  let state = c.initialState();
  const lines = [];
  for (let t = 0; t <= request.drive.ms; t += c.SETTINGS.sendMs) {
    pad.buttons[4].pressed = t >= 100 && t < request.drive.release_ms;
    pad.axes[1] = t >= 100 ? -1 : 0;
    const step = c.nextCommand(state, gate.read(pad), t, avail, { gait: manifest.gait });
    state = step.state;
    if (step.command.type === "stop") { lines.push([t, "STOP"]); continue; }
    const result = engine.step(step.command, c.SETTINGS.sendMs);
    if (result.q) lines.push([t, c.formatJoints(result.q)]);
  }
  out.drive = lines;
}

process.stdout.write(JSON.stringify(out));
