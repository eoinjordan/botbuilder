// SPDX-License-Identifier: MIT
// A recipe as a PDF file and as a zip, made in the browser with no library.
//
// recipePdf() writes a small PDF 1.4 document: real text in the standard
// Helvetica faces (so it can be searched and copied) and the part pictures.
// The pictures are the 8-bit PNGs of stl/thumbs; a PNG's compressed data is
// what a PDF image with a PNG predictor holds, so it is copied in unchanged.
// zipStore() writes an uncompressed zip. Both return a Uint8Array and touch
// neither the page nor the network, so tests run them under Node.

const PAGE_W = 595;
const PAGE_H = 842;
const MARGIN = 48;
const WIDE = PAGE_W - 2 * MARGIN;

// Helvetica advance widths for the characters 32 to 126, in 1/1000 em.
const WIDTHS = [
  278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278, 556, 556, 556, 556, 556, 556, 556, 556,
  556, 556, 278, 278, 584, 584, 584, 556, 1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833, 722, 778,
  667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469, 556, 333, 556, 556, 500, 556, 556, 278, 556,
  556, 222, 222, 500, 222, 833, 556, 556, 556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500, 334, 260, 334, 584,
];

function plain(text) {
  // The standard faces are used without embedding, so only ASCII is written.
  return String(text).replace(/[^\x20-\x7e]/g, "?");
}

function width(text, size, bold) {
  let total = 0;
  for (const ch of plain(text)) total += WIDTHS[ch.charCodeAt(0) - 32];
  return (total / 1000) * size * (bold ? 1.06 : 1);
}

function wrap(text, size, max, bold) {
  const lines = [];
  let line = "";
  for (let word of plain(text).split(" ")) {
    while (width(word, size, bold) > max) {
      // A word longer than the line (a URL, a file name): break it.
      let cut = word.length - 1;
      while (cut > 1 && width(word.slice(0, cut), size, bold) > max - width(line ? `${line} ` : "", size, bold)) cut -= 1;
      lines.push(line ? `${line} ${word.slice(0, cut)}` : word.slice(0, cut));
      line = "";
      word = word.slice(cut);
    }
    const next = line ? `${line} ${word}` : word;
    if (width(next, size, bold) > max && line) {
      lines.push(line);
      line = word;
    } else {
      line = next;
    }
  }
  if (line) lines.push(line);
  return lines;
}

function escape(text) {
  return plain(text).replace(/[\\()]/g, (ch) => `\\${ch}`);
}

function ascii(text) {
  const out = new Uint8Array(text.length);
  for (let i = 0; i < text.length; i += 1) out[i] = text.charCodeAt(i) & 0xff;
  return out;
}

function join(chunks) {
  const out = new Uint8Array(chunks.reduce((sum, chunk) => sum + chunk.length, 0));
  let at = 0;
  for (const chunk of chunks) {
    out.set(chunk, at);
    at += chunk.length;
  }
  return out;
}

// What a PDF needs from a PNG, or null for a PNG it cannot take as it is
// (interlaced, 16-bit, with an alpha channel).
export function readPng(bytes) {
  const signature = [137, 80, 78, 71, 13, 10, 26, 10];
  if (!bytes || bytes.length < 33 || signature.some((value, i) => bytes[i] !== value)) return null;
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  let at = 8;
  let header = null;
  let palette = null;
  const data = [];
  while (at + 8 <= bytes.length) {
    const length = view.getUint32(at);
    const type = String.fromCharCode(bytes[at + 4], bytes[at + 5], bytes[at + 6], bytes[at + 7]);
    const body = bytes.subarray(at + 8, at + 8 + length);
    if (type === "IHDR") {
      header = { width: view.getUint32(at + 8), height: view.getUint32(at + 12), bits: bytes[at + 16], colour: bytes[at + 17],
        interlace: bytes[at + 20] };
    } else if (type === "PLTE") palette = body;
    else if (type === "IDAT") data.push(body);
    else if (type === "IEND") break;
    at += 12 + length;
  }
  if (!header || header.interlace || header.bits > 8 || ![0, 2, 3].includes(header.colour) || !data.length) return null;
  if (header.colour === 3 && !palette) return null;
  return { width: header.width, height: header.height, bits: header.bits, colour: header.colour, palette, data: join(data) };
}

function hex(bytes) {
  let out = "";
  for (const value of bytes) out += value.toString(16).padStart(2, "0");
  return out;
}

class Layout {
  constructor() {
    this.pages = [];
    this.newPage();
  }

