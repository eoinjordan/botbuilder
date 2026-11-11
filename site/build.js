// SPDX-License-Identifier: MIT
// "Build yours" configurator. The evaluator below walks config/compat.json
// exactly as microduck/recipe.py does; tests/test_recipe.py runs both over
// every combination and compares them. No combination is written here: the
// page only shows what the data says. All paths are relative.

const SEARCH_DEPTH = 6;
const STORE_KEY = "microduck-build-yours";

// --- evaluator (mirror of microduck/recipe.py) ------------------------------

function matches(when, sel) {
  return Object.entries(when).every(([key, allowed]) => allowed.includes(sel[key]));
}

export function normalise(compat, selection) {
  const sel = {};
  for (const dim of compat.dimensions) {
    const value = selection[dim.id];
    sel[dim.id] = dim.options.some((option) => option.id === value) ? value : compat.defaults[dim.id];
  }
  for (const dim of compat.dimensions) {
    if (dim.only_for && !matches(dim.only_for, sel)) sel[dim.id] = compat.defaults[dim.id];
  }
  return sel;
}

function label(compat, dimId, optionId) {
  for (const dim of compat.dimensions) {
    if (dim.id !== dimId) continue;
    for (const option of dim.options) if (option.id === optionId) return option.label;
  }
  return optionId;
}

export function query(compat, sel) {
  const parts = [];
  for (const dim of compat.dimensions) {
    if (dim.only_for && !matches(dim.only_for, sel)) continue;
    parts.push(`${dim.id}=${sel[dim.id]}`);
  }
  return parts.join("&");
}

function amps(ma) {
  return `${Math.floor(ma / 1000)}.${String(Math.floor((ma % 1000) / 10)).padStart(2, "0")}`;
}

function fill(text, values) {
  let out = text;
  for (const [key, value] of Object.entries(values)) out = out.split(`{${key}}`).join(value);
  return out;
}

// The id of a build: one row of the support table.
export function buildId(sel) {
  return `${sel.controller}-${sel.locomotion}-${sel.drive}`;
}

function findRow(compat, sel) {
  for (const row of compat.support) {
    if (row.controller === sel.controller && row.locomotion === sel.locomotion && row.drive === sel.drive) return row;
  }
  return null;
}

function mostSpecific(entries, sel) {
  let best = null;
  for (const entry of entries) {
    const pairs = Object.entries(entry.match);
    if (pairs.every(([key, value]) => sel[key] === value)) {
      if (best === null || pairs.length > Object.keys(best.match).length) best = entry;
    }
  }
  return best;
}

function unsupported(data, sel) {
  const compat = data.compat;
  const rows = compat.support.filter((row) => row.controller === sel.controller);
  const matched = compat.why_not.filter((item) => matches(item.when, sel));
  const reasons = matched.map((item) => item.reason);
  // A controller the reports only carried on the biped as a block: say so, as a note.
  const reported = compat.support.some((row) => row.status === "report" && row.locomotion === sel.locomotion);
  if (reported && sel.controller in data.coverage.carried) reasons.push(data.coverage.carried[sel.controller]);
  const offered = rows
    .map((row) => `${label(compat, "locomotion", row.locomotion)} through ${label(compat, "drive", row.drive)}`)
    .join("; ");
  reasons.push(`With this controller: ${offered}.`);
  // The rows this controller does have, nearest first: same locomotion, then same drive, then the rest.
  const order = rows.filter((row) => row.locomotion === sel.locomotion)
    .concat(rows.filter((row) => row.locomotion !== sel.locomotion && row.drive === sel.drive))
    .concat(rows.filter((row) => row.locomotion !== sel.locomotion && row.drive !== sel.drive));
  return {
    blocked: true,
    reasons,
    alternatives: order.map((row) => ({ locomotion: row.locomotion, drive: row.drive })),
    codes: matched.length ? matched.map((item) => item.code) : ["not-offered"],
    short: matched.length ? matched[0].short : "Not available with this controller",
    details: matched.map((item) => ({ dims: Object.keys(item.when), short: item.short })),
    needs: matched.length > 0 && matched.every((item) => Boolean(item.needs)),
  };
}

