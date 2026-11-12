// SPDX-License-Identifier: MIT
// Builds the commands that install and flash the App Lab app on an Arduino
// UNO Q. The pattern is the setup page of unoq-braccio-sketchbot: the page
// only writes commands, the visitor runs them over their own SSH session.
// Nothing here opens a connection. The functions are pure so that Node can
// test them; the page wiring at the end runs only in a browser.

export const REPOSITORY = "https://github.com/eoinjordan/botbuilder.git";
export const APP_PATH = "app_lab/microduck_agent";
export const APP_NAME = "microduck_agent";
export const SERVER_PATH = "app_lab/microduck_agent/control_server.py";
export const AGENT_PORT = 8766;
export const CONTROL_PORT = 7101;
export const AGENT_BANNER = `Microduck agent listening on ${AGENT_PORT}`;
export const DEFAULTS = { host: "", user: "arduino", repoDir: "botbuilder", appsDir: "ArduinoApps" };

export const BASES = {
  unoq: { label: "Arduino UNO Q", written: true },
  espeye: { label: "Espressif ESP-EYE", written: false,
    note: "The camera runs the sketch in the sketchbot repository (firmware/esp_eye_camera). Flash it by hand from the " +
      "Arduino IDE over the board's own Micro-USB connector: esp32 boards package, board ESP32 Wrover Module, partition " +
      "Huge APP (3MB No OTA), secrets.h with the Wi-Fi name and password, VFLIP and HMIRROR set to 1 for the way the " +
      "board stands on this robot, Upload. The stream is then at http://esp-eye.local/stream. There is no command to " +
      "give here; docs/camera.md has the steps in full." },
  esp32cam: { label: "AI Thinker ESP32-CAM", written: false,
    note: "No firmware for an ESP32-CAM exists. The sketchbot flashes its camera board, an ESP-EYE, by hand from the " +
      "Arduino IDE; that sketch does not run on an ESP32-CAM as it is. There is no command to give here." },
  look: { label: "Microduck-look biped on two Arduino UNO Q boards", written: false,
    note: "This build has fifteen joints on two Arduino UNO Q boards and an I2C servo driver. The agent this page " +
      "flashes drives six joints on one board, so no command is shown here rather than a made-up one. What you can " +
      "do: rehearse the build in simulation with python scripts/run_look.py --sim; write your own sketch from the " +
      "joint table in robot/microduck-look/joints.json, which names each joint's range, servo, board and output; or " +
      "go back to Build yours and pick the six-servo biped, which has flash steps. Keep both servo supplies " +
      "disconnected whenever you flash a board." },
  raspberrypi: { label: "Raspberry Pi", written: false },
  lego: { label: "LEGO hub", written: false },
  m5stack: { label: "M5Stack", written: false },
};

// A value from the URL (?base=...) to one of the keys above. The ids of
// config/bases.json (unoq_braccio, pi_servo, hub51515, ev3, m5_basex_ev3,
// pi_buildhat_51515) all resolve; tests/test_flash.py checks that. Unknown values
// are kept as "other" and shown as not written; nothing is invented for them.
export function resolveBase(value) {
  const raw = String(value ?? "").trim();
  if (!raw) return { key: "unoq", ...BASES.unoq, given: "" };
  const given = raw.slice(0, 40);
  const id = raw.toLowerCase().replace(/[^a-z0-9]/g, "");
  let key = "other";
  if (/^(microduck)?look/.test(id)) key = "look";
  else if (/^(arduino)?unoq/.test(id)) key = "unoq";
  else if (id.includes("espeye")) key = "espeye";
  else if (id.includes("esp32cam")) key = "esp32cam";
  else if (id.includes("raspberry") || /^r?pi/.test(id)) key = "raspberrypi";
  else if (id.includes("m5")) key = "m5stack";
  else if (/lego|spike|ev3|nxt|wedo|poweredup|^hub|51515/.test(id)) key = "lego";
  if (key === "other") return { key, label: "This controller", written: false, given };
  return { key, ...BASES[key], given };
}

