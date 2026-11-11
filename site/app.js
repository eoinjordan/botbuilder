// SPDX-License-Identifier: MIT
// Fills the page from the generated reports and runs the 3D joint viewer.
// All paths are relative, so the site works from any base path.

const JOINT_LABELS = {
  left_hip_roll: "Left hip roll", left_hip_pitch: "Left hip pitch", left_knee: "Left knee",
  right_hip_roll: "Right hip roll", right_hip_pitch: "Right hip pitch", right_knee: "Right knee",
};
const COLORS = { print: 0xecc878, servo: 0x3c424a, horn: 0xe1e4e6, board: 0x14786e, shield: 0x285aa0, camera: 0x96283c };

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
  for (const cell of cells) tr.append(el("td", String(cell)));
  return tr;
}

function finding(level, text, label) {
  const li = el("li", undefined, level);
  li.append(el("b", label || level), document.createTextNode(text));
  return li;
}

function fillAssembly(report, joints) {
  const rep = report.variants[report.selected];
  const facts = document.getElementById("facts");
  const size = rep.dimensions.size_mm;
  const items = [
    ["Mass", `${rep.mass.total_g} g`],
    ["Size (L x W x H)", `${Math.round(size[0])} x ${Math.round(size[1])} x ${Math.round(size[2])} mm`],
    ["Foot spacing", `${Math.round(rep.dimensions.stance_width_between_foot_centres_mm)} mm`],
    ["Actuated joints", "6"],
  ];
  for (const [name, value] of items) {
    const box = document.createElement("div");
    box.append(el("dt", name), el("dd", value));
    facts.append(box);
  }
  const list = document.getElementById("findings");
  for (const f of report.findings) list.append(finding(f.level, f.text));
  const body = document.querySelector("#limits tbody");
  for (const name of joints.order) {
    const j = joints.joints[name];
    const free = rep.sweeps[name].collision_free_deg;
    body.append(row([JOINT_LABELS[name], `${free[0]} to ${free[1]}`, `${j.min_deg} to ${j.max_deg}`,
      `${j.min_set_by} / ${j.max_set_by}`, j.servo, j.torque_limit_nm, j.speed_limit_deg_s]));
  }
}

function fillSimulation(sim, hardware, joints) {
  const verdict = document.getElementById("verdict");
  const level = { stand: sim.stand.fell ? "bad" : "ok", neutral: "bad", gait: sim.gait_default.fell ? "bad" : "fit", best: "fit" };
  for (const [key, text] of Object.entries(sim.verdict)) verdict.append(finding(level[key] || "fit", text, key));
  const body = document.querySelector("#torque tbody");
  for (const name of joints.order) {
    const t = sim.stand.torque[name];
    body.append(row([JOINT_LABELS[name], t.mean_nm, t.peak_nm, t.limit_nm, t.peak_fraction_of_limit]));
  }
  const suggestions = document.getElementById("suggestions");
  for (const text of sim.suggestions) suggestions.append(el("li", text));

  const supply = hardware.supply.published;
  const big = hardware.servos.SR431.assumed.stall_current_a.value;
  const small = hardware.servos.SR311.assumed.stall_current_a.value;
  const stall = 4 * big + 2 * small;
  const amps = supply.braccio_supply_ma / 1000;
  document.getElementById("power").textContent =
    `The Braccio kit's supply is ${supply.braccio_supply_v} V at ${amps} A (maker's figure). The maker publishes no stall current ` +
    `for the SR431 or the SR311. Assuming ${big} A and ${small} A, six stalled servos would ask for ${stall} A, ` +
    `${(stall / amps).toFixed(1)} times that supply. The UNO Q needs its own ${hardware.board.published.usb_c_v} V ` +
    `${hardware.board.published.usb_c_max_a} A source on USB-C; do not feed the servos from the board's 5 V pin. ` +
    `In simulation standing draws about ${sim.stand.supply_estimate.mean_a} A and the default gait about ` +
    `${sim.gait_default.supply_estimate.mean_a} A on average (estimates from torque, not measurements).`;
}

function checklist() {
  for (const box of document.querySelectorAll("#checklist input")) {
    const key = `microduck-check-${box.dataset.key}`;
    try { box.checked = localStorage.getItem(key) === "1"; } catch (error) { /* private mode */ }
    box.addEventListener("change", () => {
      try { localStorage.setItem(key, box.checked ? "1" : "0"); } catch (error) { /* private mode */ }
    });
  }
}

// Binary STL to a three.js geometry (used only when the STLs have been
// copied into data/meshes for a local preview).
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

