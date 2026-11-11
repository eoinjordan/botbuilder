// SPDX-License-Identifier: MIT
// Fills wheeled.html from the variants summary and the wheeled reports and
// shows the chosen build in 3D.
import { COLORS, HELP, el, facts, figure, finding, getJson, programItem, row, stage, stlRow } from "./lego-common.js";

const WHEEL_LABEL = { lego: "LEGO wheels", tt65: "Stock TT wheels, 65 mm", printed_ring: "Printed, with an O-ring or band", printed_tpu: "Printed hub with a TPU tyre" };

function fillFindings(analysis, sim) {
  const ids = analysis.defaults;
  const mean = (list, f) => (list.reduce((sum, id) => sum + f(id), 0) / list.length).toFixed(1);
  const at = (end) => ids.filter((id) => analysis.variants[id].wheels_at === end);
  const by = (support) => ids.filter((id) => analysis.variants[id].support === support);
  const slope = (id) => sim.variants[id].slope.steepest_climbed_deg;
  const drag = (id) => analysis.variants[id].drag_n;
  const list = document.getElementById("wheeled-findings");
  list.append(finding("ok", `Every build has its centre of mass inside the triangle of the two wheels and the support, ` +
    `${Math.min(...ids.map((id) => analysis.variants[id].static_margin_mm))} mm or more from the nearest edge.`, "balance"));
  list.append(finding("ok", `Wheels at the back climb ${mean(at("back"), slope)} degrees on average, wheels at the front ` +
    `${mean(at("front"), slope)}.`, "which end"));
  list.append(finding("fit", "Wheels at the back can lift the support on a hard start and tip backward at the slope limit; wheels at the front " +
    "lift the support on hard braking instead.", "tipping"));
  list.append(finding("fit", `A ball in a plain printed cup slides in the cup, so it lowers the drag without removing it: ` +
    `${mean(by("ball"), drag)} N against ${mean(by("skid"), drag)} N for the skid on the level. Ball builds climb ` +
    `${mean(by("ball"), slope)} degrees on average against ${mean(by("skid"), slope)}; the ball helps most with the wheels at the front.`, "skid or ball"));
  const tyres = document.querySelector("#tyres tbody");
  for (const id of analysis.tyre_comparison) {
    const a = analysis.variants[id];
    const s = sim.variants[id];
    tyres.append(row([`${a.base} / ${a.drive}`, a.wheel, a.tyre.replace("_", " "), a.friction.wheel, s.straight.speed_m_s,
      s.spin.fraction_of_ideal, s.slope.steepest_climbed_deg, s.slope.how || "-", s.step.highest_climbed_mm]));
  }
  const rec = document.getElementById("wheeled-recordings");
  if (sim.recordings) {
    rec.append(figure(sim.recordings.ev3_straight_and_turn, "Recording of the simulated EV3 wheeled build driving straight and turning", "EV3, skid, wheels at the back", 320, 240));
    rec.append(figure(sim.recordings.ev3_step, "Recording of the simulated EV3 wheeled build stopped by a step", "EV3 stopped by a step", 320, 240));
    rec.append(figure(sim.recordings.unoq_tt_ball_front, "Recording of the simulated UNO Q build on TT motors with the wheels at the front", "UNO Q, TT motors, ball, wheels at the front", 320, 240));
  }
}

