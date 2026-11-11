# SPDX-License-Identifier: MIT
"""The part pictures, and the PDF and zip a recipe is downloaded as.

Every STL has a current picture recorded in the manifest. site/export.js is
run under Node on real recipes; the PDF is checked as a file (header, cross
reference table, page count, the part names as text, the pictures as valid
image streams) and the zip is opened with Python's zipfile. No PDF library
is installed here, so the PDF is read with the standard library only."""
import hashlib
import json
import re
import shutil
import struct
import subprocess
import zipfile
import zlib

import pytest

from conftest import ROOT
from microduck import recipe

STL = ROOT / "stl"
NODE = shutil.which("node")

DRIVER = """
import { readFileSync, writeFileSync } from "node:fs";
import { evaluate } from "./build.mjs";
import { recipePdf, zipStore } from "./export.mjs";
const [dataPath, stlDir, outDir] = process.argv.slice(2);
const data = JSON.parse(readFileSync(dataPath, "utf8"));
const jobs = JSON.parse(readFileSync(`${outDir}/jobs.json`, "utf8"));
const titles = [["wiring", "Wiring"], ["power", "Power and supply sizing"], ["firmware", "Firmware and software"],
  ["analysis", "Analysis"], ["assembly", "Assembly"]];
for (const [name, selection] of Object.entries(jobs)) {
  const recipe = evaluate(data, selection);
  const images = {};
  for (const item of recipe.print.files) {
    if (item.thumb) images[item.thumb] = new Uint8Array(readFileSync(`${stlDir}/${item.thumb.slice("./stl/".length)}`));
  }
  const selectionRows = data.compat.dimensions.map((dim) => [dim.label, recipe.labels[dim.id]]);
  const pdf = recipePdf(recipe, images, { url: `https://example.org/?${recipe.query}`, date: "2026-11-11", selection: selectionRows, titles });
  writeFileSync(`${outDir}/${name}.pdf`, pdf);
  const entries = [{ name: "recipe.pdf", data: pdf }, { name: "recipe.json", data: new TextEncoder().encode(JSON.stringify(recipe)) }];
  for (const item of recipe.print.files) {
    if (item.link && item.link.startsWith("./")) {
      entries.push({ name: `stl/${item.file}`, data: new Uint8Array(readFileSync(`${stlDir}/${item.link.slice("./stl/".length)}`)) });
    }
  }
  writeFileSync(`${outDir}/${name}.zip`, zipStore(entries, new Date(2026, 10, 11, 12, 30, 40)));
  writeFileSync(`${outDir}/${name}.json`, JSON.stringify(recipe));
}
"""

JOBS = {
    "default": {},
    "pan": {"head": "sg90_pan"},
    "walker": {"controller": "ev3", "locomotion": "crank", "drive": "ev3_motors", "camera": "none"},
    "impossible": {"controller": "ev3", "drive": "braccio_shield"},
}


# --- pictures -----------------------------------------------------------------

def test_every_stl_has_a_current_picture_recorded_in_the_manifest():
    manifest = json.loads((STL / "manifest.json").read_text(encoding="utf-8"))
    recorded = {entry["file"]: entry["thumbnail"] for entry in manifest["files"]}
    recorded.update(manifest["thumbnails"])
    on_disk = sorted(path.relative_to(STL).as_posix() for path in STL.rglob("*.stl"))
    assert sorted(recorded) == on_disk
    for name, picture in recorded.items():
        assert picture["file"] == "thumbs/" + name[:-4] + ".png"
        assert picture["stl_sha256"] == hashlib.sha256((STL / name).read_bytes()).hexdigest(), f"{name}: picture is out of date"
        data = (STL / picture["file"]).read_bytes()
        assert len(data) == picture["bytes"] and len(data) < 40_000, name
        width, height, bits, colour, _, _, interlace = struct.unpack(">IIBBBBB", data[16:29])
        # What site/export.js can put into a PDF unchanged: palette, 8 bit, not interlaced, no transparency.
        assert (width, height, bits, colour, interlace) == (320, 240, 8, 3, 0), name
        assert b"tRNS" not in data, name
    pictures = sorted(path.relative_to(STL).as_posix() for path in (STL / "thumbs").rglob("*.png"))
    assert pictures == sorted(picture["file"] for picture in recorded.values()), "no stray pictures"
    assert sum(picture["bytes"] for picture in recorded.values()) < 400_000


