# Regenerating everything

Nothing under `reports/`, `robot/`, `trajectories/`, `docs/assembly.md`,
`docs/simulation.md`, `docs/images/` or `DuckTable.h` is edited by hand. Change
an input, then regenerate.

## Setup

    python -m venv .venv
    .venv/Scripts/python -m pip install -r requirements-dev.txt     (Windows)
    .venv/bin/python -m pip install -r requirements-dev.txt         (Linux, macOS)

Python 3.11 or newer. No GPU. The packages are numpy, scipy, trimesh,
manifold3d, mujoco, pillow and pytest.

## Inputs

| Input | What it holds |
|---|---|
| the design directory's `stl/` | the seven printable STLs and three fit pieces (not in this repository) |
| `config/hardware.json` | servo, board and print data: published values with their source, assumed values with the reason |
| `config/assembly.json` | placement choices the design does not state; sweep step, limit margin |
| `config/calibration.json` | shield channel, pin, zero and direction per servo; speed limit; watchdog |
| `config/gait.json` | open-loop gait parameters |

## One command

    python scripts/regenerate.py --design-dir /path/to/microduck-braccio-unoq

The design directory defaults to `$MICRODUCK_DESIGN_DIR`, then to
`../3d-print-designs/microduck-braccio-unoq`. About a minute on a laptop.

## Step by step

| Step | Reads | Writes |
|---|---|---|
| `scripts/fetch_stls.py` | design directory | `build/stl/` (ignored by git) |
| `scripts/run_assembly.py` | `build/stl`, `config/hardware.json`, `config/assembly.json` | `reports/assembly.json`, `docs/assembly.md`, `docs/images/*.png` |
| `scripts/generate_description.py` | `build/stl`, `reports/assembly.json`, `config/calibration.json` | `robot/microduck.urdf`, `robot/microduck.xml`, `robot/joints.json`, `robot/model.json`, `app_lab/microduck_agent/sketch/DuckTable.h`, `build/microduck_visual.xml` |
| `scripts/run_sim.py` | `robot/`, `config/gait.json`, `config/calibration.json` | `reports/sim.json`, `docs/simulation.md`, `trajectories/*.csv`, `docs/images/sim-*.gif` |
| `scripts/optimise_motion.py` | `robot/`, `config/motion.json`, `config/presets.json` | `config/gaits.json` (seeded search, about 20 minutes on eight cores; not part of `regenerate.py`) |
| `scripts/run_motion.py` | `robot/`, `config/motion.json`, `config/presets.json`, `config/gaits.json` | `reports/motion.json`, `docs/motion.md`, `trajectories/<preset>_*.csv`, `trajectories/manifest.json`, `trajectories/gait_params.json`, `docs/images/motion-*.gif` |
| `scripts/build_site.py` | `reports/`, `robot/`, `docs/images/`, `config/hardware.json` | `site/data/`, `site/images/` (ignored by git; the Pages workflow runs this) |

Only the first three steps need the STLs. `run_sim.py`, `build_site.py` and
most of the tests run from what is committed.

The outputs are deterministic on one machine: regenerating without changing
an input leaves `git status` clean. The tests check that the committed
description and firmware table match what the generator writes.

## Tests

    python -m pytest

Tests that need the STLs skip when `build/stl` is empty. The firmware control
core is compiled with the host `g++` or `clang++` if there is one.

## Previewing the site

    python scripts/build_site.py
    python -m http.server --directory site 8000

Add `--with-meshes` to `build_site.py` to see the real part shapes in the 3D
view on your own machine. Do not publish a site built that way while the
licence of the source meshes is open (see NOTICE).