async function viewer(model, joints) {
  const note = document.getElementById("view-note");
  let THREE;
  try {
    THREE = await import("three");
  } catch (error) {
    note.textContent = "The 3D view needs three.js from the CDN, which did not load. The pictures above show the same model.";
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

  // Robot frame (x forward, y left, z up, mm) to three.js (y up, units of 100 mm).
  const root = new THREE.Group();
  root.rotation.x = -Math.PI / 2;
  root.scale.setScalar(0.01);
  scene.add(root);
  const floor = new THREE.GridHelper(8, 16, 0x9fb5ab, 0xd6e3dc);
  scene.add(floor);

  const groups = {};
  const hinges = {};
  for (const link of model.links) {
    const group = new THREE.Group();
    groups[link.name] = group;
    if (link.parent) {
      group.position.fromArray(link.origin_mm);
      groups[link.parent].add(group);
      hinges[link.joint] = { group, axis: new THREE.Vector3().fromArray(link.axis), min: link.min_deg, max: link.max_deg };
    } else {
      root.add(group);
    }
    const printed = new THREE.Group();
    group.add(printed);
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
        const length = a.distanceTo(b);
        mesh = new THREE.Mesh(new THREE.CylinderGeometry(shape.radius, shape.radius, length, 32), material);
        mesh.position.copy(a).add(b).multiplyScalar(0.5);
        mesh.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), b.clone().sub(a).normalize());
      }
      (shape.kind === "print" ? printed : group).add(mesh);
    }
    // The printed parts as their real meshes, from the published STLs.
    for (const item of (model.meshes_published ? link.meshes : [])) {
      fetch(`./stl/${item.file}`).then((r) => (r.ok ? r.arrayBuffer() : null)).then((buffer) => {
        if (!buffer) return;
        const mesh = new THREE.Mesh(parseStl(THREE, buffer), new THREE.MeshStandardMaterial({ color: COLORS.print, roughness: 0.8 }));
        mesh.matrixAutoUpdate = false;
        mesh.matrix.fromArray(item.matrix).transpose();
        group.add(mesh);
        printed.visible = false;
        draw();
      }).catch(() => {});
    }
  }

  // Lowest point of the robot sits on the grid.
  const box = new THREE.Box3();
  function settle() {
    root.position.y = 0;
    root.updateMatrixWorld(true);
    box.setFromObject(root);
    root.position.y = -box.min.y;
  }

  const orbit = { azimuth: 0.9, elevation: 0.28, distance: 9.5, target: new THREE.Vector3(0.5, 1.5, 0) };
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

  const sliders = document.getElementById("sliders");
  const inputs = {};
  function setJoint(name, degrees) {
    const hinge = hinges[name];
    const value = Math.min(hinge.max, Math.max(hinge.min, degrees));
    hinge.group.quaternion.setFromAxisAngle(hinge.axis, (value * Math.PI) / 180);
    inputs[name].input.value = value;
    inputs[name].output.textContent = `${value} deg`;
  }
  for (const name of joints.order) {
    const hinge = hinges[name];
    const wrap = el("div", undefined, "slider");
    const label = el("label", `${JOINT_LABELS[name]} (${hinge.min} to ${hinge.max})`);
    const input = document.createElement("input");
    input.type = "range";
    input.min = hinge.min;
    input.max = hinge.max;
    input.step = 1;
    input.id = `slider-${name}`;
    label.htmlFor = input.id;
    const output = el("output");
    wrap.append(label, output, input);
    sliders.append(wrap);
    inputs[name] = { input, output };
    input.addEventListener("input", () => { setJoint(name, Number(input.value)); settle(); draw(); });
  }
  function pose(values) {
    for (const name of joints.order) setJoint(name, values[name] || 0);
    settle();
    draw();
  }
  document.getElementById("pose-neutral").addEventListener("click", () => pose({}));
  document.getElementById("pose-stand").addEventListener("click", () => pose(model.stand_pose_deg));

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
    orbit.distance = Math.min(20, Math.max(4, orbit.distance * (event.deltaY > 0 ? 1.08 : 0.93)));
    draw();
  }, { passive: false });
  window.addEventListener("resize", draw);

  pose(model.stand_pose_deg);
  window.microduckViewer = { hinges, setJoint, pose, draw };
}

async function main() {
  checklist();
  try {
    const [report, sim, joints, model, hardware] = await Promise.all(
      ["assembly.json", "sim.json", "joints.json", "model.json", "hardware.json"].map(getJson));
    fillAssembly(report, joints);
    fillSimulation(sim, hardware, joints);
    await viewer(model, joints);
  } catch (error) {
    document.getElementById("findings").append(finding("bad", `Could not load the report data: ${error.message}`));
  }
}

main();
