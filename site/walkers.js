// SPDX-License-Identifier: MIT
// Fills walkers.html from the generated reports and animates the crank cycle
// from the kinematics. All paths are relative, so the page works from any
// base path.

const BUILDS = ["ev3-pixy2", "pi-zero-2w-51515"];
const SHORT = { "ev3-pixy2": "EV3", "pi-zero-2w-51515": "Pi Zero 2 W" };
const COLORS = { print: 0xecc878, crank: 0xd9664d, motor: 0x9aa0a8, controller: 0x4778aa, camera: 0x3f996e };

async function getJson(name) {
  const response = await fetch(`./data/${name}`);
  if (!response.ok) throw new Error(`${name}: ${response.status}`);
  return response.json();
}

function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function row(cells) {
  const tr = document.createElement("tr");
  for (const cell of cells) {
    const td = document.createElement("td");
    if (cell instanceof Node) td.append(cell); else td.textContent = String(cell);
    tr.append(td);
  }
  return tr;
}

function finding(level, text, label) {
  const li = el("li", undefined, level);
  li.append(el("b", label || level), document.createTextNode(text));
  return li;
}

function facts(target, items) {
  target.replaceChildren();
  for (const [name, value] of items) {
    const box = document.createElement("div");
    box.append(el("dt", name), el("dd", value));
    target.append(box);
  }
}

function figure(src, alt, caption, width, height) {
  const fig = document.createElement("figure");
  const img = document.createElement("img");
  img.loading = "lazy";
  img.src = `./${src}`;
  img.alt = alt;
  img.width = width;
  img.height = height;
  fig.append(img, el("figcaption", caption));
  return fig;
}

function fillBuilds(assembly, sim) {
  const cards = document.getElementById("build-cards");
  const text = {
    "ev3-pixy2": "EV3 brick strapped to the deck, two EV3 large motors on ports B and C, a Pixy2 on the head.",
    "pi-zero-2w-51515": "Raspberry Pi Zero 2 W with the Build HAT on the deck, two 51515 medium angular motors on ports A and B, a Camera Module 2 on the head.",
  };
  for (const build of BUILDS) {
    const a = assembly.builds[build];
    const s = sim.builds[build];
    const card = el("div", undefined, "build-card");
    const img = document.createElement("img");
    img.src = `./${a.pictures.iso}`;
    img.alt = `Rendered view of the ${SHORT[build]} walker as placed for the assembly test`;
    img.width = 760;
    img.height = 600;
    const list = el("dl", undefined, "facts");
    const walk = s.forward.runs.find((r) => r.rpm === sim.walk_rpm);
    facts(list, [["Mass", `${Math.round(a.mass.total_g)} g`],
      ["Size", `${Math.round(a.size_mm[0])} x ${Math.round(a.size_mm[1])} x ${Math.round(a.size_mm[2])} mm`],
      ["Walks at 60 rpm", `${walk.speed_mm_s} mm/s`],
      ["Balance margin", `${a.stability.min_margin_mm} mm`]]);
    card.append(img, el("h3", a.title), el("p", text[build]), list);
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
  const p = assembly.builds["ev3-pixy2"].placement;
  document.getElementById("brick").textContent =
    `Where the EV3 brick must sit: its centre anywhere from ${p.x_range_balanced_mm[0]} to ${p.x_range_balanced_mm[1]} mm fore and aft of ` +
    `the centre axle keeps the robot balanced, and from ${p.x_range_at_full_margin_mm[0]} to ${p.x_range_at_full_margin_mm[1]} mm keeps the full ` +
    `${p.full_margin_mm} mm. Centred on the deck is right, with the motors pointing backward. Sideways it must be centred. ` +
    `No ballast is needed on either build.`;
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
      rec.append(figure(s.recordings.fast, `Recording of the simulated ${SHORT[build]} walker at the motor's full speed`, `${SHORT[build]} at full motor speed`, 320, 240));
    }
    for (const r of s.forward.runs) {
      forward.append(row([SHORT[build], r.rpm, r.speed_mm_s, r.slip_fraction, r.max_tilt_deg, r.yaw_change_deg, r.torque.peak_nm, r.torque.stall_nm]));
    }
    const cross = Math.min(s.slopes.left_side_high.steepest_walked_deg, s.slopes.right_side_high.steepest_walked_deg);
    limits.append(row([SHORT[build], s.forward.fastest_steady_speed_mm_s, s.slopes.uphill.steepest_walked_deg,
      s.slopes.downhill.steepest_walked_deg, cross, s.steps.highest_climbed_mm, s.phase_errors.tolerated_deg, "no"]));
  }
}

