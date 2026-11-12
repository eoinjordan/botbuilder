# SPDX-License-Identifier: MIT
"""Fetch the openly licensed component photographs from Wikimedia Commons.

For every entry of config/component_images.json with "kind": "photo" and a
"title" (the file's name on Commons), this asks the Commons API for that
file's own metadata, refuses anything that is not CC0, public domain, CC BY
or CC BY-SA, downloads a modest preview, crops it to 4:3 (or to the entry's
"crop" box, fractions of the width and height; with "pad" the whole
photograph is set on a white card instead), scales it to 320 x 240 and
saves it under docs/components/ as an 8-bit PNG of at most 30 kB. It then writes the author,
the licence, the licence address and the file page into the entry, exactly
as that page gives them.

A photograph of your own needs none of this: put it in docs/components/ and
write its entry by hand (see docs/components/README.md).

    python scripts/fetch_component_photos.py            fetch what is missing
    python scripts/fetch_component_photos.py --all      fetch every photograph again

Needs the network and Pillow. It sends a generic client name and nothing
about the person running it. Not part of the tests or of the site build:
the photographs are committed.
"""
import argparse
import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from html import unescape
from io import BytesIO
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "config" / "component_images.json"
FOLDER = ROOT / "docs" / "components"
API = "https://commons.wikimedia.org/w/api.php"
AGENT = "botbuilder-site-build/1.0 (static site picture credits; generic client)"
SIZE = (320, 240)
COLOURS = (64, 48, 32, 24, 16)
LIMIT = 30_000                                  # bytes for one picture
# Licences taken: the short names Commons gives. Anything else is refused.
OPEN = re.compile(r"^(CC0( 1\.0)?|Public domain|PD|CC BY(-SA)? [1-4]\.[05]( [a-z]{2})?)$")


def get(url: str) -> bytes:
    for attempt in range(6):
        time.sleep(1.5)                              # a slow, polite client
        request = urllib.request.Request(url, headers={"User-Agent": AGENT})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            if error.code != 429:
                raise
            time.sleep(20 * (attempt + 1))
    raise RuntimeError("Wikimedia Commons keeps answering 429; try again later")


def plain(value: str) -> str:
    """The text of a metadata field without its markup."""
    return " ".join(unescape(re.sub(r"<[^>]+>", "", value or "")).split())


def metadata(title: str) -> dict:
    query = {"action": "query", "titles": title, "prop": "imageinfo", "iiprop": "url|extmetadata|size|mime",
             "iiurlwidth": "960", "format": "json"}
    pages = json.loads(get(API + "?" + urllib.parse.urlencode(query)))["query"]["pages"]
    page = next(iter(pages.values()))
    if "imageinfo" not in page:
        raise RuntimeError(f"{title}: not a file on Commons")
    info = page["imageinfo"][0]
    meta = info["extmetadata"]

    def field(name):
        return plain(meta.get(name, {}).get("value", ""))
    licence = field("LicenseShortName")
    if not OPEN.match(licence):
        raise RuntimeError(f"{title}: licence {licence!r} is not one of CC0, public domain, CC BY, CC BY-SA")
    if field("Restrictions") or field("NonFree"):
        raise RuntimeError(f"{title}: marked with restrictions")
    return {"author": field("Artist") or field("Credit"), "licence": licence, "licence_url": field("LicenseUrl"),
            "source_url": info["descriptionurl"], "preview": info["thumburl"], "mime": info["mime"]}


def picture(content: bytes, crop=None, pad=False) -> Image.Image:
    image = Image.open(BytesIO(content)).convert("RGB")
    width, height = image.size
    if pad:                                          # the whole photograph on a white card, nothing trimmed
        image.thumbnail(SIZE, Image.LANCZOS)
        card = Image.new("RGB", SIZE, (255, 255, 255))
        card.paste(image, ((SIZE[0] - image.width) // 2, (SIZE[1] - image.height) // 2))
        return card
    if crop:
        image = image.crop((round(crop[0] * width), round(crop[1] * height), round(crop[2] * width), round(crop[3] * height)))
        width, height = image.size
    wanted = SIZE[0] / SIZE[1]
    if width / height > wanted:                      # too wide: trim the sides
        keep = round(height * wanted)
        image = image.crop(((width - keep) // 2, 0, (width - keep) // 2 + keep, height))
    else:                                            # too tall: trim top and bottom
        keep = round(width / wanted)
        image = image.crop((0, (height - keep) // 2, width, (height - keep) // 2 + keep))
    return image.resize(SIZE, Image.LANCZOS)


def save(image: Image.Image, path: Path) -> None:
    """As an 8-bit palette PNG, with fewer colours until it is under LIMIT."""
    for colours in COLOURS:
        image.quantize(colors=colours, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE).save(path, optimize=True)
        if path.stat().st_size <= LIMIT:
            return


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--all", action="store_true", help="fetch every photograph again")
    parser.add_argument("--only", nargs="+", metavar="ID", help="fetch these components again")
    args = parser.parse_args(argv)
    content = json.loads(DATA.read_text(encoding="utf-8"))
    FOLDER.mkdir(parents=True, exist_ok=True)
    failed = 0
    for entry in content["components"]:
        if entry.get("kind") != "photo" or entry.get("origin") != "Wikimedia Commons" or not entry.get("title"):
            continue
        path = FOLDER / entry["file"]
        if args.only and entry["id"] not in args.only:
            continue
        if path.is_file() and entry.get("licence") and not args.all and not args.only:
            continue
        try:
            about = metadata(entry["title"])
            image = picture(get(about["preview"]), entry.get("crop"), bool(entry.get("pad")))
        except (RuntimeError, OSError, KeyError) as error:
            print(f"{entry['id']}: {error}")
            failed += 1
            continue
        save(image, path)
        entry.update(author=about["author"], licence=about["licence"], licence_url=about["licence_url"],
                     source_url=about["source_url"],
                     changes=("resized, set on a white card" if entry.get("pad") else "cropped, resized")
                     + " and reduced to a small palette; otherwise unchanged",
                     sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        print(f"{entry['id']}: {entry['title']}, {about['licence']}, {about['author']}, {path.stat().st_size} bytes")
        DATA.write_text(json.dumps(content, indent=1) + "\n", encoding="utf-8", newline="\n")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
