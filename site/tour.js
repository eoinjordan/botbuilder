// SPDX-License-Identifier: MIT
// A guided tour of the site: a short card beside the control each step is
// about, moving between pages by itself. No library. The steps are content,
// in data/tour.json (config/tour.json in the repository).
//
// The decisions are pure functions (plan, advance, anchorFor), run under
// Node by tests/test_tour.py. A first-time visitor on the landing page gets
// a small "New here?" card, not a dialog over the page; the tour itself
// starts from that card, from "Take the tour" in every footer, or from the
// address ?tour=1.
//
// One switch turns it off: localStorage "botbuilder-tour" set to "off"
// (the page tests set it), or ?tour=0 in the address.

export const SEEN_KEY = "botbuilder-tour-seen";
export const SWITCH_KEY = "botbuilder-tour";
export const SESSION_KEY = "botbuilder-tour-step";

// What to do when a page loads.
//   env.params   the address's tour and tourstep values (strings or null)
//   env.session  the step saved for a move between pages (a number or null)
//   env.seen     true or false, or null when storage cannot be read
//   env.off      the switch
//   env.landing  whether this is the landing page
//   env.count    the number of steps
export function plan(env) {
  if (env.off || env.params.tour === "0") return { action: "none" };
  const inRange = (value) => Number.isInteger(value) && value >= 0 && value < env.count;
  if (env.params.tour === "1") return { action: "run", index: 0 };
  // A move between pages: the saved step, or the one the address carries when nothing could be saved.
  if (inRange(env.session)) return { action: "run", index: env.session };
  const carried = env.params.tourstep === null ? NaN : Number(env.params.tourstep);
  if (env.params.tourstep !== null && inRange(carried)) return { action: "run", index: carried };
  // A new visitor, or one whose browser keeps nothing: offer it, never open it unasked.
  if (env.landing && env.seen !== true) return { action: "offer" };
  return { action: "none" };
}

// The step after an action. done: the tour is over (and is then "seen").
export function advance(index, action, count) {
  if (action === "skip" || action === "close") return { index, done: true };
  if (action === "back") return { index: Math.max(0, index - 1), done: false };
  if (index + 1 >= count) return { index, done: true };
  return { index: index + 1, done: false };
}

// Where a step shows on the current page.
//   step.page     the page it belongs to; step.anchor its control (a list of
//                 selectors, first one found wins); step.open a <details> to open first
//   here          the current page's file name
//   pages         the pages the site has
//   has(selector) whether a visible element matches
// Returns { navigate } to go to the step's page, or { open, target } to
// show it here; target null means a centred card.
export function anchorFor(step, here, pages, has) {
  if (step.page !== here && pages.includes(step.page)) return { navigate: step.page };
  // On its own page, or its page is not built: show it here and never point at nothing.
  const own = step.page === here;
  const open = own && step.open ? step.open : null;
  const anchors = own ? [].concat(step.anchor || []) : [];
  const target = anchors.find((selector) => has(selector)) || null;
  // A control inside a closed panel becomes visible once the panel is open.
  return { open, target: target || (open && anchors.length ? anchors[0] : null) };
}

// The address of a step's page, carrying the step in case nothing can be saved.
export function stepAddress(page, index) {
  return `./${page === "index.html" ? "" : page}?tourstep=${index}`;
}

// --- page ---------------------------------------------------------------------

// Storage by name ("localStorage" or "sessionStorage"), reached only inside
// try: a browser that blocks storage throws on the property itself.
function read(name, key) {
  try {
    return { ok: true, value: window[name].getItem(key) };
  } catch (error) {
    return { ok: false, value: null };
  }
}

function write(name, key, value) {
  try {
    if (value === null) window[name].removeItem(key);
    else window[name].setItem(key, value);
    return true;
  } catch (error) {
    return false;
  }
}

function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function pageName() {
  const name = window.location.pathname.split("/").pop();
  return name === "" ? "index.html" : name;
}

function visible(selector) {
  const node = document.querySelector(selector);
  if (!node) return false;
  const box = node.getBoundingClientRect();
  return box.width > 0 && box.height > 0;
}

let steps = null;
let pages = ["index.html", "biped.html", "admin.html"];