// Why a normalised selection is refused, or null if it is possible. Cheap:
// the search for a neighbour calls it for every candidate.
function refusal(data, sel) {
  const compat = data.compat;
  if (findRow(compat, sel) === null) return unsupported(data, sel);
  const blocks = compat.rules.filter((rule) => "block" in rule && matches(rule.when, sel));
  if (blocks.length) {
    const alternatives = [];
    for (const rule of blocks) alternatives.push(...rule.alternatives);
    return {
      blocked: true,
      reasons: blocks.map((rule) => rule.block),
      alternatives,
      codes: blocks.map((rule) => rule.code),
      short: blocks[0].short,
      details: blocks.map((rule) => ({ dims: Object.keys(rule.when), short: rule.short })),
      needs: blocks.every((rule) => Boolean(rule.needs)),
    };
  }
  return null;
}

function pass(data, sel) {
  const compat = data.compat;
  const refused = refusal(data, sel);
  if (refused !== null) return refused;
  const row = findRow(compat, sel);
  const matched = compat.rules.filter((rule) => matches(rule.when, sel));

  let variant = null;
  let status;
  const reasons = [row.reason];
  const lead = [];
  if (row.status === "summary") {
    variant = mostSpecific(data.variants, sel);
    if (variant === null) {
      status = "being_analysed";
      lead.push("In analysis: mass, stability and speed appear here when the summary is ready.");
    } else {
      status = variant.status;
      lead.push(`From the variants summary, status as written there: ${variant.status_text}.`);
      lead.push(...variant.lines);
    }
  } else if (row.status === "report") {
    const covered = data.coverage.entries.find((entry) =>
      Object.entries(entry.match).every(([key, value]) => sel[key] === value));
    if (covered === undefined) {
      status = "defined";
      lead.push("No analysis numbers for this controller, camera and head together.");
    } else {
      status = covered.status;
      lead.push(...covered.lines);
    }
  } else {
    status = row.status;
    lead.push("No analysis numbers for this selection.");
  }
  const written = data.programs.filter((entry) => Object.entries(entry.match).every(([key, value]) => sel[key] === value));
  const program = written.length ? written[0] : null;
  const sections = {};
  for (const name of compat.sections) sections[name] = [];
  sections.analysis.push(...lead);
  for (const entry of written) sections.firmware.push(...entry.lines);
  const settings = { mechanism: "", preset: "" };
  const rails = {};
  const loads = [];
  for (const rule of matched) {
    if (rule.downgrade && (status === "analysed" || status === "assembly_only")) status = "defined";
    if ("reason" in rule) reasons.push(rule.reason);
    for (const [key, value] of Object.entries(rule.set || {})) settings[key] = value;
    for (const [key, value] of Object.entries(rule.rails || {})) if (!(key in rails)) rails[key] = value;
    loads.push(...(rule.loads || []));
    for (const [name, items] of Object.entries(rule.add || {})) {
      // A summary entry lists the whole build; the rules then add only what it does not
      // know about (the camera and head chosen here).
      if (variant !== null && (name === "print" || name === "parts") && !rule.extra) continue;
      sections[name].push(...items);
    }
    if (program === null) {
      for (const [name, items] of Object.entries(rule.without_program || {})) sections[name].push(...items);
    }
  }
  if (variant !== null) {
    sections.print.push(...variant.files);
    sections.parts.push(...variant.parts);
  }

  // Supply sizing, one line per rail in order of first use.
  const sizing = [];
  const order = [];
  for (const load of loads) if (!order.includes(load.rail)) order.push(load.rail);
  for (const railId of order) {
    const rail = rails[railId];
    const mine = loads.filter((load) => load.rail === railId);
    const known = mine.filter((load) => load.stall_ma !== null);
    const unknown = mine.filter((load) => load.stall_ma === null);
    const total = known.reduce((sum, load) => sum + load.qty * load.stall_ma, 0);
    let line = `${rail.label}: `;
    if (known.length) {
      const terms = known.map((load) => `${load.qty} x ${amps(load.stall_ma)} A ${load.what}`).join(" + ");
      line += `stalled demand ${amps(total)} A (${terms}).`;
    } else {
      line += "size it for the stall current of what it feeds.";
    }
    if (unknown.length) {
      line += ` Add the stall current of: ${unknown.map((load) => `${load.qty} x ${load.what}`).join("; ")}.`;
    }
    if (rail.limit_ma !== null && known.length) {
      if (total > rail.limit_ma) {
        const tenths = Math.floor((total * 10) / rail.limit_ma);
        line +=
          ` That is ${Math.floor(tenths / 10)}.${tenths % 10} times the ${rail.limit_label}, ` +
          `${amps(rail.limit_ma)} A: size the supply and wiring for the stall figure, or fuse it.`;
      } else {
        line += ` Within the ${rail.limit_label}, ${amps(rail.limit_ma)} A.`;
      }
    }
    sizing.push(line);
  }
  sections.power = sizing.concat(sections.power);

  // Files to print: fit-test pieces first, linked when the manifest has them.
  const listing = data.manifest;
  const wanted = [];
  let noTorso = false;
  for (const item of sections.print) {
    if (!item.from_manifest) {
      wanted.push(item);
      continue;
    }
    // The committed biped parts, chosen by the option fields the manifest gives each file.
    const maps = compat.manifest_map;
    const controller = sel.controller in maps.controller ? maps.controller[sel.controller] : null;
    const head = sel.head in maps.head ? maps.head[sel.head] : null;
    // The biped's files are those with no locomotion option; the walkers' and wheeled parts have one.
    const ownFiles = listing.files.filter((entry) => entry.locomotion === null);
    const torsos = ownFiles.filter(
      (entry) => entry.part === "torso" && entry.controller === controller && entry.head === head);
    const known = ownFiles.filter((entry) => entry.part === "torso" && entry.camera !== null).map((entry) => entry.camera);
    let own = false;
    let torso = null;
    if (head === null) {
      // A fixed mount: the torso of the selected camera, or of the default camera when the
      // selection is not a camera a torso is made for (the mount is then left empty).
      own = torsos.some((entry) => entry.camera === sel.camera);
      const camera = known.includes(sel.camera) ? sel.camera : listing.camera_default;
      const found = torsos.find((entry) => entry.camera === camera);
      if (found) torso = found.file;
    } else if (torsos.length) {
      torso = torsos[0].file;
    }
    if (torso === null) noTorso = true;
    for (const entry of ownFiles) {
      const general = entry.controller === null && entry.head === null;
      let take;
      if (entry.part === "torso") take = entry.file === torso;
      else if (general && entry.camera === null) take = true; // legs and the fit pieces every build needs
      else if (general && entry.fit) take = head === null && own && entry.camera === sel.camera;
      else if (entry.head !== null && entry.controller === null) {
        take = entry.head === head && (entry.camera === null || entry.camera === sel.camera);
      } else take = false;
      if (take) wanted.push({ file: entry.file, qty: 1, role: entry.what, fit: entry.fit });
    }
  }
  if (noTorso) {
    if (status === "analysed" || status === "assembly_only") status = "defined";
    reasons.push(
      "No torso file is in stl/ for this controller with this camera and head. The design's generator " +
        "makes one (CONTROLLER, CAMERA and the head option in build.py).");
  }
  const marks = {};
  for (const record of data.validated) if (record.part && record.mark) marks[record.part] = record.date;
  let files = [];
  for (const item of wanted) {
    let name = item.file;
    if (item.folder && settings.preset) name = `${settings.preset}/${name}`;
    let link = null;
    let about = { thumb: null, size: "", note: "" };
    for (const path of listing.paths) {
      if (path === name || path.endsWith(`/${name}`)) {
        // Files the site build copies are linked on the site; others in the repository.
        link = listing.served.includes(path) ? `./stl/${path}` : `${compat.repo_blob}stl/${path}`;
        if (path in listing.info) about = listing.info[path];
        break;
      }
    }
    files.push({ file: name, qty: item.qty, role: item.role, fit: Boolean(item.fit), link,
      thumb: about.thumb, size: about.size, note: about.note, validated: name in marks ? marks[name] : "" });
  }
  files = files.filter((item) => item.fit).concat(files.filter((item) => !item.fit));
  let note;
  if (!files.length) note = "No printable files are in stl/ for this selection yet.";
  else if (listing.present) note = "Linked files are in the repository's stl/ directory. A name without a link is not there yet.";
  else note = "File names only.";

  const base = data.bases.bases[row.base];
  const values = { ...data.facts, robot_creator: compat.robot_creator };
  let mark = null;
  for (const record of data.validated) {
    if (record.id === buildId(sel) && !record.part && record.mark) {
      mark = { date: record.date, checked: record.checked, photo: record.photo };
    }
  }
  const out = {
    blocked: false,
    status,
    reasons: reasons.map((text) => fill(text, values)),
    base: row.base,
    build: buildId(sel),
    validated: mark,
    sources: base.sources,
    mechanism: settings.mechanism,
    preset: settings.preset,
    print: { note, files },
    parts: sections.parts,
  };
  for (const name of compat.sections) {
    if (name !== "print" && name !== "parts") out[name] = sections[name].map((text) => fill(text, values));
  }
  return out;
}

