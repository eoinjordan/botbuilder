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
  esp32cam: { label: "AI Thinker ESP32-CAM", written: false,
    note: "No firmware for an ESP32-CAM exists in this repository. In the sketchbot arrangement the camera board is " +
      "flashed by hand from the Arduino IDE over its serial port (esp32 boards package, PSRAM enabled, Huge APP " +
      "partition, Upload); neither its site nor its SSH commands flash it. There is no command to give here." },
  raspberrypi: { label: "Raspberry Pi", written: false },
  lego: { label: "LEGO hub", written: false },
  m5stack: { label: "M5Stack", written: false },
};

// A value from the URL (?base=...) to one of the keys above. Unknown values
// are kept as "other" and shown as not written; nothing is invented for them.
export function resolveBase(value) {
  const raw = String(value ?? "").trim();
  if (!raw) return { key: "unoq", ...BASES.unoq, given: "" };
  const given = raw.slice(0, 40);
  const id = raw.toLowerCase().replace(/[^a-z0-9]/g, "");
  let key = "other";
  if (/^(arduino)?unoq/.test(id)) key = "unoq";
  else if (id.includes("esp32cam")) key = "esp32cam";
  else if (id.includes("raspberry") || /^(rpi|pi[0-9]*|pizero.*)$/.test(id)) key = "raspberrypi";
  else if (id.includes("m5")) key = "m5stack";
  else if (/lego|spike|ev3|nxt|wedo|poweredup/.test(id)) key = "lego";
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
  byId("base-detail").textContent = base.written ? "" : (base.note || "No firmware and no flash steps exist for it in this repository. No command is shown rather than a made-up one.");
  byId("flash-form").hidden = !base.written;
  byId("unoq-link").hidden = base.written;

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