async function load() {
  if (steps) return steps;
  const response = await fetch("./data/tour.json");
  if (!response.ok) throw new Error(String(response.status));
  steps = (await response.json()).steps;
  try {
    const listed = await fetch("./data/pages.json");
    if (listed.ok) pages = pages.concat(await listed.json());
  } catch (error) {
    // Without the list every page is taken as missing: the steps show here.
  }
  return steps;
}

function finish() {
  write("localStorage", SEEN_KEY, "1");
  write("sessionStorage", SESSION_KEY, null);
}

class Tour {
  constructor(list) {
    this.steps = list;
    this.index = 0;
    this.before = document.activeElement;
    this.spot = el("div", undefined, "tour-spot");
    this.spot.setAttribute("aria-hidden", "true");
    this.card = el("div", undefined, "tour-card");
    this.card.setAttribute("role", "dialog");
    this.card.setAttribute("aria-modal", "true");
    this.card.setAttribute("aria-labelledby", "tour-title");
    this.card.setAttribute("aria-describedby", "tour-text");
    this.count = el("p", undefined, "tour-count");
    this.title = el("h2");
    this.title.id = "tour-title";
    this.text = el("p");
    this.text.id = "tour-text";
    const row = el("div", undefined, "tour-actions");
    this.back = el("button", "Back", "secondary");
    this.next = el("button", "Next", "primary");
    this.skip = el("button", "Skip", "tour-skip");
    for (const [button, action] of [[this.back, "back"], [this.next, "next"], [this.skip, "skip"]]) {
      button.type = "button";
      button.addEventListener("click", () => this.act(action));
      row.append(button);
    }
    this.card.append(this.count, this.title, this.text, row);
    this.onKey = (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        this.act("close");
      } else if (event.key === "Tab") {
        // Focus stays inside the card while it is open.
        const buttons = [this.back, this.next, this.skip].filter((button) => !button.disabled);
        const at = buttons.indexOf(document.activeElement);
        event.preventDefault();
        buttons[(at + (event.shiftKey ? -1 : 1) + buttons.length) % buttons.length].focus();
      }
    };
    this.place = () => this.position();
  }

  open(index) {
    document.body.append(this.spot, this.card);
    document.addEventListener("keydown", this.onKey, true);
    window.addEventListener("resize", this.place);
    window.addEventListener("scroll", this.place, true);
    // The card changes size when its text or the web font arrives: place it again.
    if (window.ResizeObserver) {
      this.watch = new ResizeObserver(this.place);
      this.watch.observe(this.card);
    }
    this.show(index);
  }

  close() {
    document.removeEventListener("keydown", this.onKey, true);
    window.removeEventListener("resize", this.place);
    window.removeEventListener("scroll", this.place, true);
    if (this.watch) this.watch.disconnect();
    window.clearTimeout(this.wait);
    this.spot.remove();
    this.card.remove();
    if (this.before && document.contains(this.before) && this.before.focus) this.before.focus();
  }

  act(action) {
    const result = advance(this.index, action, this.steps.length);
    if (result.done) {
      finish();
      this.close();
      return;
    }
    this.show(result.index);
  }

  show(index) {
    this.index = index;
    const step = this.steps[index];
    const where = anchorFor(step, pageName(), pages, visible);
    if (where.navigate) {
      // The step is on another page: remember it, and carry it in the address as well.
      write("sessionStorage", SESSION_KEY, String(index));
      window.location.assign(stepAddress(where.navigate, index));
      return;
    }
    write("sessionStorage", SESSION_KEY, String(index));
    if (where.open) {
      const panel = document.querySelector(where.open);
      if (panel) panel.open = true;
    }
    this.target = where.target && visible(where.target) ? document.querySelector(where.target) : null;
    // A control the page is still drawing (the recipe loads its data first): look again for a moment.
    window.clearTimeout(this.wait);
    let tries = 0;
    const again = () => {
      if (this.index !== index || this.target || !document.contains(this.card)) return;
      const found = anchorFor(step, pageName(), pages, visible).target;
      if (found && visible(found)) {
        this.target = document.querySelector(found);
        this.target.scrollIntoView({ block: "center", inline: "nearest" });
        this.position();
      } else if ((tries += 1) < 20) this.wait = window.setTimeout(again, 150);
    };
    if (!this.target && step.page === pageName() && [].concat(step.anchor || []).length) this.wait = window.setTimeout(again, 150);
    this.count.textContent = `Step ${index + 1} of ${this.steps.length}`;
    this.title.textContent = step.title;
    this.text.textContent = step.text;
    this.back.disabled = index === 0;
    this.next.textContent = index + 1 === this.steps.length ? "Finish" : "Next";
    if (this.target) {
      const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      this.target.scrollIntoView({ block: "center", inline: "nearest", behavior: still ? "auto" : "smooth" });
    }
    this.position();
    this.next.focus({ preventScroll: true });
  }

  position() {
    const docked = window.matchMedia("(max-width: 520px)").matches;
    this.card.classList.toggle("tour-docked", docked);
    this.card.classList.toggle("tour-centred", !docked && !this.target);
    this.card.style.left = "";
    this.card.style.top = "";
    if (!this.target) {
      this.spot.hidden = true;
      return;
    }
    const box = this.target.getBoundingClientRect();
    const pad = 6;
    this.spot.hidden = false;
    this.spot.style.left = `${Math.max(0, box.left - pad)}px`;
    this.spot.style.top = `${box.top - pad}px`;
    this.spot.style.width = `${Math.min(window.innerWidth, box.width + 2 * pad)}px`;
    this.spot.style.height = `${box.height + 2 * pad}px`;
    if (docked) return;
    // Under the control when there is room, else over it, else at the top of the window.
    const size = this.card.getBoundingClientRect();
    let top = box.bottom + pad + 10;
    if (top + size.height > window.innerHeight - 8) top = box.top - pad - 10 - size.height;
    if (top < 8) top = Math.max(8, window.innerHeight - size.height - 8);
    const left = Math.min(Math.max(8, box.left), Math.max(8, window.innerWidth - size.width - 8));
    this.card.style.left = `${left}px`;
    this.card.style.top = `${top}px`;
  }
}