// POSIX single quoting. Inside single quotes the shell expands nothing, so
// quotes, semicolons, backticks and $() arrive as plain characters. Control
// characters are refused: a pasted newline would run as a second command.
export function shellQuote(value) {
  const text = String(value);
  if (/[\u0000-\u001f\u007f]/.test(text)) throw new Error("Control characters cannot be part of a command.");
  return `'${text.replace(/'/g, "'\\''")}'`;
}

export function validHost(value) {
  const host = String(value ?? "").trim().toLowerCase();
  if (!host) throw new Error("Enter the UNO Q hostname or its local IP address.");
  if (host.length > 253) throw new Error("The host name is too long.");
  const dnsName = host.split(".").every((label) => /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/.test(label));
  const ipv6 = /^[0-9a-f:]{2,39}$/.test(host) && host.includes(":") && /^[0-9a-f]/.test(host);
  if (!dnsName && !ipv6) throw new Error("Use a plain hostname or IP address: letters, digits, dots and inner hyphens only.");
  return host;
}

export function validUser(value) {
  const user = String(value ?? "").trim();
  if (!/^[a-z_][a-z0-9_-]{0,31}$/.test(user)) throw new Error("Use a Linux user name: lower-case letters, digits, underscore or hyphen.");
  return user;
}

// A directory below the home directory on the board, for example ArduinoApps.
export function validHomePath(value, what = "The path") {
  const path = String(value ?? "").trim();
  if (!path) throw new Error(`${what} is empty.`);
  if (path.length > 200) throw new Error(`${what} is too long.`);
  if (!/^[A-Za-z0-9._][A-Za-z0-9._/-]*$/.test(path)) {
    throw new Error(`${what} must be relative to the home directory and use only letters, digits, dot, underscore, hyphen and slash.`);
  }
  if (path.endsWith("/") || path.includes("//")) throw new Error(`${what} has an empty part.`);
  if (path.split("/").some((part) => part === "." || part === ".." || part.startsWith("-"))) {
    throw new Error(`${what} must not contain '.' or '..' parts or parts that start with a hyphen.`);
  }
  return path;
}

// "$HOME"/'rel/path': the variable expands on the board, the typed part is quoted.
export function homePath(relative) {
  return `"$HOME"/${shellQuote(relative)}`;
}

function onBoard(command, wrap, target) {
  return wrap ? `ssh ${shellQuote(target)} ${shellQuote(command)}` : command;
}