  newPage() {
    this.ops = [];
    this.pages.push(this.ops);
    this.y = PAGE_H - MARGIN;
  }

  need(height) {
    if (this.y - height < MARGIN + 18) this.newPage();
  }

  text(line, x, y, size, bold, grey) {
    this.ops.push(`BT /F${bold ? 2 : 1} ${size} Tf ${grey ? "0.41 0.48 0.46" : "0.09 0.17 0.17"} rg ${x.toFixed(1)} ${y.toFixed(1)} Td (${escape(line)}) Tj ET`);
  }

  para(text, options = {}) {
    const size = options.size || 10;
    const indent = options.indent || 0;
    const lines = wrap(text, size, WIDE - indent, options.bold);
    const lead = size * 1.4;
    lines.forEach((line, i) => {
      this.need(lead);
      this.y -= lead;
      if (i === 0 && options.mark) this.text(options.mark, MARGIN, this.y, size, false, true);
      this.text(line, MARGIN + indent, this.y, size, options.bold, options.grey);
    });
    this.y -= options.after === undefined ? 3 : options.after;
  }

  heading(text) {
    this.need(46);
    this.y -= 12;
    this.para(text, { size: 13, bold: true, after: 2 });
    this.ops.push(`0.84 0.89 0.86 RG 0.7 w ${MARGIN} ${(this.y - 1).toFixed(1)} m ${PAGE_W - MARGIN} ${(this.y - 1).toFixed(1)} l S`);
    this.y -= 5;
  }

  list(items, numbered) {
    items.forEach((item, i) => this.para(item, { indent: 16, mark: numbered ? `${i + 1}.` : "-" }));
  }
}

