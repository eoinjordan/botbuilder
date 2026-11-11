// SPDX-License-Identifier: MIT
// Fills walkers.html from the generated reports and animates the crank cycle
// from the kinematics.
import { COLORS, HELP, el, facts, figure, finding, getJson, programItem, row, stage, stlRow } from "./lego-common.js";

const BUILDS = ["ev3-pixy2", "hub-51515", "pi-zero-2w-51515"];
const SHORT = { "ev3-pixy2": "EV3", "hub-51515": "51515 hub", "pi-zero-2w-51515": "Pi Zero 2 W" };
const TEXT = {
  "ev3-pixy2": "EV3 brick strapped to the deck, two EV3 large motors on ports B and C, a Pixy2 on the head.",
  "hub-51515": "Robot Inventor 51515 hub strapped to the deck, two medium angular motors on hub ports A and B, a head plate with pin holes.",
  "pi-zero-2w-51515": "Raspberry Pi Zero 2 W with the Build HAT on the deck, two 51515 medium angular motors on ports A and B, a Camera Module 2 on the head.",
};

function fillBuilds(assembly, sim) {
  const cards = document.getElementById("build-cards");
  for (const build of BUILDS) {
    const a = assembly.builds[build];
    const s = sim.builds[build];
    const card = el("div", undefined, "build-card");
    const img = document.createElement("img");
    img.src = `./${a.pictures.iso}`;
    img.alt = `Rendered view of the ${SHORT[build]} walker`;
    img.width = 760;
    img.height = 600;
    const list = el("dl", undefined, "facts");
    const walk = s.forward.runs.find((r) => r.rpm === sim.walk_rpm);
    facts(list, [["Mass", `${Math.round(a.mass.total_g)} g`],
      ["Size", `${Math.round(a.size_mm[0])} x ${Math.round(a.size_mm[1])} x ${Math.round(a.size_mm[2])} mm`],
      ["Walks at 60 rpm", `${walk.speed_mm_s} mm/s`],
      ["Balance margin", `${a.stability.min_margin_mm} mm`]]);
    const jump = document.createElement("a");
    jump.href = `#get-${build}`;
    jump.textContent = "Parts and programs";
    const p = el("p");
    p.append(jump);
    card.append(img, el("h3", a.title), el("p", TEXT[build]), list, p);
    cards.append(card);
  }
}

function fillAssembly(assembly) {
  const list = document.getElementById("findings");
  for (const f of assembly.findings) list.append(finding(f.level, f.text));
  const body = document.querySelector("#balance tbody");
  const gallery = document.getElementById("assembly-gallery");
  for (const build of BUILDS) {
    const a = assembly.builds[build];
    const w = a.com_window;
    body.append(row([SHORT[build], a.mass.total_g, a.stability.min_margin_mm, a.stability.tilt_to_tip_deg,
      `${w.x_range_mm_at_com_y[0]} to ${w.x_range_mm_at_com_y[1]}`, `${w.y_range_mm_at_com_x[0]} to ${w.y_range_mm_at_com_x[1]}`]));
    gallery.append(figure(a.pictures.balance, `Soles and centre of mass of the ${SHORT[build]} walker from above`, `${SHORT[build]}: soles and centre of mass`, 760, 520));
    gallery.append(figure(a.pictures.drive, `Drive train of the ${SHORT[build]} walker with the chassis hidden`, `${SHORT[build]}: motors, gears, cranks`, 760, 520));
  }
  gallery.append(figure(assembly.gear_mesh.picture, "Three printed gears in mesh on 16 mm centres", "Printed gears on the 16 mm axle spacing", 760, 300));
  const notes = [];
  for (const build of ["ev3-pixy2", "hub-51515"]) {
    const p = assembly.builds[build].placement;
    notes.push(`${p.item}: its centre may be anywhere from ${p.x_range_balanced_mm[0]} to ${p.x_range_balanced_mm[1]} mm fore and aft of the ` +
      `centre axle, and from ${p.x_range_at_full_margin_mm[0]} to ${p.x_range_at_full_margin_mm[1]} mm keeps the full ${p.full_margin_mm} mm.`);
  }
  document.getElementById("brick").textContent =
    `Where the controller sits. ${notes.join(" ")} Centred on the deck is right, with the motors pointing backward. ` +
    `Sideways it must be centred. No build needs ballast.`;
}

