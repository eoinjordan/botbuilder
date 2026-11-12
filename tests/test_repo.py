# SPDX-License-Identifier: MIT
"""House rules for the repository: plain ASCII text, SPDX lines on source
files, only the generated printable STLs as meshes, documents that agree
with the reports."""
import json
import re
import subprocess

import pytest

from conftest import ROOT

TEXT = {".py", ".md", ".json", ".yml", ".yaml", ".html", ".css", ".js", ".cpp", ".hpp", ".h", ".ino", ".csv", ".txt", ".xml",
        ".urdf", ".ini", ""}
SOURCE = {".py", ".js", ".css", ".cpp", ".hpp", ".h", ".ino"}
THIRD_PARTY = {"site/assets/licenses/space-grotesk.txt"}


def tracked():
    done = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True)
    if done.returncode or not done.stdout.strip():
        pytest.skip("not a git checkout")
    return [ROOT / line for line in done.stdout.splitlines() if (ROOT / line).is_file()]


def test_text_files_are_plain_ascii():
    for path in tracked():
        rel = path.relative_to(ROOT).as_posix()
        if path.suffix not in TEXT or rel in THIRD_PARTY:
            continue
        data = path.read_bytes()
        bad = [b for b in data if b > 126 or (b < 32 and b not in (9, 10, 13))]
        assert not bad, f"{rel}: non-ASCII byte {bad[0]:#x}"


def test_prose_has_no_exclamation_marks():
    for path in tracked():
        if path.suffix != ".md" and path.name != "NOTICE":
            continue
        text = path.read_text(encoding="utf-8").replace("![", "[")
        assert "!" not in text, path.name


def test_source_files_carry_an_spdx_line():
    for path in tracked():
        if path.suffix in SOURCE and path.stat().st_size:
            head = path.read_text(encoding="utf-8")[:300]
            assert "SPDX-License-Identifier: MIT" in head, path.relative_to(ROOT).as_posix()


def under_stl(path) -> bool:
    return path.relative_to(ROOT).parts[0] == "stl"


def test_only_the_generated_printable_parts_are_tracked_as_meshes():
    """The derived printable STLs are committed under stl/ and its folders,
    each listed in the manifest by its path. The third-party source meshes
    are not in the repository."""
    with open(ROOT / "stl" / "manifest.json", encoding="utf-8") as handle:
        listed = {entry["file"] for entry in json.load(handle)["files"]}
    meshes = [path for path in tracked() if path.suffix.lower() in (".stl", ".obj", ".step", ".3mf")]
    for path in meshes:
        assert under_stl(path) and path.suffix == ".stl", path.relative_to(ROOT).as_posix()
        assert not re.match(r"\d\d_[^t]", path.name), "source meshes are numbered 01 to 15; only the torso starts with 01_"
    assert {path.relative_to(ROOT / "stl").as_posix() for path in meshes} == listed


def test_repository_stays_small():
    # Printable files and their pictures under stl/ have their own budget.
    rest = [path for path in tracked() if not under_stl(path)]
    # 8 MB of code, documents, reports and recordings, and under 1 MB of pictures for the site:
    # the bought components (docs/components), the build cards and the logo.
    assert sum(path.stat().st_size for path in rest) < 9_200_000
    for path in rest:
        assert path.stat().st_size < 1_000_000, path.name
    meshes = [path for path in tracked() if under_stl(path)]
    # About 24.7 MB of printable files and their pictures (2.5 MB of that the Microduck-look parts
    # with their comb feet), and 8.9 MB of everything else: the whole checkout stays under 34 MB,
    # a little under the two budgets added together.
    assert sum(path.stat().st_size for path in meshes) < 25_000_000
    assert sum(path.stat().st_size for path in tracked()) < 34_000_000
    for path in meshes:
        assert path.stat().st_size < 3_000_000, path.name


def test_generated_documents_say_their_status():
    assert "never been assembled" in (ROOT / "docs" / "simulation.md").read_text(encoding="utf-8")
    assert "Nothing here has been printed, assembled or powered" in (ROOT / "docs" / "assembly.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "docs/status.md" in readme
    assert "where their shape comes from" in readme


def test_readme_numbers_match_the_reports(selected, sim_report):
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    mass = selected["mass"]
    assert f"{round(mass['total_g'])} g" in readme
    assert f"{round(mass['total_if_printed_solid_g'])} g if" in readme
    stance = round(selected["dimensions"]["stance_width_between_foot_centres_mm"])
    assert f"are {stance} mm apart" in readme
    assert f"{round(sim_report['gait_default']['distance_forward_m'] * 1000)} mm in" in readme
    assert f"{round(sim_report['gait_best']['distance_forward_m'] * 1000)} mm in" in readme
    limits = selected["joint_limits_deg"]["left_hip_roll"]
    assert re.search(rf"hip roll {int(limits['min_deg'])} to \+{int(limits['max_deg'])}", readme)
