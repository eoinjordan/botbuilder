// SPDX-License-Identifier: MIT
// Shared by walkers.js and wheeled.js: small DOM helpers, the STL reader and
// the 3D stage. All paths are relative, so the pages work from any base path.

export async function getJson(name) {
  const response = await fetch(`./data/${name}`);
  if (!response.ok) throw new Error(`${name}: ${response.status}`);
  return response.json();
}

export function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

export function row(cells) {
  const tr = document.createElement("tr");
  for (const cell of cells) {
    const td = document.createElement("td");
    if (cell instanceof Node) td.append(cell); else td.textContent = String(cell);
    tr.append(td);
  }
  return tr;
}

export function finding(level, text, label) {
  const li = el("li", undefined, level);
  li.append(el("b", label || level), document.createTextNode(text));
  return li;
}

export function facts(target, items) {
  target.replaceChildren();
  for (const [name, value] of items) {
    const box = document.createElement("div");
    box.append(el("dt", name), el("dd", value));
    target.append(box);
  }
}

export function figure(src, alt, caption, width, height) {
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

export function download(path, label) {
  const link = document.createElement("a");
  link.href = `./${path}`;
  link.download = path.split("/").slice(-2).join("-");
  link.textContent = label || path.split("/").pop();
  return link;
}

// One table row per STL of a manifest or summary entry: file is relative to stl/.
export function stlRow(file, quantity, what, bytes) {
  const tr = row([download(`stl/${file}`, file.replace("lego/", "")), quantity, what, bytes ? `${Math.round(bytes / 1024)} kB` : ""]);
  tr.children[2].className = "wrap";
  return tr;
}

// A program with its loading routes: Robot Creator first, then the vendor tool.
export function programItem(p) {
  const li = document.createElement("li");
  li.append(download(p.file), document.createTextNode(` (${p.language}). ${p.what} Ports: ` +
    `${Object.entries(p.ports).map(([port, what]) => `${port} ${what}`).join(", ")}. `));
  if (p.load_with) {
    const link = document.createElement("a");
    link.href = p.load_with.url;
    link.rel = "noopener noreferrer";
    link.textContent = p.load_with.name;
    li.append(document.createTextNode("Load with "), link, document.createTextNode(`: ${p.load_with.steps} Or: ${p.alternative}`));
  } else {
    li.append(document.createTextNode(p.alternative));
  }
  return li;
}

// Binary STL to a three.js geometry.
export function parseStl(THREE, buffer) {
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

// A canvas with lights, a floor grid and an orbiting camera driven by pointer,
// wheel and keys. Robot roots use x forward, y left, z up in mm.
export async function stage(canvas, note) {
  let THREE;
  try {
    THREE = await import("three");
  } catch (error) {
    note.textContent = "The 3D view needs three.js from the CDN, which did not load. The pictures show the same model.";
    return null;
  }
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  const scene = new THREE.Scene();
  scene.add(new THREE.HemisphereLight(0xffffff, 0x8a9a94, 1.6));
  const sun = new THREE.DirectionalLight(0xffffff, 1.4);
  sun.position.set(3, 6, 4);
  scene.add(sun);
  scene.add(new THREE.GridHelper(12, 50, 0x9fb5ab, 0xd6e3dc));
  const camera = new THREE.PerspectiveCamera(35, 1, 0.1, 100);
  const orbit = { azimuth: 2.2, elevation: 0.3, distance: 8.5, target: new THREE.Vector3(0.2, 0.9, 0) };
  const cache = new Map();

  function geometry(file) {
    if (!cache.has(file)) {
      cache.set(file, fetch(`./stl/${file}`).then((r) => {
        if (!r.ok) throw new Error(`${file}: ${r.status}`);
        return r.arrayBuffer();
      }).then((buffer) => parseStl(THREE, buffer)));
    }
    return cache.get(file);
  }
  function root() {
    const group = new THREE.Group();
    group.rotation.x = -Math.PI / 2;
    group.scale.setScalar(0.01);
    scene.add(group);
    return group;
  }
  function box(b, color) {
    const size = b.max.map((v, i) => v - b.min[i]);
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(size[0], size[1], size[2]),
      new THREE.MeshStandardMaterial({ color, roughness: 0.75, metalness: 0.05 }));
    mesh.position.set((b.min[0] + b.max[0]) / 2, (b.min[1] + b.max[1]) / 2, (b.min[2] + b.max[2]) / 2);
    return mesh;
  }
  async function part(file, matrix, color) {
    const mesh = new THREE.Mesh(await geometry(file), new THREE.MeshStandardMaterial({ color, roughness: 0.8, metalness: 0.02 }));
    mesh.matrixAutoUpdate = false;
    mesh.matrix.fromArray(matrix).transpose();
    return mesh;
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
  return { THREE, scene, orbit, root, box, part, draw };
}

export const HELP = "Drag or use the arrow keys to turn, scroll or plus and minus to zoom.";
export const COLORS = { print: 0xecc878, crank: 0xd9664d, motor: 0x9aa0a8, controller: 0x4778aa, camera: 0x3f996e, battery: 0x6d5a8c, tyre: 0x2c3036, wheel: 0xecc878 };