function fillSimulation(sim) {
  const list = document.getElementById("sim-findings");
  const rec = document.getElementById("recordings");
  const forward = document.querySelector("#forward tbody");
  const limits = document.querySelector("#limits tbody");
  const level = { walks: "ok", speed: "fit", turning: "bad", slope: "fit", step: "bad", phase: "ok" };
  for (const build of BUILDS) {
    const s = sim.builds[build];
    for (const [key, text] of Object.entries(s.verdict)) list.append(finding(level[key] || "fit", `${SHORT[build]}: ${text}`, key));
    if (s.recordings) {
      rec.append(figure(s.recordings.walk, `Recording of the simulated ${SHORT[build]} walker at 60 rpm`, `${SHORT[build]} at 60 rpm`, 320, 240));
    }
    for (const r of s.forward.runs) {
      forward.append(row([SHORT[build], r.rpm, r.speed_mm_s, r.slip_fraction, r.max_tilt_deg, r.yaw_change_deg, r.torque.peak_nm, r.torque.stall_nm]));
    }
    const cross = Math.min(s.slopes.left_side_high.steepest_walked_deg, s.slopes.right_side_high.steepest_walked_deg);
    limits.append(row([SHORT[build], s.forward.fastest_steady_speed_mm_s, s.slopes.uphill.steepest_walked_deg,
      s.slopes.downhill.steepest_walked_deg, cross, s.steps.highest_climbed_mm, s.phase_errors.tolerated_deg, "no"]));
  }
}

function fillDownloads(summary, manifest) {
  const host = document.getElementById("downloads");
  const bytes = Object.fromEntries(manifest.files.map((f) => [f.file, f.bytes]));
  for (const build of BUILDS) {
    const entry = summary.entries.find((e) => e.locomotion === "crank" && e.build === build);
    const block = document.createElement("div");
    block.id = `get-${build}`;
    block.append(el("h3", entry.title));
    const wrap = el("div", undefined, "table-wrap");
    const table = document.createElement("table");
    table.innerHTML = "<thead><tr><th>STL</th><th>Print</th><th>For</th><th>Size</th></tr></thead>";
    const body = document.createElement("tbody");
    for (const f of entry.files) body.append(stlRow(f.file, f.qty, f.role, bytes[f.file]));
    table.append(body);
    wrap.append(table);
    block.append(wrap, el("h4", "Other parts"));
    const parts = el("ul", undefined, "plain");
    for (const p of entry.parts) parts.append(el("li", `${p.qty ? `${p.qty} x ` : ""}${p.name}: ${p.note}`));
    block.append(parts, el("h4", "Programs"));
    const programs = el("ul", undefined, "plain");
    for (const p of entry.programs) programs.append(programItem(p));
    block.append(programs);
    host.append(block);
  }
}