// The nearest possible selection, keeping the pinned choices as they are:
// follow the alternatives each block offers, depth first, and stop at the
// first selection that is not blocked. null if the pinned choices cannot be
// part of any possible selection.
export function search(data, selection, pinned) {
  const compat = data.compat;
  const start = normalise(compat, selection);
  const order = compat.dimensions.map((dim) => dim.id);
  const seen = new Set();
  const walk = (current, depth) => {
    const result = refusal(data, current);
    if (result === null) return current;
    if (depth === 0) return null;
    for (const alternative of result.alternatives) {
      if (Object.entries(alternative).some(([key, value]) => pinned.includes(key) && start[key] !== value)) continue;
      const following = normalise(compat, { ...current, ...alternative });
      const key = order.map((name) => following[name]).join("|");
      if (seen.has(key)) continue;
      seen.add(key);
      const found = walk(following, depth - 1);
      if (found !== null) return found;
    }
    return null;
  };
  return walk(start, SEARCH_DEPTH);
}

// Whether an option can be chosen with the current controller, and what the
// selection becomes if it is. Not possible: the short reason.
export function optionState(data, selection, dimId, optionId) {
  const candidate = { ...normalise(data.compat, selection), [dimId]: optionId };
  const found = search(data, candidate, ["controller", dimId]);
  if (found !== null) return { enabled: true, selection: found, short: "" };
  const result = pass(data, normalise(data.compat, candidate));
  const about = result.details.find((item) => item.dims.includes(dimId));
  return { enabled: false, selection: null, short: about ? about.short : result.short };
}

