// SPDX-License-Identifier: MIT
// "Build yours" configurator. The evaluator below walks config/compat.json
// exactly as microduck/recipe.py does; tests/test_recipe.py runs both over
// every combination and compares them. No combination is written here: the
// page only shows what the data says. All paths are relative.

const MAX_NEAREST_STEPS = 8;
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

function findRow(compat, sel) {
  for (const row of compat.support) {
    if (row.controller === sel.controller && row.locomotion === sel.locomotion && row.drive === sel.drive) return row;
  }
  return null;
}

function findVariant(entries, sel) {
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
  const offered = rows
    .map((row) => `${label(compat, "locomotion", row.locomotion)} through ${label(compat, "drive", row.drive)}`)
    .join("; ");
  const reasons = [
    `${label(compat, "controller", sel.controller)} is not offered as '${label(compat, "locomotion", sel.locomotion)}'` +
      ` through '${label(compat, "drive", sel.drive)}'. Offered for this controller: ${offered}.`,
  ];
  for (const item of compat.why_not) if (matches(item.when, sel)) reasons.push(item.reason);
  // A controller the reports only carried on the biped as a block: say so, as a note.
  const reported = compat.support.some((row) => row.status === "report" && row.locomotion === sel.locomotion);
  if (reported && sel.controller in data.coverage.carried) reasons.push(data.coverage.carried[sel.controller]);
  const pick =
    rows.find((row) => row.locomotion === sel.locomotion) || rows.find((row) => row.drive === sel.drive) || rows[0];
  return { reasons, nearest: { locomotion: pick.locomotion, drive: pick.drive } };
}