async function chooser(summary, manifest, views) {
  const entries = summary.entries.filter((e) => e.locomotion === "wheeled");
  const bytes = Object.fromEntries(manifest.files.map((f) => [f.file, f.bytes]));
  const base = document.getElementById("pick-base");
  const wheel = document.getElementById("pick-wheel");
  const support = document.getElementById("pick-support");
  const end = document.getElementById("pick-end");
  const pairs = [];
  for (const e of entries) {
    const key = `${e.controller}|${e.drive}`;
    if (!pairs.some((p) => p.key === key)) pairs.push({ key, label: e.title.replace(": two wheels on", ":") });
  }
  // The two LEGO controllers first.
  pairs.sort((a, b) => (/^(ev3|hub51515)\|/.test(b.key) ? 1 : 0) - (/^(ev3|hub51515)\|/.test(a.key) ? 1 : 0));
  for (const p of pairs) {
    const option = el("option", p.label);
    option.value = p.key;
    base.append(option);
  }
  function wheelOptions() {
    const kinds = [...new Set(entries.filter((e) => `${e.controller}|${e.drive}` === base.value).map((e) => e.wheel))];
    wheel.replaceChildren();
    for (const kind of kinds) {
      const option = el("option", WHEEL_LABEL[kind]);
      option.value = kind;
      wheel.append(option);
    }
  }

  const note = document.getElementById("view-note");
  const view = await stage(document.getElementById("view"), note);
  let shown = null;
  async function show3d(id) {
    if (!view) return;
    const data = views[id];
    const root = view.root();
    root.position.y = data.radius_mm / 100;
    note.textContent = "Loading the printable parts.";
    try {
      for (const b of data.boxes) root.add(view.box(b, COLORS[b.kind]));
      for (const w of data.wheels.filter((x) => x.cylinder)) {
        const tyre = new view.THREE.Mesh(new view.THREE.CylinderGeometry(w.radius, w.radius, w.width, 48),
          new view.THREE.MeshStandardMaterial({ color: COLORS.tyre, roughness: 0.9 }));
        tyre.position.fromArray(w.centre);
        root.add(tyre);
      }
      const meshes = await Promise.all([...data.stl, ...data.wheels.filter((x) => !x.cylinder)].map((p) => view.part(p.file, p.matrix, COLORS[p.kind])));
      for (const mesh of meshes) root.add(mesh);
      note.textContent = HELP;
    } catch (error) {
      note.textContent = `Could not load the parts: ${error.message}`;
    }
    if (shown) view.scene.remove(shown);
    shown = root;
    view.draw();
  }

  async function show() {
    const e = entries.find((x) => `${x.controller}|${x.drive}` === base.value && x.wheel === wheel.value &&
      x.support === support.value && x.wheels === end.value);
    if (!e) return;
    document.getElementById("build-title").textContent = e.title;
    facts(document.getElementById("build-facts"), [["Mass", `${e.mass_g} g`], ["Speed", `${e.speed_m_s} m/s`],
      ["Spin", `${e.spin_deg_s} deg/s`], ["Slope", `${e.slope_limit_deg} deg`], ["Step", `${e.step_limit_mm} mm`],
      ["Ground clearance", `${e.ground_clearance_mm} mm`], ["Wheel", `${e.wheel_diameter_mm} mm`], ["Margin", `${e.stability_margin_mm} mm`]]);
    const notes = document.getElementById("build-notes");
    notes.replaceChildren(el("li", `Drive: ${e.drive_summary}.`), el("li", `Balance: ${e.stability_verdict}.`), ...e.notes.map((n) => el("li", n)));
    const files = document.querySelector("#build-files tbody");
    files.replaceChildren(...e.files.map((f) => stlRow(f.file, f.qty, f.role, bytes[f.file])));
    document.getElementById("build-parts").replaceChildren(...e.parts.map((p) => el("li", `${p.qty ? `${p.qty} x ` : ""}${p.name}: ${p.note}`)));
    const programs = document.getElementById("build-programs");
    programs.replaceChildren(...(e.programs.length ? e.programs.map(programItem) : [el("li", "Not written for this controller yet.")]));
    await show3d(e.id);
  }
  base.addEventListener("change", () => { wheelOptions(); show(); });
  for (const select of [wheel, support, end]) select.addEventListener("change", show);
  wheelOptions();
  await show();
}

function fillParts(manifest) {
  const body = document.querySelector("#parts tbody");
  for (const f of manifest.files.filter((x) => x.file.startsWith("lego/wheeled/"))) {
    body.append(stlRow(f.file, f.print_quantity, f.note ? `${f.what} (${f.note})` : f.what, f.bytes));
  }
}

async function main() {
  try {
    const [summary, analysis, sim, manifest, views] = await Promise.all(
      ["variants-summary.json", "wheeled-analysis.json", "wheeled-sim.json", "lego-manifest.json", "wheeled-viewer.json"].map(getJson));
    fillFindings(analysis, sim);
    fillParts(manifest);
    await chooser(summary, manifest, views);
  } catch (error) {
    document.getElementById("wheeled-findings").append(finding("bad", `Could not load the report data: ${error.message}`));
  }
}

main();