export function evaluate(data, selection) {
  const compat = data.compat;
  const sel = normalise(compat, selection);
  const first = pass(data, sel);
  const labels = {};
  for (const dim of compat.dimensions) labels[dim.id] = label(compat, dim.id, sel[dim.id]);
  const recipe = {
    selection: sel,
    labels,
    query: query(compat, sel),
    trademarks: compat.trademarks,
  };
  if (!first.blocked) {
    Object.assign(recipe, first);
    delete recipe.blocked;
    recipe.status_label = compat.statuses[recipe.status].label;
    recipe.headline = compat.statuses[recipe.status].headline;
    recipe.refusal = [];
    recipe.nearest = null;
    return recipe;
  }

  let near = search(data, sel, ["controller"]);
  if (near === null) near = search(data, sel, []);
  if (near === null) near = normalise(compat, compat.defaults);
  const result = pass(data, near);
  const status = first.needs ? "needs_part" : "not_possible";
  const changes = compat.dimensions
    .filter((dim) => near[dim.id] !== sel[dim.id])
    .map((dim) => `${dim.label}: ${label(compat, dim.id, near[dim.id])}`);
  Object.assign(recipe, {
    status,
    status_label: compat.statuses[status].label,
    headline: compat.statuses[status].headline,
    reasons: first.reasons,
    refusal: first.codes,
    base: null,
    build: buildId(sel),
    validated: null,
    sources: [],
    mechanism: "",
    preset: "",
    print: { note: "", files: [] },
    parts: [],
    nearest: {
      selection: near,
      query: query(compat, near),
      status: result.status,
      status_label: compat.statuses[result.status].label,
      changes,
    },
  });
  for (const name of compat.sections) {
    if (name !== "print" && name !== "parts") recipe[name] = [];
  }
  return recipe;
}