// The whole plan for one base. options.mode is "install" (first time) or
// "update" (checkout and app already on the board). options.where is
// "session" (paste into the SSH session) or "computer" (each command wrapped
// in ssh and run from the visitor's own machine).
export function flashPlan(options = {}) {
  const base = resolveBase(options.base);
  if (!base.written) {
    return { base, written: false, steps: [],
      message: `${base.label}: not written. This repository has firmware and flash steps for the Arduino UNO Q only.` };
  }
  const host = validHost(options.host);
  const user = validUser(options.user ?? DEFAULTS.user);
  const repoDir = validHomePath(options.repoDir ?? DEFAULTS.repoDir, "The checkout directory");
  const appsDir = validHomePath(options.appsDir ?? DEFAULTS.appsDir, "The App Lab apps directory");
  const mode = options.mode === "update" ? "update" : "install";
  const wrap = options.where === "computer";
  const target = `${user}@${host}`;
  const repo = homePath(repoDir);
  const apps = homePath(appsDir);
  const app = homePath(`${appsDir}/${APP_NAME}`);
  const source = homePath(`${repoDir}/${APP_PATH}`);
  const steps = [];
  const add = (id, title, command, note, where = "board") => steps.push({ id, title, note, where,
    command: where === "board" ? onBoard(command, wrap, target) : command });

  if (!wrap) add("ssh", "Open a session on the board", `ssh ${shellQuote(target)}`,
    "Run on your computer. The password or key prompt is SSH's own; this page never sees it.", "computer");
  if (mode === "install") {
    add("clone", "Fetch this repository", `git clone --depth 1 ${shellQuote(REPOSITORY)} ${repo}`,
      "Needs git and Internet access on the board. Stops if the directory already exists.");
    add("mkdir", "Make the App Lab apps directory", `mkdir -p ${apps}`, "Does nothing if it is already there.");
  } else {
    add("pull", "Update the checkout", `git -C ${repo} pull --ff-only origin main`,
      "Fast-forward only. Stops if the checkout has local changes that conflict.");
    add("stop", "Stop the running app", `arduino-app-cli app stop ${app}`, "The sketch keeps running on the microcontroller until the next flash.");
    add("remove", "Remove the old copy of the app", `rm -rf ${app}`,
      "App Lab rebuilds the sketch only when the copy in the apps directory changes. This deletes that copy and nothing else.");
  }
  add("copy", "Copy the app into App Lab", `cp -R ${source} ${app}`, "Copies the sketch and the Linux-side relay.");
  add("start", "Build, flash and start", `arduino-app-cli app start ${app}`,
    "Compiles the sketch on the board, flashes the microcontroller and starts the relay. The first build takes a few minutes. Servo supply disconnected.");
  add("logs", "Read the app log", `arduino-app-cli app logs ${app}`, `Expect the line: ${AGENT_BANNER}`);
  add("status", "Ask the board for its status", `printf 'S\\n' | nc -w 2 127.0.0.1 ${AGENT_PORT}`,
    "Expect one line starting STAT mode=RELAX. See the post-flash check below.");
  add("control", "Optional: serve the control page from the board",
    `python3 ${homePath(`${repoDir}/${SERVER_PATH}`)} --bind 0.0.0.0 --port ${CONTROL_PORT}`,
    `Then open http://${host.includes(":") ? `[${host}]` : host}:${CONTROL_PORT}/ on the same network. Motion stays disabled unless you add --allow-motion. Ctrl+C stops it.`);
  return { base, written: true, steps, mode, where: wrap ? "computer" : "session", target, message: "" };
}

// The program files for the controller a link names, from the data the
// configurator uses (data/recipe.json): [{ build, lines }]. given is the
// base id or controller id from the address. Empty when none are written.
export function programsFor(data, given) {
  const rows = data.compat.support.filter((row) => row.base === given || row.controller === given);
  const controllers = [...new Set(rows.map((row) => row.controller))];
  const text = (dimId, optionId) => {
    const dim = data.compat.dimensions.find((item) => item.id === dimId);
    const option = dim.options.find((item) => item.id === optionId);
    return option ? option.label : optionId;
  };
  return data.programs
    .filter((entry) => controllers.includes(entry.match.controller))
    .map((entry) => ({
      build: [entry.match.locomotion, entry.match.drive].filter(Boolean).map((id, i) => text(i ? "drive" : "locomotion", id)).join(", "),
      lines: entry.lines,
    }));
}

// ---- page wiring (browser only) ----

