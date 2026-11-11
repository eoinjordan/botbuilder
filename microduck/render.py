# SPDX-License-Identifier: MIT
"""Orthographic software renderer for triangle meshes.

A z-buffer rasteriser in NumPy. It needs no GPU, no window and no OpenGL, so
the assembly pictures come out the same on a laptop and on a CI runner.
"""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw

# Camera rotations: rows are the camera x (right), y (up) and z (towards the
# viewer) axes written in world coordinates. World is x forward, y left, z up.
VIEWS = {
    "front": np.array([[0, 1, 0], [0, 0, 1], [1, 0, 0]], float),
    "back": np.array([[0, -1, 0], [0, 0, 1], [-1, 0, 0]], float),
    "left": np.array([[-1, 0, 0], [0, 0, 1], [0, 1, 0]], float),
    "right": np.array([[1, 0, 0], [0, 0, 1], [0, -1, 0]], float),
    "top": np.array([[0, -1, 0], [1, 0, 0], [0, 0, 1]], float),
}


def iso_view(azimuth_deg: float = 35.0, elevation_deg: float = 22.0) -> np.ndarray:
    """Camera looking at the origin from the front left, above."""
    az = np.radians(azimuth_deg)
    el = np.radians(elevation_deg)
    toward = np.array([np.cos(el) * np.cos(az), np.cos(el) * np.sin(az), np.sin(el)])
    right = np.cross([0.0, 0.0, 1.0], toward)
    right /= np.linalg.norm(right)
    up = np.cross(toward, right)
    return np.vstack([right, up, toward])


VIEWS["iso"] = iso_view()
VIEWS["iso_back"] = iso_view(145.0, 22.0)


def _raster(buf, zbuf, pts, depth, faces, colors, shade, xray):
    h, w = zbuf.shape
    a = pts[faces[:, 0]]
    b = pts[faces[:, 1]]
    c = pts[faces[:, 2]]
    area = (b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1]) - (b[:, 1] - a[:, 1]) * (c[:, 0] - a[:, 0])
    lo = np.floor(np.minimum(np.minimum(a, b), c)).astype(int)
    hi = np.ceil(np.maximum(np.maximum(a, b), c)).astype(int)
    for i in np.nonzero(np.abs(area) > 1e-9)[0]:
        x0, y0 = max(lo[i, 0], 0), max(lo[i, 1], 0)
        x1, y1 = min(hi[i, 0], w - 1), min(hi[i, 1], h - 1)
        if x1 < x0 or y1 < y0:
            continue
        xs = np.arange(x0, x1 + 1) + 0.5
        ys = np.arange(y0, y1 + 1) + 0.5
        gx, gy = np.meshgrid(xs, ys)
        w0 = ((b[i, 0] - gx) * (c[i, 1] - gy) - (b[i, 1] - gy) * (c[i, 0] - gx)) / area[i]
        w1 = ((c[i, 0] - gx) * (a[i, 1] - gy) - (c[i, 1] - gy) * (a[i, 0] - gx)) / area[i]
        w2 = 1.0 - w0 - w1
        inside = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
        if not inside.any():
            continue
        f = faces[i]
        z = w0 * depth[f[0]] + w1 * depth[f[1]] + w2 * depth[f[2]]
        zs = zbuf[y0:y1 + 1, x0:x1 + 1]
        region = buf[y0:y1 + 1, x0:x1 + 1]
        if xray:
            region[inside] = 0.35 * region[inside] + 0.65 * colors[i] * shade[i]
        else:
            hit = inside & (z > zs)
            zs[hit] = z[hit]
            region[hit] = colors[i] * shade[i]


def render(items, view="iso", size=(900, 700), overlays=(), bounds=None,
           background=(255, 255, 255), supersample=2, margin=0.06, title=None):
    """Render meshes to a PIL image.

    items and overlays are sequences of (vertices Nx3, faces Mx3, rgb 0..255).
    Overlays are drawn last without a depth test, so buried volumes stay
    visible. bounds, if given, is a (2, 3) world box to frame instead of the
    extent of the items.
    """
    rot = VIEWS[view] if isinstance(view, str) else np.asarray(view, float)
    w, h = size[0] * supersample, size[1] * supersample
    buf = np.empty((h, w, 3), float)
    buf[:] = background
    zbuf = np.full((h, w), -np.inf)

    if bounds is None:
        allv = np.vstack([np.asarray(v, float) for v, _, _ in items])
        bounds = np.array([allv.min(axis=0), allv.max(axis=0)])
    bounds = np.asarray(bounds, float)
    corners = np.array([[bounds[i, 0], bounds[j, 1], bounds[k, 2]]
                        for i in (0, 1) for j in (0, 1) for k in (0, 1)])
    cam = corners @ rot.T
    cmin, cmax = cam.min(axis=0), cam.max(axis=0)
    span = np.maximum(cmax[:2] - cmin[:2], 1e-6)
    scale = min(w / span[0], h / span[1]) * (1.0 - 2.0 * margin)
    centre = 0.5 * (cmin[:2] + cmax[:2])

    light = np.array([0.35, 0.45, 0.82])
    light /= np.linalg.norm(light)

    def draw(batch, xray):
        for verts, faces, rgb in batch:
            verts = np.asarray(verts, float)
            faces = np.asarray(faces, int)
            if len(faces) == 0:
                continue
            p = verts @ rot.T
            pts = np.empty((len(p), 2))
            pts[:, 0] = (p[:, 0] - centre[0]) * scale + w / 2.0
            pts[:, 1] = h / 2.0 - (p[:, 1] - centre[1]) * scale
            tri = p[faces]
            normal = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
            length = np.linalg.norm(normal, axis=1)
            length[length == 0] = 1.0
            normal /= length[:, None]
            shade = 0.38 + 0.62 * np.abs(normal @ light)
            if not xray:
                keep = normal[:, 2] > -1e-9
                faces, shade = faces[keep], shade[keep]
            colors = np.tile(np.asarray(rgb, float), (len(faces), 1))
            _raster(buf, zbuf, pts, p[:, 2], faces, colors, shade[:, None], xray)

    draw(items, False)
    draw(overlays, True)
    image = Image.fromarray(np.clip(buf, 0, 255).astype(np.uint8))
    if supersample > 1:
        image = image.resize(size, Image.LANCZOS)
    if title:
        ImageDraw.Draw(image).text((10, 8), title, fill=(30, 40, 40))
    return image


def box_mesh(lo, hi):
    """Vertices and faces of an axis-aligned box, outward winding."""
    lo, hi = np.asarray(lo, float), np.asarray(hi, float)
    v = np.array([[lo[0], lo[1], lo[2]], [hi[0], lo[1], lo[2]], [hi[0], hi[1], lo[2]], [lo[0], hi[1], lo[2]],
                  [lo[0], lo[1], hi[2]], [hi[0], lo[1], hi[2]], [hi[0], hi[1], hi[2]], [lo[0], hi[1], hi[2]]])
    f = np.array([[0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7], [0, 1, 5], [0, 5, 4],
                  [1, 2, 6], [1, 6, 5], [2, 3, 7], [2, 7, 6], [3, 0, 4], [3, 4, 7]])
    return v, f