// --- page -------------------------------------------------------------------

const SECTION_TITLES = {
  wiring: "Wiring",
  power: "Power and supply sizing",
  firmware: "Firmware and software",
  analysis: "Analysis",
  assembly: "Assembly",
};

function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function readStored() {
  try {
    return JSON.parse(window.localStorage.getItem(STORE_KEY) || "{}") || {};
  } catch (error) {
    return {};
  }
}

function store(sel) {
  try {
    window.localStorage.setItem(STORE_KEY, JSON.stringify(sel));
  } catch (error) {
    // Private mode or storage disabled: the URL still carries the selection.
  }
}

function fromUrl() {
  const found = {};
  for (const [key, value] of new URLSearchParams(window.location.search)) found[key] = value;
  return found;
}

function buildForm(data, form, onChange) {
  const controls = {};
  for (const dim of data.compat.dimensions) {
    const wrap = el("div", undefined, "field");
    const name = el("label", dim.label);
    name.htmlFor = `pick-${dim.id}`;
    const select = document.createElement("select");
    select.id = `pick-${dim.id}`;
    select.name = dim.id;
    for (const option of dim.options) {
      const item = el("option", option.label);
      item.value = option.id;
      select.append(item);
    }
    select.addEventListener("change", onChange);
    wrap.append(name, select);
    form.append(wrap);
    controls[dim.id] = select;
  }
  return controls;
}

// Every option is either selectable (choosing it brings the other fields to
// a compatible state) or greyed out with its short reason. Returns the
// greyed-out ones for the list under the form.
function syncForm(data, controls, sel) {
  const compat = data.compat;
  const greyed = [];
  for (const dim of compat.dimensions) {
    const select = controls[dim.id];
    select.value = sel[dim.id];
    select.disabled = Boolean(dim.only_for) && !matches(dim.only_for, sel);
    for (const item of select.options) {
      if (select.disabled || item.value === sel[dim.id]) {
        item.disabled = false;
        item.title = "";
        continue;
      }
      const state = optionState(data, sel, dim.id, item.value);
      item.disabled = !state.enabled;
      item.title = state.short;
      if (!state.enabled) greyed.push([item.textContent, state.short]);
    }
  }
  return greyed;
}

// Text with any web address in it turned into a link that opens in a new tab.
function withLinks(node, text) {
  const pieces = text.split(/(https:\/\/[^\s]+[^\s.,;:)])/);
  pieces.forEach((piece, i) => {
    if (i % 2 === 0) {
      node.append(document.createTextNode(piece));
      return;
    }
    const link = el("a", piece);
    link.href = piece;
    link.target = "_blank";
    link.rel = "noopener";
    link.setAttribute("aria-label", `${piece}, opens in a new tab`);
    node.append(link);
  });
  return node;
}

function list(items, className) {
  const ul = el("ul", undefined, className || "plain");
  for (const text of items) ul.append(withLinks(el("li"), text));
  return ul;
}

function block(title, node) {
  const wrap = el("div", undefined, "recipe-block");
  wrap.append(el("h3", title), node);
  return wrap;
}

