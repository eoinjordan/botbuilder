# SPDX-License-Identifier: MIT
"""House rules for the repository: plain ASCII text, SPDX lines on source
files, STLs only under stl/, documents that agree with the reports."""
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


def test_mesh_files_are_tracked_only_under_stl():
    for path in tracked():
        if path.suffix.lower() in (".stl", ".obj", ".step", ".3mf"):
            assert under_stl(path), path.relative_to(ROOT).as_posix()


def test_repository_stays_small():
    # Printable files under stl/ have their own budget; stl/lego adds 8.1 MB.
    rest = [path for path in tracked() if not under_stl(path)]
    assert sum(path.stat().st_size for path in rest) < 5_000_000
    for path in rest:
        assert path.stat().st_size < 1_000_000, path.name
    meshes = [path for path in tracked() if under_stl(path)]
    assert sum(path.stat().st_size for path in meshes) < 20_000_000
    for path in meshes:
        assert path.stat().st_size < 3_000_000, path.name


def test_generated_documents_say_their_status():
    assert "never been assembled" in (ROOT / "docs" / "simulation.md").read_text(encoding="utf-8")
    assert "Nothing here has been printed, assembled or powered" in (ROOT / "docs" / "assembly.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "verified in simulation only" in readme
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