function fillParts(manifest) {
  const body = document.querySelector("#parts tbody");
  for (const f of manifest.files) {
    const link = document.createElement("a");
    link.href = `./stl/lego/${f.file}`;
    link.download = f.file.replace("/", "-");
    link.textContent = f.file;
    const tr = row([link, f.print_quantity, f.purpose, f.volume_cm3, f.bounding_box_mm.join(" x "), `${Math.round(f.bytes / 1024)} kB`]);
    tr.children[2].className = "wrap";
    body.append(tr);
  }
}

// Binary STL to a three.js geometry.
function parseStl(THREE, buffer) {
  const view = new DataView(buffer);
  const count = view.getUint32(80, true);
  const positions = new Float32Array(count * 9);
  for (let i = 0; i < count; i++) {
    const base = 84 + i * 50 + 12;
    for (let k = 0; k < 9; k++) positions[i * 9 + k] = view.getFloat32(base + k * 4, true);
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
  geometry.computeVertexNormals();
  return geometry;
}

async function viewer(models) {
  const note = document.getElementById("view-note");
  let THREE;
  try {
    THREE = await import("three");
  } catch (error) {
    note.textContent = "The 3D view needs three.js from the CDN, which did not load. The pictures below show the same model.";
    return;
  }
  const canvas = document.getElementById("view");
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  const scene = new THREE.Scene();
  scene.add(new THREE.HemisphereLight(0xffffff, 0x8a9a94, 1.6));
  const sun = new THREE.DirectionalLight(0xffffff, 1.4);
  sun.position.set(3, 6, 4);
  scene.add(sun);
  const camera = new THREE.PerspectiveCamera(35, 1, 0.1, 100);
  const floor = new THREE.GridHelper(12, 50, 0x9fb5ab, 0xd6e3dc);
  scene.add(floor);

  // Robot frame (x forward, y left, z up, mm) to three.js (y up, units of 100 mm).
  const roots = {};
  const movers = {};
  const cache = new Map();
  function geometry(file) {
    if (!cache.has(file)) {
      cache.set(file, fetch(`./stl/lego/${file}`).then((r) => {
        if (!r.ok) throw new Error(`${file}: ${r.status}`);
        return r.arrayBuffer();
      }).then((buffer) => parseStl(THREE, buffer)));
    }
    return cache.get(file);
  }

  async function build(name) {
    const view = models[name].viewer;
    const root = new THREE.Group();
    root.rotation.x = -Math.PI / 2;
    root.scale.setScalar(0.01);
    root.visible = false;
    scene.add(root);
    roots[name] = root;
    movers[name] = [];
    for (const b of view.boxes) {
      const size = b.max.map((v, i) => v - b.min[i]);
      const mesh = new THREE.Mesh(new THREE.BoxGeometry(size[0], size[1], size[2]),
        new THREE.MeshStandardMaterial({ color: COLORS[b.kind], roughness: 0.75, metalness: 0.05 }));
      mesh.position.set((b.min[0] + b.max[0]) / 2, (b.min[1] + b.max[1]) / 2, (b.min[2] + b.max[2]) / 2);
      root.add(mesh);
    }
    await Promise.all(view.printed.map(async (part) => {
      const crank = part.motion && part.motion[0] === "crank";
      const mesh = new THREE.Mesh(await geometry(part.file),
        new THREE.MeshStandardMaterial({ color: crank ? COLORS.crank : COLORS.print, roughness: 0.8, metalness: 0.02 }));
      mesh.matrixAutoUpdate = false;
      const base = new THREE.Matrix4().fromArray(part.matrix).transpose();
      mesh.matrix.copy(base);
      root.add(mesh);
      if (part.motion) movers[name].push({ mesh, base, motion: part.motion });
    }));
  }

  const state = { build: BUILDS[0], phase: 90, playing: false, follow: true, travel: 0 };
  const orbit = { azimuth: 2.2, elevation: 0.3, distance: 8.5, target: new THREE.Vector3(0.2, 0.9, 0) };
  const shift = new THREE.Matrix4();
  const turn = new THREE.Matrix4();
  const lay = new THREE.Matrix4().makeRotationX(Math.PI / 2);

  function pose() {
    const view = models[state.build].viewer;
    const r = view.crank_radius_mm;
    const a = (state.phase * Math.PI) / 180;
    for (const item of movers[state.build] || []) {
      const side = item.motion[1] === "left" ? 1 : -1;
      if (item.motion[0] === "leg") {
        shift.makeTranslation(side * r * Math.cos(a), 0, -side * r * Math.sin(a));
        item.mesh.matrix.multiplyMatrices(shift, item.base);
      } else {
        const angle = a + (side > 0 ? 0 : Math.PI);
        shift.makeTranslation(item.motion[2], item.motion[3], 0);
        turn.makeRotationY(angle);
        item.mesh.matrix.multiplyMatrices(shift, turn).multiply(lay);
      }
    }
    // The lower foot is on the floor: lift the body to match.
    const height = view.leg_drop_mm + r * Math.abs(Math.sin(a));
    for (const name of BUILDS) {
      if (!roots[name]) continue;
      roots[name].visible = name === state.build;
      roots[name].position.set(state.follow ? (state.travel % 300) / 100 - 1.5 : 0, height / 100, 0);
    }
    const stance = Math.sin(a) > 0.02 ? "left" : Math.sin(a) < -0.02 ? "right" : "both";
    document.getElementById("phase-out").textContent = `${Math.round(state.phase)} deg`;
    facts(document.getElementById("phase-facts"), [["Foot on the floor", stance], ["Body height", `${height.toFixed(1)} mm`],
      ["Per crank turn", `${view.stride_per_turn_mm} mm`], ["Travelled", `${Math.round(state.travel)} mm`]]);
  }

  function draw() {
    const width = canvas.clientWidth;
    const height = canvas.clientHeight;
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

  function refresh() { pose(); draw(); }

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

  // The stance foot moves back under the body: 4 r per turn, as |d cos| of the phase.
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
  for (const name of BUILDS) {
    document.getElementById(`pick-${name}`).addEventListener("click", async () => {
      state.build = name;
      for (const other of BUILDS) {
        const button = document.getElementById(`pick-${other}`);
        button.setAttribute("aria-pressed", String(other === name));
        button.className = other === name ? "primary" : "secondary";
      }
      if (!roots[name]) {
        note.textContent = "Loading the printable parts.";
        try { await build(name); note.textContent = "Drag or use the arrow keys to turn, scroll or plus and minus to zoom."; } catch (error) { note.textContent = `Could not load the parts: ${error.message}`; }
      }
      refresh();
    });
  }

  let drag = null;
  canvas.addEventListener("pointerdown", (event) => { drag = { x: event.clientX, y: event.clientY }; canvas.setPointerCapture(event.pointerId); });
  canvas.addEventListener("pointerup", () => { drag = null; });
  canvas.addEventListener("pointermove", (event) => {
    if (!drag) return;
    orbit.azimuth -= (event.clientX - drag.x) * 0.008;
    orbit.elevation = Math.min(1.4, Math.max(-0.2, orbit.elevation + (event.clientY - drag.y) * 0.006));
    drag = { x: event.clientX, y: event.clientY };
    draw();
  });
  canvas.addEventListener("wheel", (event) => {
    event.preventDefault();
    orbit.distance = Math.min(20, Math.max(3, orbit.distance * (event.deltaY > 0 ? 1.08 : 0.93)));
    draw();
  }, { passive: false });
  canvas.addEventListener("keydown", (event) => {
    const keys = { ArrowLeft: [0.1, 0, 1], ArrowRight: [-0.1, 0, 1], ArrowUp: [0, 0.06, 1], ArrowDown: [0, -0.06, 1], "+": [0, 0, 0.9], "=": [0, 0, 0.9], "-": [0, 0, 1.1] };
    const k = keys[event.key];
    if (!k) return;
    event.preventDefault();
    orbit.azimuth += k[0];
    orbit.elevation = Math.min(1.4, Math.max(-0.2, orbit.elevation + k[1]));
    orbit.distance = Math.min(20, Math.max(3, orbit.distance * k[2]));
    draw();
  });
  window.addEventListener("resize", draw);

  try {
    await build(state.build);
    note.textContent = "Drag or use the arrow keys to turn, scroll or plus and minus to zoom.";
  } catch (error) {
    note.textContent = `Could not load the parts: ${error.message}`;
  }
  refresh();
  window.walkerViewer = { state, refresh, roots, movers };
}

async function main() {
  try {
    const [assembly, sim, manifest, ...models] = await Promise.all(
      ["lego-assembly.json", "lego-sim.json", "lego-manifest.json", ...BUILDS.map((b) => `lego-model-${b}.json`)].map(getJson));
    fillBuilds(assembly, sim);
    fillAssembly(assembly);
    fillSimulation(sim);
    fillParts(manifest);
    await viewer(Object.fromEntries(BUILDS.map((b, i) => [b, models[i]])));
  } catch (error) {
    document.getElementById("findings").append(finding("bad", `Could not load the report data: ${error.message}`));
  }
}

main();