def test_recipes_carry_the_picture_and_size_of_each_part():
    data = recipe.bundle(ROOT)
    rec = recipe.evaluate(data, {})
    assert rec["print"]["files"]
    for item in rec["print"]["files"]:
        assert item["thumb"] == "./stl/thumbs/" + item["file"][:-4] + ".png"
        assert (ROOT / item["thumb"][2:]).is_file()
        assert re.fullmatch(r"\d+ x \d+ x \d+ mm", item["size"]), item
        assert item["note"] == ""
    walker = recipe.evaluate(data, JOBS["walker"])
    assert walker["print"]["files"], "the walkers' parts are pictured too"
    for item in walker["print"]["files"]:
        assert item["thumb"] == "./stl/thumbs/" + item["file"][:-4] + ".png" and (ROOT / item["thumb"][2:]).is_file()
        assert re.fullmatch(r"\d+ x \d+ x \d+ mm", item["size"]), item


def test_site_build_serves_the_pictures():
    subprocess.run([shutil.which("python") or "python", str(ROOT / "scripts" / "build_site.py")], check=False, capture_output=True)
    manifest = json.loads((STL / "manifest.json").read_text(encoding="utf-8"))
    for entry in manifest["files"]:
        assert (ROOT / "site" / "stl" / entry["thumbnail"]["file"]).is_file()


# --- PDF and zip ----------------------------------------------------------------

@pytest.fixture(scope="module")
def made(tmp_path_factory):
    if NODE is None:
        pytest.skip("Node is not installed; site/export.js was not run")
    folder = tmp_path_factory.mktemp("export")
    shutil.copyfile(ROOT / "site" / "build.js", folder / "build.mjs")
    shutil.copyfile(ROOT / "site" / "export.js", folder / "export.mjs")
    (folder / "driver.mjs").write_text(DRIVER, encoding="utf-8")
    (folder / "data.json").write_text(json.dumps(recipe.bundle(ROOT)), encoding="utf-8")
    (folder / "jobs.json").write_text(json.dumps(JOBS), encoding="utf-8")
    subprocess.run([NODE, "driver.mjs", "data.json", str(STL), str(folder)], cwd=folder, check=True, capture_output=True, timeout=120)
    return folder


def objects_of(pdf: bytes) -> dict:
    """Every object by number, found through the cross reference table."""
    assert pdf.startswith(b"%PDF-1.4\n") and pdf.rstrip().endswith(b"%%EOF")
    start = int(re.search(rb"startxref\n(\d+)\n%%EOF", pdf).group(1))
    assert pdf[start:start + 5] == b"xref\n"
    count = int(re.match(rb"xref\n0 (\d+)\n", pdf[start:]).group(1))
    rows = pdf[start:].split(b"\n")[3:2 + count]
    found = {}
    for number, row in enumerate(rows, start=1):
        offset = int(row[:10])
        head = f"{number} 0 obj\n".encode()
        assert pdf[offset:offset + len(head)] == head, f"object {number} is not where the table says"
        found[number] = pdf[offset + len(head):pdf.index(b"\nendobj\n", offset)]
    assert int(re.search(rb"/Size (\d+)", pdf[start:]).group(1)) == count
    return found