// recipe: what evaluate() in build.js returns. images: thumb path -> PNG
// bytes (a missing or unusable picture leaves its box empty). meta: { url,
// date, titles } where titles names the text sections; optionally parts (a
// picture path or null for each part of the recipe), credits (one line for
// each credited picture), creditsUrl, and logo (the path of the site's mark
// among the images, drawn at the top right of the first page).
export function recipePdf(recipe, images, meta) {
  const doc = new Layout();
  const pictures = [];             // { name, png }
  const pictureOf = {};
  // The index of a picture among the PDF's images, or -1 if it cannot be used.
  const use = (path) => {
    if (!path) return -1;
    if (!(path in pictureOf)) {
      const png = readPng(images[path]);
      pictureOf[path] = png ? pictures.push({ name: `Im${pictures.length + 1}`, png }) - 1 : -1;
    }
    return pictureOf[path];
  };

  const mark = use(meta.logo);
  if (mark >= 0) doc.ops.push(`q 40 0 0 40 ${PAGE_W - MARGIN - 40} ${PAGE_H - MARGIN - 40} cm /${pictures[mark].name} Do Q`);
  doc.para("Botbuilder recipe", { size: 9, grey: true, after: 0 });
  doc.para(`${recipe.labels.controller}: ${recipe.labels.locomotion}`, { size: 18, bold: true, after: 4 });
  doc.para(`Status: ${recipe.status_label}`, { size: 12, bold: true, after: 1 });
  doc.para(recipe.headline);
  if (recipe.validated) {
    // Only when the owner has recorded a check of this build.
    doc.para(`Printed and checked on ${recipe.validated.date}${recipe.validated.checked ? `: ${recipe.validated.checked}` : "."}`, { bold: true });
  }
  doc.list(recipe.reasons);
  if (recipe.nearest) {
    doc.para(`Nearest possible selection: ${recipe.nearest.changes.join("; ")} (${recipe.nearest.status_label}).`, { bold: true });
  }

  doc.heading("Selection");
  for (const [name, value] of meta.selection) doc.para(`${name}: ${value}`, { after: 0 });
  doc.y -= 4;

  if (!recipe.nearest) {
    doc.heading("What this is");
    doc.para(recipe.mechanism);

    doc.heading("Files to print");
    doc.para(recipe.print.note, { size: 9, grey: true });
    const columns = 3;
    const gap = 12;
    const cell = (WIDE - gap * (columns - 1)) / columns;
    const picW = cell;
    const picH = (cell * 3) / 4;
    for (let first = 0; first < recipe.print.files.length; first += columns) {
      const row = recipe.print.files.slice(first, first + columns).map((item) => {
        const facts = [`Print ${item.qty}`];
        if (item.size) facts.push(item.size);
        return {
          item,
          name: wrap(item.file, 8.5, cell, true),
          role: wrap(item.role, 8, cell, false),
          facts: wrap(facts.join("  |  "), 8, cell, false),
          note: wrap([item.note, item.validated ? `Printed and checked on ${item.validated}` : ""].filter(Boolean).join(" "), 8, cell, false),
        };
      });
      const lines = Math.max(...row.map((card) => card.name.length + card.role.length + card.facts.length + card.note.length + (card.item.fit ? 1 : 0)));
      const height = picH + 6 + lines * 11 + 12;
      doc.need(height);
      const top = doc.y;
      row.forEach((card, i) => {
        const x = MARGIN + i * (cell + gap);
        doc.ops.push(`0.84 0.89 0.86 RG 0.7 w ${x.toFixed(1)} ${(top - picH).toFixed(1)} ${picW.toFixed(1)} ${picH.toFixed(1)} re S`);
        const index = use(card.item.thumb);
        if (index >= 0) {
          doc.ops.push(`q ${picW.toFixed(1)} 0 0 ${picH.toFixed(1)} ${x.toFixed(1)} ${(top - picH).toFixed(1)} cm /${pictures[index].name} Do Q`);
        }
        let y = top - picH - 6;
        const put = (textLines, bold, grey) => {
          for (const line of textLines) {
            y -= 11;
            doc.text(line, x, y, bold ? 8.5 : 8, bold, grey);
          }
        };
        if (card.item.fit) put(["PRINT FIRST: fit test"], true, false);
        put(card.name, true, false);
        put(card.role, false, false);
        put(card.facts, false, true);
        put(card.note, false, true);
      });
      doc.y = top - height;
    }

    doc.heading("Parts");
    recipe.parts.forEach((part, i) => {
      // A bought part with a picture: the picture on the left, the text beside it.
      const index = use(meta.parts ? meta.parts[i] : null);
      const indent = index >= 0 ? 52 : 0;
      let top = 0;
      if (index >= 0) {
        doc.need(40);
        top = doc.y;
        doc.ops.push(`q 44 0 0 33 ${MARGIN} ${(top - 36).toFixed(1)} cm /${pictures[index].name} Do Q`);
      }
      doc.para(`${part.qty === null ? "-" : `${part.qty} x`} ${part.name}`, { bold: true, after: 0, indent });
      doc.para(part.note, { indent: indent + 16, size: 9, grey: true });
      if (index >= 0 && doc.y > top - 40 && doc.y < top) doc.y = top - 40;
    });
    for (const [key, title] of meta.titles) {
      if (!recipe[key] || !recipe[key].length) continue;
      doc.heading(title);
      doc.list(recipe[key], key === "assembly");
    }
    if (recipe.sources.length) {
      doc.heading("Maker documentation for this base");
      doc.list(recipe.sources, false);
    }
  }

  doc.heading("This recipe");
  doc.para(`Link: ${meta.url}`);
  doc.para(`Made on ${meta.date}.`);
  doc.para(recipe.trademarks, { size: 8, grey: true });
  if (meta.credits && meta.credits.length) {
    doc.heading("Picture credits");
    for (const line of meta.credits) doc.para(line, { size: 8, grey: true, after: 1 });
    if (meta.creditsUrl) doc.para(`All picture credits: ${meta.creditsUrl}`, { size: 8, grey: true });
  }

  // Objects: 1 catalog, 2 pages, 3 and 4 fonts, then pictures, then a content stream and a page for each page.
  const objects = [];
  const add = (body) => objects.push(body) + 0;
  add(null);
  add(null);
  add(ascii("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"));
  add(ascii("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>"));
  const xobjects = [];
  for (const { name, png } of pictures) {
    const colours = png.colour === 2 ? 3 : 1;
    let space = "/DeviceGray";
    if (png.colour === 2) space = "/DeviceRGB";
    if (png.colour === 3) space = `[/Indexed /DeviceRGB ${png.palette.length / 3 - 1} <${hex(png.palette)}>]`;
    const head = `<< /Type /XObject /Subtype /Image /Width ${png.width} /Height ${png.height} /ColorSpace ${space} ` +
      `/BitsPerComponent ${png.bits} /Filter /FlateDecode /DecodeParms << /Predictor 15 /Colors ${colours} ` +
      `/BitsPerComponent ${png.bits} /Columns ${png.width} >> /Length ${png.data.length} >>\nstream\n`;
    xobjects.push(`/${name} ${add(join([ascii(head), png.data, ascii("\nendstream")]))} 0 R`);
  }
  const kids = [];
  doc.pages.forEach((ops, i) => {
    ops.push(`BT /F1 8 Tf 0.41 0.48 0.46 rg ${MARGIN} 30 Td (${escape(`Botbuilder recipe, ${meta.date}. Page ${i + 1} of ${doc.pages.length}.`)}) Tj ET`);
    const stream = ops.join("\n");
    const content = add(ascii(`<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`));
    kids.push(add(ascii(`<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${PAGE_W} ${PAGE_H}] /Contents ${content} 0 R ` +
      `/Resources << /Font << /F1 3 0 R /F2 4 0 R >> /XObject << ${xobjects.join(" ")} >> >> >>`)));
  });
  objects[0] = ascii("<< /Type /Catalog /Pages 2 0 R >>");
  objects[1] = ascii(`<< /Type /Pages /Count ${kids.length} /Kids [${kids.map((id) => `${id} 0 R`).join(" ")}] >>`);
  const info = add(ascii(`<< /Title (${escape(`Botbuilder recipe: ${recipe.labels.controller}, ${recipe.labels.locomotion}`)}) /Producer (botbuilder site/export.js) >>`));

  const chunks = [ascii("%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")];
  let offset = chunks[0].length;
  const offsets = [];
  objects.forEach((body, i) => {
    const part = join([ascii(`${i + 1} 0 obj\n`), body, ascii("\nendobj\n")]);
    offsets.push(offset);
    offset += part.length;
    chunks.push(part);
  });
  let xref = `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`;
  for (const value of offsets) xref += `${String(value).padStart(10, "0")} 00000 n \n`;
  xref += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R /Info ${info} 0 R >>\nstartxref\n${offset}\n%%EOF\n`;
  chunks.push(ascii(xref));
  return join(chunks);
}

// --- zip ----------------------------------------------------------------------

let crcTable = null;

function crc32(bytes) {
  if (!crcTable) {
    crcTable = new Uint32Array(256);
    for (let n = 0; n < 256; n += 1) {
      let c = n;
      for (let k = 0; k < 8; k += 1) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
      crcTable[n] = c >>> 0;
    }
  }
  let crc = 0xffffffff;
  for (let i = 0; i < bytes.length; i += 1) crc = crcTable[(crc ^ bytes[i]) & 0xff] ^ (crc >>> 8);
  return (crc ^ 0xffffffff) >>> 0;
}

// entries: [{ name, data: Uint8Array }]. Stored, not compressed: the STLs
// are the bulk and the reader's unzip does not care. date is a Date.
export function zipStore(entries, date) {
  const time = (date.getHours() << 11) | (date.getMinutes() << 5) | (date.getSeconds() >> 1);
  const day = ((date.getFullYear() - 1980) << 9) | ((date.getMonth() + 1) << 5) | date.getDate();
  const chunks = [];
  const central = [];
  let offset = 0;
  for (const entry of entries) {
    const name = new TextEncoder().encode(entry.name);
    const crc = crc32(entry.data);
    const local = new DataView(new ArrayBuffer(30));
    local.setUint32(0, 0x04034b50, true);
    local.setUint16(4, 20, true);
    local.setUint16(6, 0x0800, true);          // names are UTF-8
    local.setUint16(8, 0, true);               // stored
    local.setUint16(10, time, true);
    local.setUint16(12, day, true);
    local.setUint32(14, crc, true);
    local.setUint32(18, entry.data.length, true);
    local.setUint32(22, entry.data.length, true);
    local.setUint16(26, name.length, true);
    local.setUint16(28, 0, true);
    const record = new DataView(new ArrayBuffer(46));
    record.setUint32(0, 0x02014b50, true);
    record.setUint16(4, 20, true);
    record.setUint16(6, 20, true);
    record.setUint16(8, 0x0800, true);
    record.setUint16(10, 0, true);
    record.setUint16(12, time, true);
    record.setUint16(14, day, true);
    record.setUint32(16, crc, true);
    record.setUint32(20, entry.data.length, true);
    record.setUint32(24, entry.data.length, true);
    record.setUint16(28, name.length, true);
    record.setUint32(42, offset, true);
    central.push(new Uint8Array(record.buffer), name);
    chunks.push(new Uint8Array(local.buffer), name, entry.data);
    offset += 30 + name.length + entry.data.length;
  }
  const directory = join(central);
  const end = new DataView(new ArrayBuffer(22));
  end.setUint32(0, 0x06054b50, true);
  end.setUint16(8, entries.length, true);
  end.setUint16(10, entries.length, true);
  end.setUint32(12, directory.length, true);
  end.setUint32(16, offset, true);
  return join([...chunks, directory, new Uint8Array(end.buffer)]);
}