function start() {
  const byId = (id) => document.getElementById(id);
  const params = new URLSearchParams(location.search);
  const base = resolveBase(params.get("base"));
  const output = byId("commands");
  const error = byId("form-error");
  const baseNote = byId("base-note");
  baseNote.textContent = base.written
    ? `Controller: ${base.label}.`
    : `Controller: ${base.label}${base.given ? ` (base=${base.given})` : ""}. Not written.`;
  byId("base-detail").textContent = base.written ? "" : (base.note || "No firmware and no flash steps exist for it in this repository, so no command is shown rather than a made-up one. " +
      "What you can do: use the programs listed below if there are any for this controller, or go back to Build yours and pick the Arduino UNO Q, the one board with flash steps.");
  byId("flash-form").hidden = !base.written;
  // Programs written for this controller's builds, with how each is loaded.
  fetch("./data/recipe.json").then((reply) => (reply.ok ? reply.json() : null)).then((data) => {
    const found = data ? programsFor(data, base.given) : [];
    if (!found.length) return;
    const box = byId("programs");
    const title = document.createElement("h3");
    title.textContent = "Programs for this controller";
    box.append(title);
    for (const program of found) {
      const list = document.createElement("ul");
      list.className = "plain";
      const head = document.createElement("p");
      head.textContent = program.build;
      head.style.fontWeight = "600";
      for (const line of program.lines) {
        const item = document.createElement("li");
        line.split(/(https:\/\/[^\s]+[^\s.,;:)])/).forEach((piece, i) => {
          if (i % 2 === 0) { item.append(document.createTextNode(piece)); return; }
          const link = document.createElement("a");
          link.href = piece;
          link.textContent = piece;
          link.target = "_blank";
          link.rel = "noopener";
          link.setAttribute("aria-label", `${piece}, opens in a new tab`);
          item.append(link);
        });
        list.append(item);
      }
      box.append(head, list);
    }
    box.hidden = false;
    baseNote.textContent = `Controller: ${base.label}${base.given ? ` (base=${base.given})` : ""}.`;
    byId("base-detail").textContent = "The UNO Q agent is not ported to this controller; its builds have the programs below.";
  }).catch(() => {});
  byId("unoq-link").hidden = base.written;
  // Back to the configurator with the same selection, if it was a known id.
  if (/^[a-z0-9_]{1,40}$/.test(base.given)) byId("back-link").href = `./?base=${base.given}`;

  async function copy(text, button) {
    try { await navigator.clipboard.writeText(text); button.textContent = "Copied"; }
    catch (failure) { button.textContent = "Select and copy by hand"; }
    setTimeout(() => { button.textContent = "Copy"; }, 2500);
  }

  function render() {
    output.textContent = "";
    error.hidden = true;
    if (!base.written) return;
    if (!byId("servo-off").checked) {
      error.textContent = "Disconnect the servo supply and tick the first box above. The commands appear after that.";
      error.hidden = false;
      return;
    }
    let plan;
    try {
      plan = flashPlan({ base: "unoq", host: byId("host").value, user: byId("user").value, repoDir: byId("repo-dir").value,
        appsDir: byId("apps-dir").value, mode: byId("mode").value, where: byId("where").value });
    } catch (failure) {
      error.textContent = byId("host").value.trim() ? failure.message : "Enter the board's address to build the commands.";
      error.hidden = false;
      return;
    }
    plan.steps.forEach((step, index) => {
      const item = document.createElement("li");
      const head = document.createElement("div");
      head.className = "command-head";
      const title = document.createElement("b");
      title.textContent = `${index + 1}. ${step.title}`;
      const place = document.createElement("span");
      place.className = "where";
      place.textContent = step.where === "computer" || plan.where === "computer" ? "on your computer" : "in the SSH session";
      const button = document.createElement("button");
      button.type = "button";
      button.className = "secondary copy";
      button.textContent = "Copy";
      button.setAttribute("aria-label", `Copy command ${index + 1}: ${step.title}`);
      button.addEventListener("click", () => copy(step.command, button));
      head.append(title, place, button);
      const pre = document.createElement("pre");
      pre.tabIndex = 0;
      pre.dataset.step = step.id;
      pre.textContent = step.command;
      const note = document.createElement("p");
      note.className = "small-note";
      note.textContent = step.note;
      item.append(head, pre, note);
      output.append(item);
    });
  }

  byId("flash-form").addEventListener("submit", (event) => event.preventDefault());
  for (const id of ["host", "user", "repo-dir", "apps-dir", "mode", "where", "servo-off"]) {
    byId(id).addEventListener("input", render);
    byId(id).addEventListener("change", render);
  }
  const host = params.get("host");
  if (host) { try { byId("host").value = validHost(host); } catch (failure) { /* ignored: the visitor types it */ } }
  render();
}

if (typeof document !== "undefined") start();