async function viewer(models) {
  const note = document.getElementById("view-note");
  const canvas = document.getElementById("view");
  const view = await stage(canvas, note);
  if (!view) return;
  const { THREE } = view;
  const roots = {};
  const movers = {};

  async function build(name) {
    const data = models[name].viewer;
    const root = view.root();
    root.visible = false;
    roots[name] = root;
    movers[name] = [];
    for (const b of data.boxes) root.add(view.box(b, COLORS[b.kind]));
    await Promise.all(data.printed.map(async (part) => {
      const crank = part.motion && part.motion[0] === "crank";
      const mesh = await view.part(part.file, part.matrix, crank ? COLORS.crank : COLORS.print);
      root.add(mesh);
      if (part.motion) movers[name].push({ mesh, base: mesh.matrix.clone(), motion: part.motion });
    }));
  }

  const state = { build: BUILDS[0], phase: 90, playing: false, follow: true, travel: 0 };
  const shift = new THREE.Matrix4();
  const turn = new THREE.Matrix4();
  const lay = new THREE.Matrix4().makeRotationX(Math.PI / 2);

  function pose() {
    const data = models[state.build].viewer;
    const r = data.crank_radius_mm;
    const a = (state.phase * Math.PI) / 180;
    for (const item of movers[state.build] || []) {
      const side = item.motion[1] === "left" ? 1 : -1;
      if (item.motion[0] === "leg") {
        shift.makeTranslation(side * r * Math.cos(a), 0, -side * r * Math.sin(a));
        item.mesh.matrix.multiplyMatrices(shift, item.base);
      } else {
        shift.makeTranslation(item.motion[2], item.motion[3], 0);
        turn.makeRotationY(a + (side > 0 ? 0 : Math.PI));
        item.mesh.matrix.multiplyMatrices(shift, turn).multiply(lay);
      }
    }
    // The lower foot is on the floor: lift the body to match.
    const height = data.leg_drop_mm + r * Math.abs(Math.sin(a));
    for (const name of BUILDS) {
      if (!roots[name]) continue;
      roots[name].visible = name === state.build;
      roots[name].position.set(state.follow ? (state.travel % 300) / 100 - 1.5 : 0, height / 100, 0);
    }
    const stance = Math.sin(a) > 0.02 ? "left" : Math.sin(a) < -0.02 ? "right" : "both";
    document.getElementById("phase-out").textContent = `${Math.round(state.phase)} deg`;
    facts(document.getElementById("phase-facts"), [["Foot on the floor", stance], ["Body height", `${height.toFixed(1)} mm`],
      ["Per crank turn", `${data.stride_per_turn_mm} mm`], ["Travelled", `${Math.round(state.travel)} mm`]]);
  }
  function refresh() { pose(); view.draw(); }

  // The stance foot moves back under the body: 4 r per turn.
  function advance(deltaDeg) {
    const r = models[state.build].viewer.crank_radius_mm;
    const steps = Math.max(1, Math.ceil(Math.abs(deltaDeg) / 2));
    let a = (state.phase * Math.PI) / 180;
    const da = (deltaDeg * Math.PI) / 180 / steps;
    for (let i = 0; i < steps; i++) {
      state.travel += r * Math.abs(Math.sin(a + da / 2)) * da;
      a += da;
    }
  }
  const slider = document.getElementById("phase");
  slider.addEventListener("input", () => {
    const next = Number(slider.value);
    let delta = next - state.phase;
    if (delta > 180) delta -= 360;
    if (delta < -180) delta += 360;
    advance(delta);
    state.phase = next;
    refresh();
  });
  let last = null;
  function frame(now) {
    if (!state.playing) { last = null; return; }
    if (last !== null) {
      const delta = Math.min(0.1, (now - last) / 1000) * 240;     // 40 rpm on screen
      advance(delta);
      state.phase = (state.phase + delta) % 360;
      slider.value = Math.round(state.phase) % 360;
      refresh();
    }
    last = now;
    requestAnimationFrame(frame);
  }
  const play = document.getElementById("play");
  play.addEventListener("click", () => {
    state.playing = !state.playing;
    play.textContent = state.playing ? "Pause" : "Play";
    play.setAttribute("aria-pressed", String(state.playing));
    if (state.playing) requestAnimationFrame(frame);
  });
  const follow = document.getElementById("follow");
  follow.addEventListener("click", () => {
    state.follow = !state.follow;
    follow.setAttribute("aria-pressed", String(state.follow));
    refresh();
  });
  async function load(name) {
    if (roots[name]) return;
    note.textContent = "Loading the printable parts.";
    try { await build(name); note.textContent = HELP; } catch (error) { note.textContent = `Could not load the parts: ${error.message}`; }
  }
  for (const name of BUILDS) {
    document.getElementById(`pick-${name}`).addEventListener("click", async () => {
      state.build = name;
      for (const other of BUILDS) {
        const button = document.getElementById(`pick-${other}`);
        button.setAttribute("aria-pressed", String(other === name));
        button.className = other === name ? "primary" : "secondary";
      }
      await load(name);
      refresh();
    });
  }
  await load(state.build);
  refresh();
  window.walkerViewer = { state, refresh, roots, movers };
}

async function main() {
  try {
    const [assembly, sim, manifest, summary, ...models] = await Promise.all(
      ["lego-assembly.json", "lego-sim.json", "lego-manifest.json", "variants-summary.json",
        ...BUILDS.map((b) => `lego-model-${b}.json`)].map(getJson));
    fillBuilds(assembly, sim);
    fillAssembly(assembly);
    fillSimulation(sim);
    fillDownloads(summary, manifest);
    await viewer(Object.fromEntries(BUILDS.map((b, i) => [b, models[i]])));
  } catch (error) {
    document.getElementById("findings").append(finding("bad", `Could not load the report data: ${error.message}`));
  }
}

main();