function pass(data, sel) {
  const compat = data.compat;
  const row = findRow(compat, sel);
  if (row === null) {
    const blocked = unsupported(data, sel);
    return { blocked: true, reasons: blocked.reasons, nearest: blocked.nearest };
  }
  const matched = compat.rules.filter((rule) => matches(rule.when, sel));
  const blocks = matched.filter((rule) => "block" in rule);
  if (blocks.length) {
    const nearest = {};
    for (const rule of blocks) Object.assign(nearest, rule.nearest);
    return { blocked: true, reasons: blocks.map((rule) => rule.block), nearest };
  }

  let variant = null;
  let status;
  const reasons = [row.reason];
  const lead = [];
  if (row.status === "summary") {
    variant = findVariant(data.variants, sel);
    if (variant === null) {
      status = "being_analysed";
      reasons.push("No analysis summary exists in reports/ yet for this base and locomotion.");
      lead.push("Being analysed: no summary file exists in reports/ yet. No mass, stability or speed figure is given here.");
    } else {
      status = variant.status;
      lead.push(`From the variants summary in reports/, status as written there: ${variant.status_text}.`);
      lead.push(...variant.lines);
      if (status !== "analysed") {
        lead.push("Not analysed to a verdict yet: the summary does not report this variant as analysed.");
      }
    }
  } else if (row.status === "report") {
    const covered = data.coverage.entries.find((entry) =>
      Object.entries(entry.match).every(([key, value]) => sel[key] === value));
    if (covered === undefined) {
      status = "defined";
      lead.push("Not analysed: the reports do not cover this controller, camera and head together.");
    } else {
      status = covered.status;
      lead.push(...covered.lines);
    }
  } else {
    status = row.status;
    lead.push("Not analysed: no simulation or digital assembly exists for this selection.");
  }
  const sections = {};
  for (const name of compat.sections) sections[name] = [];
  sections.analysis.push(...lead);
  const settings = { mechanism: "", preset: "" };
  const rails = {};
  const loads = [];
  for (const rule of matched) {
    if (rule.downgrade && (status === "analysed" || status === "assembly_only")) status = "defined";
    if ("reason" in rule) reasons.push(rule.reason);
    for (const [key, value] of Object.entries(rule.set || {})) settings[key] = value;
    for (const [key, value] of Object.entries(rule.rails || {})) if (!(key in rails)) rails[key] = value;
    loads.push(...(rule.loads || []));
    for (const [name, items] of Object.entries(rule.add || {})) sections[name].push(...items);
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
      const terms = known.map((load) => `${load.qty} x ${amps(load.stall_ma)} A ${load.what}, ${load.basis}`).join(" + ");
      line += `stalled demand ${amps(total)} A (${terms}).`;
    } else {
      line += "stalled demand not known.";
    }
    if (unknown.length) {
      line += ` Not counted, stall current ${unknown.map((load) => `${load.basis}: ${load.qty} x ${load.what}`).join("; ")}.`;
    }
    if (rail.limit_ma !== null && known.length) {
      if (total > rail.limit_ma) {
        const tenths = Math.floor((total * 10) / rail.limit_ma);
        line +=
          ` That is ${Math.floor(tenths / 10)}.${tenths % 10} times the ${rail.limit_label}, ` +
          `${amps(rail.limit_ma)} A: size the supply and wiring for the stall figure, or fuse it.`;
      } else {
        line += ` Within the ${rail.limit_label}, ${amps(rail.limit_ma)} A, on these figures.`;
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
    const torsos = listing.files.filter(
      (entry) => entry.part === "torso" && entry.controller === controller && entry.head === head);
    const known = listing.files.filter((entry) => entry.camera !== null).map((entry) => entry.camera);
    let own = false;
    let torso = null;
    if (head === null) {
      // A fixed mount: the torso of the selected camera, or of the default camera when the
      // selection is not a camera the manifest knows (the mount is then left empty).
      own = torsos.some((entry) => entry.camera === sel.camera);
      const camera = known.includes(sel.camera) ? sel.camera : listing.camera_default;
      const found = torsos.find((entry) => entry.camera === camera);
      if (found) torso = found.file;
    } else if (torsos.length) {
      torso = torsos[0].file;
    }
    if (torso === null) noTorso = true;
    for (const entry of listing.files) {
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
      "No torso file is committed for this controller with this camera and head. The design's generator " +
        "would have to be run for it (CONTROLLER, CAMERA and the head option in build.py), and that part has not been checked.");
  }
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
      thumb: about.thumb, size: about.size, note: about.note });
  }
  files = files.filter((item) => item.fit).concat(files.filter((item) => !item.fit));
  let note;
  if (!files.length) {
    note = "No printable files are named for this selection yet: the design is in progress on another branch.";
  } else if (listing.present) {
    note = "Linked files are in the repository's stl/ directory; none has been printed. A name without a link is not in its manifest.";
  } else {
    note = "File names only: the repository has no STL manifest, so nothing is linked.";
  }

  const base = data.bases.bases[row.base];
  const values = data.facts;
  const out = {
    blocked: false,
    status,
    reasons: reasons.map((text) => fill(text, values)),
    base: row.base,
    base_name: base.name,
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
    not_built: compat.not_built,
    trademarks: compat.trademarks,
  };
  if (!first.blocked) {
    Object.assign(recipe, first);
    delete recipe.blocked;
    recipe.status_label = compat.statuses[recipe.status].label;
    recipe.headline = compat.statuses[recipe.status].headline;
    recipe.nearest = null;
    return recipe;
  }

  let near = { ...sel };
  let result = first;
  for (let step = 0; step < MAX_NEAREST_STEPS; step += 1) {
    near = normalise(compat, { ...near, ...result.nearest });
    result = pass(data, near);
    if (!result.blocked) break;
  }
  if (result.blocked) {
    near = normalise(compat, compat.defaults);
    result = pass(data, near);
  }
  const changes = compat.dimensions
    .filter((dim) => near[dim.id] !== sel[dim.id])
    .map((dim) => `${dim.label}: ${label(compat, dim.id, near[dim.id])}`);
  Object.assign(recipe, {
    status: "not_possible",
    status_label: compat.statuses.not_possible.label,
    headline: compat.statuses.not_possible.headline,
    reasons: first.reasons,
    base: null,
    base_name: "",
    sources: [],
    mechanism: "",
    preset: "",
    print: { note: "Nothing to print: the selection is not possible.", files: [] },
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

function offered(compat, sel, dim, optionId) {
  // Read from the support table only: is there a row for this controller
  // (and, for the drive, this locomotion) with the option?
  if (dim.id === "locomotion") {
    return compat.support.some((row) => row.controller === sel.controller && row.locomotion === optionId);
  }
  if (dim.id === "drive") {
    return compat.support.some(
      (row) => row.controller === sel.controller && row.locomotion === sel.locomotion && row.drive === optionId);
  }
  return true;
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

function syncForm(data, controls, sel) {
  const compat = data.compat;
  for (const dim of compat.dimensions) {
    const select = controls[dim.id];
    select.value = sel[dim.id];
    select.disabled = Boolean(dim.only_for) && !matches(dim.only_for, sel);
    for (const item of select.options) {
      const option = dim.options.find((candidate) => candidate.id === item.value);
      item.textContent = offered(compat, sel, dim, item.value) ? option.label : `${option.label} (not offered here)`;
    }
  }
}

function list(items, className) {
  const ul = el("ul", undefined, className || "plain");
  for (const text of items) ul.append(el("li", text));
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
  verdict.append(el("p", recipe.not_built, "not-built"));
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
  if (recipe.status === "not_possible") return;

  target.append(block("What this is", el("p", recipe.mechanism)));

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
  let recipe;

  const show = (push) => {
    recipe = evaluate(data, sel);
    sel = recipe.selection;
    syncForm(data, controls, sel);
    render(data, recipe, output);
    document.getElementById("trademarks").textContent = recipe.trademarks;
    if (push) window.history.replaceState(null, "", `?${recipe.query}`);
    store(sel);
  };
  const controls = buildForm(data, document.getElementById("picker"), (event) => {
    const next = {};
    for (const dim of compat.dimensions) next[dim.id] = controls[dim.id].value;
    sel = normalise(compat, next);
    const note = document.getElementById("action-note");
    note.textContent = "";
    if (event.target.name === "controller") {
      // Switching only the controller: carry the other choices over where they are possible
      // and take the nearest possible ones where they are not, instead of answering "not
      // possible" to a combination nobody asked for. A link still gets the plain answer.
      const tried = evaluate(data, sel);
      if (tried.nearest) {
        sel = tried.nearest.selection;
        note.textContent = `Changed for this controller: ${tried.nearest.changes.join("; ")}.`;
      }
    }
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

if (typeof document !== "undefined") start();
