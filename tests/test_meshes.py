# SPDX-License-Identifier: MIT
"""The printable STLs: present, closed, one body each, and the ones the
committed report was made from."""
import hashlib

import numpy as np
import pytest
import trimesh

from conftest import needs_stls
from microduck import model, render

ALL = {**model.PART_FILES, **{"fit_" + k: v for k, v in model.FIT_FILES.items()}}


@needs_stls
@pytest.mark.parametrize("name", sorted(ALL))
def test_stl_is_one_closed_solid(name):
    mesh = trimesh.load_mesh(model.stl_dir() / ALL[name])
    assert mesh.is_watertight
    assert mesh.is_volume
    assert mesh.volume > 0
    assert len(mesh.split()) == 1


@needs_stls
@pytest.mark.parametrize("name", sorted(model.PART_FILES))
def test_manifold_kernel_accepts_and_agrees_on_volume(name):
    mesh = trimesh.load_mesh(model.stl_dir() / model.PART_FILES[name])
    solid = model.load_part(name)
    assert solid.volume() == pytest.approx(mesh.volume, rel=1e-4)


@needs_stls
def test_report_was_made_from_these_stls(assembly_report):
    for filename, digest in assembly_report["stl_sha256"].items():
        assert hashlib.sha256((model.stl_dir() / filename).read_bytes()).hexdigest() == digest, filename


@needs_stls
def test_left_and_right_parts_are_mirror_sized():
    for part in ("yoke", "thigh", "shin"):
        left = np.asarray(model.load_part(f"left_{part}").bounding_box()).reshape(2, 3)
        right = np.asarray(model.load_part(f"right_{part}").bounding_box()).reshape(2, 3)
        assert np.allclose(left[1] - left[0], right[1] - right[0], atol=0.01)


def test_software_renderer_draws_a_box():
    vertices, faces = render.box_mesh([0, 0, 0], [10, 20, 30])
    image = render.render([(vertices, faces, (200, 50, 50))], "iso", (120, 90))
    pixels = np.asarray(image)
    assert pixels.shape == (90, 120, 3)
    assert (pixels != 255).any(axis=2).mean() > 0.1