@pytest.mark.parametrize("name", sorted(JOBS))
def test_pdf_is_a_sound_file_with_the_recipe_in_it(made, name):
    pdf = (made / f"{name}.pdf").read_bytes()
    rec = json.loads((made / f"{name}.json").read_text(encoding="utf-8"))
    objects = objects_of(pdf)
    pages = [body for body in objects.values() if body.startswith(b"<< /Type /Page ")]
    declared = int(re.search(rb"/Type /Pages /Count (\d+)", objects[2]).group(1))
    assert len(pages) == declared >= 1
    text = b"".join(body for body in objects.values() if body.startswith(b"<< /Length") and b"/Subtype /Image" not in body)
    for body in objects.values():                         # stream lengths are right
        match = re.match(rb"<< .*?/Length (\d+) >>\nstream\n", body, re.S)
        if match:
            assert body[match.end():].endswith(b"\nendstream") and len(body) - match.end() - len(b"\nendstream") == int(match.group(1))

    def shown(words: str) -> bool:
        return words.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)").encode() in text

    assert shown(f"Status: {rec['status_label']}")
    assert shown("https://example.org/?" + rec["query"][:40])
    assert shown("Made on 2026-11-11.")
    assert shown(f"Page 1 of {declared}.")
    images = [body for body in objects.values() if b"/Subtype /Image" in body]
    if rec["status"] == "not_possible":
        assert declared == 1 and not images
        assert shown("Nearest possible selection")
        return
    assert declared >= 2, "a recipe runs over several pages"
    for item in rec["print"]["files"]:
        assert shown(item["file"][:30]), item["file"]
        assert shown(f"Print {item['qty']}")
    for part in rec["parts"]:
        assert shown(part["name"][:30]), part["name"]
    assert shown("PRINT FIRST: fit test") == any(item["fit"] for item in rec["print"]["files"])
    for title in ("Files to print", "Parts", "Wiring", "Power and supply sizing", "Firmware and software", "Analysis", "Assembly"):
        assert shown(title), title
    assert len(images) == len({item["thumb"] for item in rec["print"]["files"] if item["thumb"]})
    for body in images:
        width, height = (int(re.search(rb"/%s (\d+)" % key, body).group(1)) for key in (b"Width", b"Height"))
        assert b"/Indexed /DeviceRGB" in body and b"/Predictor 15" in body and b"/Columns %d" % width in body
        stream = body[body.index(b"stream\n") + 7:-len(b"\nendstream")]
        # PNG rows: one filter byte and one byte per pixel.
        assert len(zlib.decompress(stream)) == height * (width + 1)
    for used in set(re.findall(rb"/(Im\d+) Do", text)):
        assert any(b"/%s " % used in page for page in pages)


def test_pdf_breaks_long_words_and_keeps_to_ascii(made):
    pdf = (made / "default.pdf").read_bytes()
    assert all(byte < 127 or 0xcf <= byte for byte in pdf[:9]) and b"\r" not in pdf[:200]
    for body in objects_of(pdf).values():
        if body.startswith(b"<< /Length") and b"/Subtype /Image" not in body:
            for line in re.findall(rb"\((.*?)\) Tj", body):
                assert len(line) < 140 and all(32 <= byte < 127 for byte in line)


@pytest.mark.parametrize("name", sorted(JOBS))
def test_zip_opens_and_holds_the_pdf_the_recipe_and_its_stls(made, name):
    rec = json.loads((made / f"{name}.json").read_text(encoding="utf-8"))
    with zipfile.ZipFile(made / f"{name}.zip") as archive:
        assert archive.testzip() is None
        names = archive.namelist()
        assert names[:2] == ["recipe.pdf", "recipe.json"]
        assert archive.read("recipe.pdf") == (made / f"{name}.pdf").read_bytes()
        assert json.loads(archive.read("recipe.json")) == rec
        served = [item["file"] for item in rec["print"]["files"] if item["link"] and item["link"].startswith("./")]
        assert names[2:] == [f"stl/{file}" for file in served]
        for file in served:
            assert archive.read(f"stl/{file}") == (STL / file).read_bytes()
        info = archive.getinfo("recipe.pdf")
        assert info.compress_type == zipfile.ZIP_STORED and info.date_time == (2026, 11, 11, 12, 30, 40)


def test_the_page_offers_the_pdf_the_zip_and_the_print_dialog():
    html = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "site" / "build.js").read_text(encoding="utf-8")
    for control in ("download-pdf", "download-all", "print", "download"):
        assert f'id="{control}"' in html and f'getElementById("{control}")' in script
    assert 'import("./export.js")' in script
    assert "picture.alt = item.role" in script and 'picture.loading = "lazy"' in script
    css = (ROOT / "site" / "recipe.css").read_text(encoding="utf-8")
    assert ".part-cards" in css and "break-inside: avoid" in css and "@page" in css
    export = (ROOT / "site" / "export.js").read_text(encoding="utf-8")
    assert "https://" not in export and "fetch(" not in export and "window." not in export and "document." not in export
