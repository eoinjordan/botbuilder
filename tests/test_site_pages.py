# SPDX-License-Identifier: MIT
"""The Flash and Control pages as static files: relative paths so a
repository base path works, no trackers, one pinned external script, the
status said plainly, and the build copying what the control page reads."""
import json
import re
import subprocess
import sys

import pytest

from conftest import ROOT
from microduck import motions

SITE = ROOT / "site"
PAGES = ("flash.html", "flash.js", "control.html", "control.js")


def read(name: str) -> str:
    return (SITE / name).read_text(encoding="utf-8")


@pytest.mark.parametrize("name", PAGES)
def test_paths_are_relative(name):
    text = read(name)
    assert not re.search(r'(src|href)="/[^/]', text)
    assert not re.search(r'url\("?/[^/]', text)
    assert not re.search(r'fetch\(["`]/', text)
    # Links marked data-page are hidden until the build finds the page (nav.js).
    text = re.sub(r'<a [^>]*data-page="[^"]*"[^>]*>', "", text)
    for target in re.findall(r'(?:src|href)="(\./[^"#?]*)', text):
        if target.startswith(("./data/", "./images/")) or target == "./":
            continue
        assert (SITE / target[2:]).is_file(), target


@pytest.mark.parametrize("name", PAGES)
def test_no_trackers_and_only_known_hosts(name):
    text = read(name)
    for needle in ("google-analytics", "googletagmanager", "gtag(", "plausible", "matomo", "facebook", "document.cookie", "fonts.googleapis"):
        assert needle not in text.lower(), needle
    hosts = set(re.findall(r"https://[a-z0-9.-]+", text))
    assert hosts <= {"https://cdn.jsdelivr.net", "https://github.com"}


def test_external_scripts():
    assert re.findall(r'<script[^>]*src="([^"]+)"', read("flash.html")) == ["./nav.js", "./flash.js"]
    assert re.findall(r'<script[^>]*src="([^"]+)"', read("control.html")) == ["./nav.js", "./control.js"]
    assert "https://cdn.jsdelivr.net/npm/three@0.180.0/build/three.module.min.js" in read("control.html")
    assert "cdn.jsdelivr.net" not in read("flash.html")
    assert "import " not in read("flash.js").split("// ---- page wiring")[0], "the flash logic is one file"


def test_status_is_said_on_both_pages():
    flash, control = read("flash.html"), read("control.html")
    assert flash.lower().count("not run on hardware") >= 3
    assert control.lower().count("not run on hardware") >= 2
    assert "Nothing is\n        flashed from the browser" in flash or "Nothing is flashed from the browser" in " ".join(flash.split())
    joined = " ".join(control.split())
    assert "cannot reach a robot" in joined and "Pairing is done in the operating system" in joined
    assert "not physics" in joined
    for name in ("flash.html", "control.html"):
        assert '<html lang="en">' in read(name) and 'name="viewport"' in read(name)


def test_pages_carry_the_shared_nav_and_the_build_lists_them():
    block = re.search(r'<nav id="site-nav">.*?</nav>', read("index.html"), re.S).group(0)
    for name in ("flash.html", "control.html"):
        mine = re.search(r'<nav id="site-nav">.*?</nav>', read(name), re.S).group(0)
        assert mine.replace(' aria-current="page"', "") == block.replace(' aria-current="page"', ""), name
        assert 'src="./nav.js"' in read(name) and "Bot<b>builder</b>" in read(name)
        assert f'data-page="{name}" hidden aria-current="page"' in mine
    subprocess.run([sys.executable, str(ROOT / "scripts" / "build_site.py")], check=True, capture_output=True)
    pages = json.loads((SITE / "data" / "pages.json").read_text(encoding="utf-8"))
    assert "flash.html" in pages and "control.html" in pages
    assert 'id="back-link" href="./"' in read("flash.html") and "Build yours</a>" in read("control.html")


def test_every_control_has_a_name():
    for name in ("flash.html", "control.html"):
        html = read(name)
        for button in re.findall(r"<button[^>]*>(.*?)</button>", html, re.S):
            assert button.strip(), "a button without text"
        ids = re.findall(r'<(?:input|select)[^>]*\bid="([^"]+)"', html)
        for control_id in ids:
            pattern = rf'<label[^>]*>(?:(?!</label>).)*id="{control_id}"|<label for="{control_id}"'
            assert re.search(pattern, html, re.S), f"{name}: {control_id} has no label"


def test_build_copies_the_manifest_and_its_trajectories():
    subprocess.run([sys.executable, str(ROOT / "scripts" / "build_site.py")], check=True, capture_output=True)
    manifest = json.loads((SITE / "data" / "motions.json").read_text(encoding="utf-8"))
    assert manifest == motions.load_manifest()
    for entry in manifest["motions"].values():
        assert (SITE / "data" / entry["file"]).read_bytes() == (ROOT / entry["source"]).read_bytes()
    workflow = (ROOT / ".github" / "workflows" / "pages.yml").read_text(encoding="utf-8")
    assert "pip install" not in workflow, "the build must stay standard library only"


def test_documents_say_their_status():
    assert "not run on hardware" in " ".join((ROOT / "docs" / "flash.md").read_text(encoding="utf-8").split())
    control = " ".join((ROOT / "docs" / "control.md").read_text(encoding="utf-8").split())
    assert "not run on hardware" in control and "mixed content" in control
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "docs/flash.md" in readme and "docs/control.md" in readme