function render(data, recipe, target) {
  target.replaceChildren();
  const verdict = el("div", undefined, `verdict verdict-${recipe.status}`);
  verdict.append(el("p", "STATUS", "eyebrow"), el("h2", recipe.status_label), el("p", recipe.headline));
  if (recipe.validated) {
    // Shown only when the owner has recorded a check of this build.
    verdict.append(el("p", `Printed and checked on ${recipe.validated.date}${recipe.validated.checked ? `: ${recipe.validated.checked}` : "."}`, "checked-mark"));
    if (recipe.validated.photo) {
      const photo = document.createElement("img");
      photo.src = `./${recipe.validated.photo}`;
      photo.alt = `The build as printed and checked on ${recipe.validated.date}`;
      photo.loading = "lazy";
      photo.className = "checked-photo";
      verdict.append(photo);
    }
  }
  verdict.append(list(recipe.reasons));
  if (recipe.nearest) {
    const near = el("p", undefined, "nearest");
    near.append(document.createTextNode("Nearest possible selection: "));
    const link = el("a", recipe.nearest.changes.join("; "));
    link.href = `?${recipe.nearest.query}`;
    link.dataset.query = recipe.nearest.query;
    near.append(link, document.createTextNode(` (${recipe.nearest.status_label}).`));
    verdict.append(near);
  }
  target.append(verdict);

  const chosen = el("dl", undefined, "facts");
  for (const dim of data.compat.dimensions) {
    if (dim.only_for && !matches(dim.only_for, recipe.selection)) continue;
    const box = document.createElement("div");
    box.append(el("dt", dim.label), el("dd", recipe.labels[dim.id]));
    chosen.append(box);
  }
  target.append(chosen);
  if (recipe.nearest) return;

  const what = el("div");
  what.append(el("p", recipe.mechanism));
  const more = data.compat.locomotion_pages[recipe.selection.locomotion];
  if (more) {
    const para = el("p", undefined, "type-link no-print");
    const link = el("a", more.text);
    link.href = `./${more.page}`;
    para.append(link);
    what.append(para);
  }
  target.append(block("What this is", what));

  const print = el("div");
  print.append(el("p", recipe.print.note, "small-note flush"));
  if (recipe.print.files.length) {
    if (recipe.preset) print.append(el("p", `Preset: ${recipe.preset}`, "small-note flush"));
    const cards = el("ul", undefined, "part-cards");
    for (const item of recipe.print.files) {
      const card = el("li", undefined, item.fit ? "part-card fit" : "part-card");
      if (item.thumb) {
        const picture = document.createElement("img");
        picture.src = item.thumb;
        picture.alt = item.role;
        picture.width = 320;
        picture.height = 240;
        picture.loading = "lazy";
        card.append(picture);
      } else {
        card.append(el("div", "No picture yet", "part-nopicture"));
      }
      const text = el("div", undefined, "part-text");
      if (item.fit) text.append(el("p", "Print first: fit test", "part-first"));
      const name = el("h4");
      if (item.link) {
        const link = el("a", item.file);
        link.href = item.link;
        if (item.link.startsWith("./")) link.download = "";
        else link.rel = "noopener noreferrer";
        name.append(link);
      } else {
        name.textContent = item.file;
      }
      text.append(name, el("p", item.role));
      text.append(el("p", item.size ? `Print ${item.qty}, ${item.size}` : `Print ${item.qty}`, "part-facts"));
      if (item.note) text.append(el("p", item.note, "part-facts"));
      if (item.validated) text.append(el("p", `Printed and checked on ${item.validated}`, "checked-mark"));
      card.append(text);
      cards.append(card);
    }
    print.append(cards);
  }
  target.append(block("Files to print", print));

  const parts = el("table");
  const head = el("tr");
  for (const name of ["Part", "Qty", "Note"]) head.append(el("th", name));
  parts.append(head);
  for (const item of recipe.parts) {
    const tr = el("tr");
    tr.append(el("td", item.name), el("td", item.qty === null ? "not set" : String(item.qty)), el("td", item.note));
    parts.append(tr);
  }
  const partsScroll = el("div", undefined, "table-wrap wrap-cells");
  partsScroll.append(parts);
  target.append(block("Parts", partsScroll));

  for (const name of data.compat.sections) {
    if (!(name in SECTION_TITLES)) continue;
    if (name === "assembly") {
      const steps = el("ol", undefined, "steps");
      for (const text of recipe[name]) steps.append(el("li", text));
      target.append(block(SECTION_TITLES[name], steps));
    } else {
      const section = block(SECTION_TITLES[name], list(recipe[name]));
      if (name === "firmware" && recipe.base) {
        // The Flash page builds the commands for this controller, or says
        // that none are written.
        const link = el("a", "Flash steps for this controller");
        link.href = `./flash.html?base=${encodeURIComponent(recipe.base)}`;
        const para = el("p");
        para.append(link);
        section.append(para);
      }
      target.append(section);
    }
  }

  if (recipe.sources.length) {
    const sources = el("ul", undefined, "plain");
    for (const url of recipe.sources) {
      const li = el("li");
      const link = el("a", url);
      link.href = url;
      link.rel = "noopener noreferrer";
      li.append(link);
      sources.append(li);
    }
    target.append(block("Maker documentation for this base", sources));
  }
}