let running = null;

export async function startTour(index) {
  if (running) running.close();
  const list = await load();
  running = new Tour(list);
  running.open(Math.min(Math.max(0, index), list.length - 1));
  return running;
}

// Start it, and say nothing if its steps cannot be loaded: the page served by
// the robot's own server carries this script but not the site's data.
function quietly(index) {
  return startTour(index).catch(() => {});
}

// The small card a new visitor sees: start the tour or send it away.
function offer() {
  const card = el("div", undefined, "tour-offer");
  card.setAttribute("role", "region");
  card.setAttribute("aria-label", "Tour of the site");
  const start = el("button", "Take the tour", "primary");
  const no = el("button", "No thanks", "secondary");
  start.type = "button";
  no.type = "button";
  start.addEventListener("click", () => {
    card.remove();
    quietly(0);
  });
  no.addEventListener("click", () => {
    write("localStorage", SEEN_KEY, "1");
    card.remove();
  });
  const row = el("div", undefined, "tour-actions");
  row.append(start, no);
  card.append(el("p", "New here? A short tour shows what the site can do."), row);
  document.body.append(card);
}

function begin() {
  const params = new URLSearchParams(window.location.search);
  // The landing page is the one with the row of finished builds, whatever its address.
  const landing = pageName() === "index.html" && document.getElementById("builds") !== null;
  const flag = read("localStorage", SWITCH_KEY);
  const seen = read("localStorage", SEEN_KEY);
  const saved = read("sessionStorage", SESSION_KEY);
  const decision = plan({
    params: { tour: params.get("tour"), tourstep: params.get("tourstep") },
    session: saved.value === null ? null : Number(saved.value),
    seen: seen.ok ? seen.value === "1" : null,
    off: flag.value === "off",
    landing,
    count: Number.MAX_SAFE_INTEGER,
  });
  // "Take the tour" in the footer starts it here when this is the landing page.
  for (const link of document.querySelectorAll("a[data-tour]")) {
    link.addEventListener("click", (event) => {
      if (!landing) return;
      event.preventDefault();
      quietly(0);
    });
  }
  if (decision.action === "run") {
    // After the page's own script has drawn what the steps point at.
    const go = () => quietly(decision.index);
    if (document.readyState === "complete") window.setTimeout(go, 0);
    else window.addEventListener("load", () => window.setTimeout(go, 0));
  } else if (decision.action === "offer") {
    offer();
  }
}

if (typeof document !== "undefined") {
  window.botbuilderTour = { start: startTour, current: () => running };
  begin();
}
