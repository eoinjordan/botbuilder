# SPDX-License-Identifier: MIT
"""The generated URDF and MJCF load in MuJoCo and agree with the joint table."""
import mujoco
import numpy as np
import pytest

from conftest import ROOT, needs_stls
from microduck import describe, model
from microduck.model import JOINTS

XML = ROOT / "robot" / "microduck.xml"
URDF = ROOT / "robot" / "microduck.urdf"


@pytest.fixture(scope="module")
def mj():
    return mujoco.MjModel.from_xml_path(str(XML))


def test_mjcf_loads_with_six_actuated_joints(mj):
    assert mj.nu == 6
    assert mj.njnt == 7        # six hinges and the free joint
    names = [mujoco.mj_id2name(mj, mujoco.mjtObj.mjOBJ_ACTUATOR, i) for i in range(mj.nu)]
    assert names == JOINTS


def test_mjcf_limits_match_the_joint_table(mj, joints):
    for i, name in enumerate(JOINTS):
        j = joints["joints"][name]
        joint_id = mujoco.mj_name2id(mj, mujoco.mjtObj.mjOBJ_JOINT, name)
        assert np.degrees(mj.jnt_range[joint_id]) == pytest.approx([j["min_deg"], j["max_deg"]], abs=1e-3)
        assert mj.actuator_forcerange[i] == pytest.approx([-j["torque_limit_nm"], j["torque_limit_nm"]])
        assert np.degrees(mj.actuator_ctrlrange[i]) == pytest.approx([j["min_deg"], j["max_deg"]], abs=1e-3)
        # damping = stall torque / no-load speed
        dof = mj.jnt_dofadr[joint_id]
        assert mj.dof_damping[dof] == pytest.approx(j["torque_limit_nm"] / np.radians(j["speed_limit_deg_s"]), rel=1e-3)


def test_servo_limits_come_from_the_published_figures(joints):
    hardware = model.load_json("hardware.json")
    for name in JOINTS:
        j = joints["joints"][name]
        pub = hardware["servos"][j["servo"]]["published"]
        assert j["torque_limit_nm"] == pytest.approx(pub["torque_kgcm_4v8"] * 9.80665 / 100.0, abs=1e-3)
        assert j["speed_limit_deg_s"] == pytest.approx(60.0 / pub["speed_s_per_60deg_4v8"], abs=0.1)
        assert j["servo"] == ("SR311" if name.endswith("knee") else "SR431")


def test_mjcf_mass_matches_the_assembly_report(mj, selected, joints):
    total = float(mj.body_mass.sum())
    assert total == pytest.approx(selected["mass"]["total_g"] / 1000.0, abs=1e-3)
    assert total == pytest.approx(joints["mass_kg"], abs=1e-3)
    assert (mj.body_inertia[1:] > 0).all()


def test_joint_limits_match_the_assembly_report(selected, joints):
    for name in JOINTS:
        assert joints["joints"][name]["min_deg"] == selected["joint_limits_deg"][name]["min_deg"]
        assert joints["joints"][name]["max_deg"] == selected["joint_limits_deg"][name]["max_deg"]
    assert joints["stand_pose_deg"] == selected["balance"]["stand_pose"]["q_deg"]


@pytest.mark.parametrize("key", ["neutral", "stand"])
def test_keyframes_put_the_soles_on_the_floor(mj, key):
    data = mujoco.MjData(mj)
    mujoco.mj_resetDataKeyframe(mj, data, mujoco.mj_name2id(mj, mujoco.mjtObj.mjOBJ_KEY, key))
    mujoco.mj_forward(mj, data)
    lowest = []
    for g in range(mj.ngeom):
        if mj.geom_type[g] != mujoco.mjtGeom.mjGEOM_BOX:
            continue
        size = mj.geom_size[g]
        corners = np.array([[x * size[0], y * size[1], z * size[2]] for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)])
        lowest.append((data.geom_xpos[g] + corners @ data.geom_xmat[g].reshape(3, 3).T)[:, 2].min())
    assert min(lowest) == pytest.approx(0.0, abs=2e-4), "the lowest point of the robot rests on the floor"
    feet = sorted(lowest)[:2]
    assert feet[1] == pytest.approx(0.0, abs=2e-4), "both soles are on the floor"


def test_urdf_loads_in_mujoco(joints):
    urdf = mujoco.MjModel.from_xml_path(str(URDF))
    assert urdf.njnt == 6
    for name in JOINTS:
        joint_id = mujoco.mj_name2id(urdf, mujoco.mjtObj.mjOBJ_JOINT, name)
        assert joint_id >= 0
        j = joints["joints"][name]
        assert np.degrees(urdf.jnt_range[joint_id]) == pytest.approx([j["min_deg"], j["max_deg"]], abs=1e-3)
        assert urdf.jnt_axis[joint_id] == pytest.approx(j["axis"])


def test_urdf_and_mjcf_agree_on_link_masses(mj):
    urdf = mujoco.MjModel.from_xml_path(str(URDF))
    for name in ("left_hip", "left_thigh", "left_shin", "right_hip", "right_thigh", "right_shin"):
        a = mj.body_mass[mujoco.mj_name2id(mj, mujoco.mjtObj.mjOBJ_BODY, name)]
        b = urdf.body_mass[mujoco.mj_name2id(urdf, mujoco.mjtObj.mjOBJ_BODY, name)]
        assert a == pytest.approx(b, rel=1e-4)


def test_viewer_model_matches_the_joint_table(joints):
    import json
    with open(ROOT / "robot" / "model.json", encoding="utf-8") as handle:
        viewer = json.load(handle)
    by_joint = {link["joint"]: link for link in viewer["links"] if "joint" in link}
    assert sorted(by_joint) == sorted(JOINTS)
    for name in JOINTS:
        assert by_joint[name]["min_deg"] == joints["joints"][name]["min_deg"]
        assert by_joint[name]["max_deg"] == joints["joints"][name]["max_deg"]


@needs_stls
def test_description_is_up_to_date(assembly_report, robot_with_meshes):
    """Regenerating from the STLs gives the committed files, byte for byte."""
    table = describe.joint_table(robot_with_meshes, assembly_report)
    shapes = describe.link_shapes(robot_with_meshes)
    assert describe.mjcf(robot_with_meshes, table, shapes) == XML.read_text(encoding="utf-8")
    assert describe.urdf(robot_with_meshes, table, shapes) == URDF.read_text(encoding="utf-8")