async function start() {
  const output = document.getElementById("recipe");
  let data;
  try {
    const response = await fetch("./data/recipe.json");
    if (!response.ok) throw new Error(String(response.status));
    data = await response.json();
  } catch (error) {
    output.textContent = "The recipe data did not load. Run python scripts/build_site.py and serve the site directory.";
    return;
  }
  const compat = data.compat;
  // A linked recipe is the address alone; the remembered one is used only without it.
  const linked = fromUrl();
  let sel = normalise(compat, Object.keys(linked).length ? linked : readStored());
  // A link that names only some fields (a type page's "?locomotion=wheeled") keeps those and takes
  // compatible values for the rest. A link that names a contradiction gets the plain answer.
  const named = compat.dimensions.map((dim) => dim.id).filter((id) => id in linked);
  if (named.length && named.length < compat.dimensions.filter((dim) => !dim.only_for).length) {
    const fitted = search(data, sel, named);
    if (fitted !== null) sel = fitted;
  }
  let recipe;

  const show = (push) => {
    recipe = evaluate(data, sel);
    sel = recipe.selection;
    const greyed = syncForm(data, controls, sel);
    const why = document.getElementById("greyed");
    why.replaceChildren();
    why.hidden = greyed.length === 0;
    if (greyed.length) {
      why.append(el("summary", "Why some options are greyed out"));
      const reasons = el("ul", undefined, "plain");
      for (const [name, reason] of greyed) reasons.append(el("li", `${name}: ${reason}`));
      why.append(reasons);
    }
    render(data, recipe, output);
    document.getElementById("trademarks").textContent = recipe.trademarks;
    if (push) window.history.replaceState(null, "", `?${recipe.query}`);
    store(sel);
  };
  const controls = buildForm(data, document.getElementById("picker"), (event) => {
    const next = {};
    for (const dim of compat.dimensions) next[dim.id] = controls[dim.id].value;
    const before = sel;
    // The field that was changed stays as chosen, and so does the controller; the other
    // fields move to the nearest compatible state. A link is never adjusted this way.
    const found = search(data, next, ["controller", event.target.name]);
    sel = found === null ? normalise(compat, next) : found;
    const moved = compat.dimensions
      .filter((dim) => dim.id !== event.target.name && sel[dim.id] !== normalise(compat, next)[dim.id])
      .map((dim) => `${dim.label}: ${label(compat, dim.id, sel[dim.id])}`);
    document.getElementById("action-note").textContent = moved.length && before ? `Also changed to fit: ${moved.join("; ")}.` : "";
    show(true);
  });
  show(window.location.search.length > 1);

  output.addEventListener("click", (event) => {
    const link = event.target.closest("a[data-query]");
    if (!link) return;
    event.preventDefault();
    const next = {};
    for (const [key, value] of new URLSearchParams(link.dataset.query)) next[key] = value;
    sel = normalise(compat, next);
    show(true);
    document.getElementById("picker").querySelector("select").focus();
  });
  document.getElementById("reset").addEventListener("click", () => {
    sel = normalise(compat, compat.defaults);
    show(true);
  });
  document.getElementById("copy-link").addEventListener("click", async () => {
    const url = `${window.location.origin}${window.location.pathname}?${recipe.query}`;
    const note = document.getElementById("action-note");
    try {
      await navigator.clipboard.writeText(url);
      note.textContent = "Link copied.";
    } catch (error) {
      window.history.replaceState(null, "", `?${recipe.query}`);
      note.textContent = "Copy the address from the address bar.";
    }
  });
  const stem = () => `botbuilder-recipe-${recipe.query.replace(/[^a-z0-9]+/gi, "-")}`;
  const save = (bytes, type, name) => {
    const link = document.createElement("a");
    link.href = URL.createObjectURL(new Blob([bytes], { type }));
    link.download = name;
    document.body.append(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(link.href);
  };
  const bytesOf = async (path) => {
    const response = await fetch(path);
    if (!response.ok) throw new Error(`${path}: ${response.status}`);
    return new Uint8Array(await response.arrayBuffer());
  };
  const jsonText = () => `${JSON.stringify(recipe, null, 1)}\n`;
  // The PDF is written in the page by export.js: no library, nothing sent anywhere.
  const makePdf = async () => {
    const { recipePdf } = await import("./export.js");
    const images = {};
    for (const item of recipe.print.files) {
      if (!item.thumb || item.thumb in images) continue;
      try {
        images[item.thumb] = await bytesOf(item.thumb);
      } catch (error) {
        images[item.thumb] = null;                 // the PDF leaves that box empty
      }
    }
    return recipePdf(recipe, images, {
      url: `${window.location.origin}${window.location.pathname}?${recipe.query}`,
      date: new Date().toISOString().slice(0, 10),
      selection: compat.dimensions
        .filter((dim) => !dim.only_for || matches(dim.only_for, recipe.selection))
        .map((dim) => [dim.label, recipe.labels[dim.id]]),
      titles: compat.sections.filter((name) => name in SECTION_TITLES).map((name) => [name, SECTION_TITLES[name]]),
    });
  };
  const busy = async (button, work) => {
    const note = document.getElementById("action-note");
    button.disabled = true;
    note.textContent = "Working.";
    try {
      note.textContent = await work();
    } catch (error) {
      note.textContent = `That did not work (${error.message}). The Print button and your browser's Save as PDF give the same recipe.`;
    }
    button.disabled = false;
  };
  document.getElementById("download").addEventListener("click", () => save(jsonText(), "application/json", `${stem()}.json`));
  document.getElementById("download-pdf").addEventListener("click", (event) => busy(event.currentTarget, async () => {
    save(await makePdf(), "application/pdf", `${stem()}.pdf`);
    return "PDF saved.";
  }));
  document.getElementById("download-all").addEventListener("click", (event) => busy(event.currentTarget, async () => {
    const { zipStore } = await import("./export.js");
    const entries = [
      { name: "recipe.pdf", data: await makePdf() },
      { name: "recipe.json", data: new TextEncoder().encode(jsonText()) },
    ];
    const left = [];
    for (const item of recipe.print.files) {
      // Only files this site serves; a part that is only named, or kept elsewhere, is listed instead.
      if (!item.link || !item.link.startsWith("./")) {
        left.push(item.file);
        continue;
      }
      try {
        entries.push({ name: `stl/${item.file}`, data: await bytesOf(item.link) });
      } catch (error) {
        left.push(item.file);
      }
    }
    const lines = ["Botbuilder recipe", `${window.location.origin}${window.location.pathname}?${recipe.query}`, "",
      "recipe.pdf   the recipe with the part pictures", "recipe.json  the same recipe as data",
      `stl/         ${entries.length - 2} printable files, quantities in the recipe`];
    if (left.length) lines.push("", "Not in this zip (no file on the site):", ...left.map((name) => `  ${name}`));
    entries.push({ name: "README.txt", data: new TextEncoder().encode(`${lines.join("\n")}\n`) });
    save(zipStore(entries, new Date()), "application/zip", `${stem()}.zip`);
    return left.length ? `Zip saved; ${left.length} files are not on the site and are listed in its README.` : "Zip saved.";
  }));
  document.getElementById("print").addEventListener("click", () => window.print());
}

if (typeof document !== "undefined" && document.getElementById("picker")) start();
