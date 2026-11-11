# SPDX-License-Identifier: MIT
"""Wheeled variants: data with sources, balance by calculation, generated
models and documents, and the headline simulation results."""
import ast
import json

import numpy as np
import pytest

from conftest import ROOT
from walkers import model, report, wheeled, wheeled_report


@pytest.fixture(scope="module")
def cfg():
    return wheeled.config()


@pytest.fixture(scope="module")
def analysis():
    return json.loads((ROOT / "reports" / "wheeled" / "analysis.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def sim():
    return json.loads((ROOT / "reports" / "wheeled" / "sim.json").read_text(encoding="utf-8"))


def _facts(node, path=""):
    if isinstance(node, dict):
        if "class" in node:
            yield path, node
        for key, value in node.items():
            yield from _facts(value, f"{path}/{key}")
    elif isinstance(node, list):
        for i, value in enumerate(node):
            yield from _facts(value, f"{path}/{i}")


def test_every_fact_has_a_source_or_a_reason(cfg):
    facts = list(_facts(cfg))
    assert len(facts) > 45
    for path, fact in facts:
        assert fact["class"] in ("maker", "third-party", "assumed"), path
        if fact["class"] == "assumed":
            assert fact.get("why"), path
        else:
            assert fact["source"].startswith("https://"), path
    for key, f in cfg["friction"].items():
        if not key.startswith("_"):
            assert f["class"] == "assumed" and f["range"][0] <= f["value"] <= f["range"][1], key
    assert cfg["friction"]["pla"]["value"] < cfg["friction"]["tpu"]["value"] <= cfg["friction"]["o_ring"]["value"]


def test_every_base_has_a_wheeled_build(cfg, analysis):
    assert set(cfg["bases"]) == {"ev3", "pi_buildhat", "hub51515", "m5_basex", "unoq", "pi"}
    assert set(cfg["bases"]["unoq"]["drives"]) == set(cfg["bases"]["pi"]["drives"]) == {"servo360", "tt"}
    assert "tt" not in cfg["bases"]["m5_basex"]["drives"]
    pairs = sum(len(b["drives"]) for b in cfg["bases"].values())
    assert len(analysis["defaults"]) == pairs * 4          # skid or ball, wheels back or front
    for vid in analysis["defaults"]:
        assert (ROOT / "robot" / "lego" / "wheeled" / f"{vid}.xml").is_file()


def test_printed_wheel_geometry_matches_the_named_rings(cfg):
    import trimesh
    for key, ring, od in (("solid_d43", 38.0, 44.76), ("solid_d56", 50.0, 57.0), ("solid_tt_d65", 58.0, 65.16)):
        w = cfg["wheels"][key]
        assert w["diameter_mm"] == pytest.approx(ring * 1.02 + 6.0, abs=0.01) == pytest.approx(od, abs=0.01)
        mesh = trimesh.load_mesh(ROOT / "stl" / "lego" / "wheeled" / f"{w['stl'][0]}.stl")
        body = float(mesh.bounds[1][0] - mesh.bounds[0][0])
        assert body == pytest.approx(od - 2.0, abs=0.05)          # the ring stands 1 mm proud all round
        assert str(int(ring)) in cfg["o_rings"]["rings"][key.split("_")[-1]]
    for size, od in (("d43", 43.2), ("d56", 56.0), ("d65", 65.0)):
        tyre = trimesh.load_mesh(ROOT / "stl" / "lego" / "wheeled" / f"tyre_tpu_{size}.stl")
        assert float(tyre.bounds[1][0] - tyre.bounds[0][0]) == pytest.approx(od, abs=0.05)


def test_balance_by_calculation(analysis):
    for vid in analysis["defaults"]:
        a = analysis["variants"][vid]
        assert a["stable"] and a["static_margin_mm"] > 25.0, vid
        assert 0.2 < a["com_fraction_of_wheelbase"] < 0.45, vid
        assert a["ground_clearance_mm"] > 5.0, vid
        assert a["torque_fraction_of_stall_level"] < 0.2, vid
        if a["wheels_at"] == "back":
            assert a["support_lifts_accelerating_m_s2"] and a["support_lifts_braking_m_s2"] is None
            assert a["slope_limit_traction_deg"] > 20
        else:
            assert a["support_lifts_braking_m_s2"] and a["support_lifts_accelerating_m_s2"] is None
            assert a["slope_limit_traction_deg"] < 20
    fresh = wheeled.analyse(wheeled.build("unoq", "tt", None, "skid", "back"))
    stored = analysis["variants"]["unoq-tt-tt65-skid-back"]
    assert json.loads(json.dumps(fresh)) == stored
    assert stored["top_speed_no_load_m_s"] == pytest.approx(200 * 2 * np.pi / 60 * 0.0325, abs=0.001)


def test_generated_models_are_current(analysis):
    for vid in ("ev3-ev3large-lego43-skid-back", "unoq-servo360-solidhornd56-ball-front", "pi-tt-tt65-ball-back"):
        a = analysis["variants"][vid]
        v = wheeled.build(a["base"], a["drive"], a["wheel"], a["support"], a["wheels_at"])
        assert v.id == vid
        assert wheeled.mjcf(v) == (ROOT / "robot" / "lego" / "wheeled" / f"{vid}.xml").read_text(encoding="utf-8")


@pytest.mark.parametrize("args, speed", [(("ev3", "ev3_large"), 0.30), (("unoq", "tt"), 0.59), (("unoq", "servo360"), 0.235)])
def test_drives_straight_and_spins(args, speed, analysis, sim):
    v = wheeled.build(*args, None, "skid", "back")
    s = wheeled.WheeledSim(v)
    a = wheeled.drive(s, lambda t: (1.0, 1.0), 2.5)
    late = a[a[:, 0] >= 1.5]
    assert float((late[-1, 1] - late[0, 1]) / 1.0) == pytest.approx(speed, rel=0.08)
    assert abs(np.degrees(a[-1, 3])) < 2.0 and a[:, 5].max() < 15.0
    assert sim["variants"][v.id]["straight"]["speed_m_s"] == pytest.approx(speed, rel=0.08)
    s = wheeled.WheeledSim(v)
    a = wheeled.drive(s, lambda t: (-1.0, 1.0), 2.0)
    assert np.degrees(np.unwrap(a[:, 3])[-1]) > 150.0           # turns left, well over a third of a turn in 2 s
    assert sim["variants"][v.id]["spin"]["fraction_of_ideal"] > 0.6


def test_a_bare_printed_wheel_slips_where_a_ring_grips():
    for bare, climbs in ((True, False), (False, True)):
        v = wheeled.build("unoq", "tt", "solid_tt_d65", "skid", "back", bare=bare)
        s = wheeled.WheeledSim(v)
        s.set_slope(14.0)
        s.reset()
        a = wheeled.drive(s, lambda t: (min(1.0, t), min(1.0, t)), 4.0)
        late = a[a[:, 0] >= 2.5]
        assert bool((late[-1, 1] - late[0, 1]) / 1.5 > 0.1) == climbs, bare


def test_pinned_simulation_headlines(analysis, sim):
    S = sim["variants"]
    cmp_ = wheeled_report.end_comparison(analysis, sim)
    assert cmp_["back"]["mean_slope_deg"] > cmp_["front"]["mean_slope_deg"] + 5
    assert cmp_["ball"]["mean_drag_n"] < cmp_["skid"]["mean_drag_n"]
    for vid in analysis["defaults"]:
        s = S[vid]
        assert s["straight"]["speed_m_s"] > 0.2, vid
        assert 0.75 < s["straight"]["fraction_of_no_load_speed"] <= 1.0, vid
        assert s["stop"]["distance_m"] < 0.08, vid
        assert s["slope"]["steepest_climbed_deg"] >= 10, vid
        assert 2 <= s["step"]["highest_climbed_mm"] <= 12, vid
        if analysis["variants"][vid]["wheels_at"] == "back":
            assert s["slope"]["steepest_climbed_deg"] >= 20, vid
    for vid in analysis["tyre_comparison"]:
        limit = S[vid]["slope"]["steepest_climbed_deg"]
        assert (limit <= 10) if "-bare-" in vid else (limit >= 20), vid
    for path in sim["recordings"].values():
        assert 5_000 < (ROOT / "docs" / path).stat().st_size < 1_000_000


def test_documents_and_summary_are_current(analysis, sim, cfg):
    doc = (ROOT / "docs" / "wheeled-variants.md").read_text(encoding="utf-8")
    assert doc == wheeled_report.document(analysis, sim, cfg)
    assert "Nothing here has been printed, assembled or powered" in doc
    assert "A bare printed wheel slips on a smooth floor" in doc
    summary = json.loads((ROOT / "reports" / "variants" / "summary.json").read_text(encoding="utf-8"))
    assert summary == report.summary(report.load("assembly.json"), report.load("sim.json"))
    entries = [e for e in summary["entries"] if e["locomotion"] == "wheeled"]
    assert len(entries) == 9
    assert {e["locomotion"] for e in summary["entries"]} == {"crank walker", "wheeled"}
    for e in entries:
        assert e["wheels"] and set(e["wheels"]) <= set(wheeled_report.WHEEL_KINDS)
        assert e["status"].startswith("analysed and simulated only")
        assert len(e["options"]) == 4 and e["recommended_wheels_at"] == "back"
        if e["controller_sketch"]:
            for path in e["controller_sketch"].split(", "):
                assert (ROOT / path).is_file(), path
    kinds = {k for e in entries for k in e["wheels"]}
    assert kinds == set(wheeled_report.WHEEL_KINDS)


def test_drive_sketches_parse_and_are_marked_not_run():
    names = ("ev3_drive.py", "hub51515_drive.py", "buildhat_drive.py", "pi_servo_drive.py", "pi_tt_drive.py")
    for name in names:
        source = (ROOT / "walkers" / "controllers" / name).read_text(encoding="utf-8")
        ast.parse(source)
        assert "NOT RUN ON HARDWARE" in source, name
    assert "open loop" in (ROOT / "walkers" / "controllers" / "pi_tt_drive.py").read_text(encoding="utf-8")
    assert "open loop" in (ROOT / "walkers" / "controllers" / "pi_servo_drive.py").read_text(encoding="utf-8")


def test_page_figures_match_the_data(cfg):
    html = (ROOT / "site" / "walkers.html").read_text(encoding="utf-8")
    d, f = cfg["drives"], cfg["friction"]
    assert f"{d['servo360']['stall_torque_nm']['value']} N m against {d['tt']['stall_torque_nm']['value']}" in html
    assert f"{d['tt']['no_load_rpm']['value']:g} rpm against {d['servo360']['no_load_rpm']['value']:g}" in html
    assert (f"rubber and O-ring {f['o_ring']['value']}, TPU {f['tpu']['value']}, stock TT tyre {f['tt_tyre']['value']}, "
            f"bare plastic {f['pla']['value']}") in html
    assert "38 x 3, 50 x 3 or 58 x 3" in html
    assert "Analysed and simulated only, never built" in html
    assert "A bare printed wheel slips on a smooth floor" in html
    manifest = json.loads((ROOT / "stl" / "lego" / "manifest.json").read_text(encoding="utf-8"))
    files = [x for x in manifest["files"] if x["file"].startswith("wheeled/")]
    assert len(files) == 32
    assert {x["file"] for x in files if x["material"] == "TPU 95A"} == {
        "wheeled/tyre_tpu_d43.stl", "wheeled/tyre_tpu_d56.stl", "wheeled/tyre_tpu_d65.stl", "wheeled/idler_tyre_tpu.stl"}
