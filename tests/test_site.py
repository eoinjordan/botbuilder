# SPDX-License-Identifier: MIT
"""The static site: builds from the committed data, uses relative paths only,
pins its one external script, carries no trackers and serves the printable STLs listed in the manifest."""
import json
import re
import subprocess
import sys

import pytest

from conftest import ROOT

SITE = ROOT / "site"


@pytest.fixture(scope="module")
def built():
    subprocess.run([sys.executable, str(ROOT / "scripts" / "build_site.py")], check=True, capture_output=True)
    return SITE


def test_site_builds_with_data_and_pictures(built, assembly_report):
    for name in ("assembly.json", "sim.json", "joints.json", "model.json", "hardware.json"):
        json.loads((built / "data" / name).read_text(encoding="utf-8"))
    html = (built / "biped.html").read_text(encoding="utf-8")
    for source in re.findall(r'src="\./(images/[^"]+)"', html):
        assert (built / source).is_file(), source
    assert json.loads((built / "data" / "assembly.json").read_text(encoding="utf-8"))["findings"] == assembly_report["findings"]


def test_the_printable_stls_are_published_as_listed(built):
    manifest = json.loads((built / "stl" / "manifest.json").read_text(encoding="utf-8"))
    published = {p.relative_to(built / "stl").as_posix() for p in built.rglob("*.stl")}
    assert published == {entry["file"] for entry in manifest["files"]}, "every listed part, in its folder, and nothing else"
    for entry in manifest["files"]:
        assert (built / "stl" / entry["file"]).stat().st_size == entry["bytes"]
    model_data = json.loads((built / "data" / "model.json").read_text(encoding="utf-8"))
    assert model_data["meshes_published"] is True
    for link in model_data["links"]:
        for mesh in link["meshes"]:
            assert (built / "stl" / mesh["file"]).is_file()


def test_paths_are_relative_so_a_repo_base_path_works():
    for name in ("biped.html", "app.js", "style.css"):
        text = (SITE / name).read_text(encoding="utf-8")
        assert not re.search(r'(src|href)="/[^/]', text), name
        assert not re.search(r'url\("?/[^/]', text), name
        assert not re.search(r'fetch\(["`]/', text), name


def test_three_is_pinned_and_is_the_only_external_script():
    html = (SITE / "biped.html").read_text(encoding="utf-8")
    assert "https://cdn.jsdelivr.net/npm/three@0.180.0/build/three.module.min.js" in html
    scripts = re.findall(r"<script[^>]*src=\"([^\"]+)\"", html)
    assert scripts == ["./nav.js", "./app.js", "./tour.js"]
    external = set(re.findall(r'https://[a-z0-9.-]+', html + (SITE / "app.js").read_text(encoding="utf-8")))
    assert external <= {"https://cdn.jsdelivr.net", "https://github.com", "https://eoinjordan.github.io",
                        "https://creativecommons.org"}, "the last for the terms of the Microduck-look parts"


def test_no_trackers():
    text = "".join((SITE / name).read_text(encoding="utf-8").lower() for name in ("biped.html", "app.js", "style.css"))
    for needle in ("google-analytics", "googletagmanager", "gtag(", "plausible", "matomo", "facebook", "document.cookie", "fonts.googleapis"):
        assert needle not in text, needle


def test_status_box_is_plain():
    html = (SITE / "biped.html").read_text(encoding="utf-8")
    assert 'class="status"' not in html and "Status and assumptions" in html


def test_sliders_use_the_generated_limits():
    app = (SITE / "app.js").read_text(encoding="utf-8")
    assert "link.min_deg" in app and "link.max_deg" in app
    assert "input.min = hinge.min" in app and "input.max = hinge.max" in app


def test_pages_workflow_publishes_the_site_directory():
    workflow = (ROOT / ".github" / "workflows" / "pages.yml").read_text(encoding="utf-8")
    assert "python scripts/build_site.py" in workflow
    assert "path: site" in workflow
    assert "--with-meshes" not in workflow
