// SPDX-License-Identifier: MIT
// Admin page: every build and every printable part with its mark, and a
// button that opens the "Mark a build as validated" issue form on GitHub
// with the fields filled in. The page holds no token and no login code and
// changes nothing by itself: the mark is recorded by a workflow that applies
// the repository owner's own submissions only.

import { buildSelection, evaluate, search } from "./build.js";

// The address of the issue form with its fields filled in from the query
// string. Field ids are those of .github/ISSUE_TEMPLATE/validated.yml.
export function issueLink(repoUrl, fields) {
  const query = new URLSearchParams({ template: "validated.yml", title: `Validated: ${fields.part || fields.build}` });
  query.set("build", fields.build);
  if (fields.part) query.set("part", fields.part);
  query.set("date", fields.date);
  return `${repoUrl}issues/new?${query.toString()}`;
}

// One row per build (the finished builds, then the other rows of the support
// table) and one per printable part.
export function adminRows(data) {
  const compat = data.compat;
  const text = (dimId, optionId) => compat.dimensions.find((dim) => dim.id === dimId).options.find((option) => option.id === optionId).label;
  const rows = [];
  // The finished builds of the landing page first, by name.
  const named = new Set();
  for (const entry of data.builds.list) {
    const recipe = evaluate(data, buildSelection(data, entry));
    if (named.has(recipe.build)) continue;
    named.add(recipe.build);
    const record = data.validated.find((item) => item.id === recipe.build && !item.part);
    rows.push({
      kind: "build",
      build: recipe.build,
      part: "",
      name: entry.name,
      detail: `${recipe.labels.controller}: ${recipe.labels.locomotion}, ${recipe.labels.drive}`,
      tag: recipe.status_label,
      link: `./?build=${entry.id}`,
      thumb: `./${entry.picture}`,
      record: record || null,
    });
  }
  for (const row of compat.support) {
    const build = `${row.controller}-${row.locomotion}-${row.drive}`;
    if (named.has(build)) continue;
    const sel = search(data, { controller: row.controller, locomotion: row.locomotion, drive: row.drive }, ["controller", "locomotion", "drive"]);
    if (sel === null) continue;
    const recipe = evaluate(data, sel);
    const record = data.validated.find((item) => item.id === build && !item.part);
    rows.push({
      kind: "build",
      build,
      part: "",
      name: `${text("controller", row.controller)}: ${text("locomotion", row.locomotion)}`,
      detail: text("drive", row.drive),
      tag: recipe.status_label,
      link: `./?${recipe.query}`,
      thumb: null,
      record: record || null,
    });
  }
  for (const entry of data.manifest.files) {
    const about = data.manifest.info[entry.file] || { thumb: null, size: "" };
    // A part is recorded against the first build that prints it; the mark shows on the part wherever it is used.
    const record = data.validated.find((item) => item.part === entry.file);
    rows.push({
      kind: "part",
      build: record ? record.id : "",
      part: entry.file,
      name: entry.file,
      detail: [entry.what, about.size].filter(Boolean).join(", "),
      tag: entry.fit ? "Fit piece" : "Part",
      link: `./stl/${entry.file}`,
      thumb: about.thumb,
      record: record || null,
    });
  }
  return rows;
}

function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

async function start() {
  const list = document.getElementById("admin-list");
  let data;
  try {
    const response = await fetch("./data/recipe.json");
    if (!response.ok) throw new Error(String(response.status));
    data = await response.json();
  } catch (error) {
    list.textContent = "The site data did not load.";
    return;
  }
  const repoUrl = data.compat.repo_url;
  const today = new Date().toISOString().slice(0, 10);
  const rows = adminRows(data);
  const defaultBuild = rows.length ? rows[0].build : "";
  const filter = document.getElementById("admin-filter");
  const unmarked = document.getElementById("admin-unmarked");

  const draw = () => {
    const words = filter.value.trim().toLowerCase().split(/\s+/).filter(Boolean);
    list.replaceChildren();
    let shown = 0;
    for (const row of rows) {
      const marked = Boolean(row.record && row.record.mark);
      const haystack = `${row.name} ${row.detail} ${row.build} ${row.tag}`.toLowerCase();
      if (unmarked.checked && marked) continue;
      if (!words.every((word) => haystack.includes(word))) continue;
      shown += 1;
      const item = el("li", undefined, `admin-row admin-${row.kind}`);
      if (row.thumb) {
        const picture = document.createElement("img");
        picture.src = row.thumb;
        picture.alt = "";
        picture.width = 80;
        picture.height = 60;
        picture.loading = "lazy";
        item.append(picture);
      }
      const text = el("div", undefined, "admin-text");
      const name = el("a", row.name);
      name.href = row.link;
      const title = el("p", undefined, "admin-name");
      title.append(name, document.createTextNode(` (${row.tag})`));
      text.append(title, el("p", row.detail, "part-facts"));
      if (row.record) {
        const words2 = row.record.mark ? `Printed and checked on ${row.record.date}` : `Note of ${row.record.date}, no mark`;
        text.append(el("p", row.record.checked ? `${words2}: ${row.record.checked}` : words2, row.record.mark ? "checked-mark" : "part-facts"));
      }
      item.append(text);
      const mark = el("a", marked ? "Change or remove" : "Mark validated", "secondary admin-mark");
      // A part needs a build id on the form; one that prints it, or the first build.
      mark.href = issueLink(repoUrl, { build: row.build || defaultBuild, part: row.part, date: today });
      mark.target = "_blank";
      mark.rel = "noopener";
      mark.setAttribute("aria-label", `${marked ? "Change or remove the mark for" : "Mark validated:"} ${row.name}, opens GitHub in a new tab`);
      item.append(mark);
      list.append(item);
    }
    document.getElementById("admin-count").textContent = `${shown} of ${rows.length} shown.`;
  };
  filter.addEventListener("input", draw);
  unmarked.addEventListener("change", draw);
  draw();
}

if (typeof document !== "undefined") start();
