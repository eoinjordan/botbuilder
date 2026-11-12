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
| the design directory's `stl/` | the printable STLs, the fit pieces and `parameters.json`, as its `build.py` wrote them; copied into `stl/` here |
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
| `scripts/fetch_stls.py` | design directory | `stl/*.stl`, `stl/parameters.json`, `stl/manifest.json` |
| `scripts/run_assembly.py` | `stl`, `config/hardware.json`, `config/assembly.json` | `reports/assembly.json`, `docs/assembly.md`, `docs/images/*.png` |
| `scripts/generate_description.py` | `stl`, `reports/assembly.json`, `config/calibration.json` | `robot/microduck.urdf`, `robot/microduck.xml`, `robot/joints.json`, `robot/model.json`, `robot/clearance.json`, `app_lab/microduck_agent/sketch/DuckTable.h`, `build/microduck_visual.xml` |
| `scripts/run_sim.py` | `robot/`, `config/gait.json`, `config/calibration.json` | `reports/sim.json`, `docs/simulation.md`, `trajectories/*.csv`, `docs/images/sim-*.gif` |
| `scripts/validate_clearance.py` | `stl/`, `robot/clearance.json` | `reports/clearance.json` (the leg clearance rule against the meshes, about five minutes; not part of `regenerate.py`) |
| `scripts/optimise_motion.py` | `robot/`, `config/motion.json`, `config/presets.json` | `config/gaits.json`, `config/gait.json` (seeded search, about 25 minutes on eight cores; not part of `regenerate.py`) |
| `scripts/run_motion.py` | `robot/`, `stl/`, `config/motion.json`, `config/presets.json`, `config/gaits.json`, `reports/clearance.json` | `reports/motion.json`, `docs/motion.md`, `trajectories/{walk,turn_left,turn_right,sit,stand_up}.csv`, `trajectories/restricted/jump.csv`, `trajectories/manifest.json`, `trajectories/gait_params.json`, `docs/images/motion-*.gif` |
| `scripts/run_look.py --fetch` | the Microduck-look design directory (`MICRODUCK_LOOK_DESIGN_DIR`, default `../3d-print-designs/microduck-look`) | `stl/microduck-look/*.stl`, `parameters.json`, `LICENSE`, the comb feet and `comb_feet.json`, `manifest.json`, its entries in `stl/manifest.json`, `stl/thumbs/microduck-look/` |
| `scripts/run_look.py --comb-feet` | `stl/microduck-look/left_foot.stl`, `right_foot.stl`, `microduck/look/combfeet.py` | `stl/microduck-look/left_foot_comb.stl`, `right_foot_comb.stl`, `comb_feet.json`, the manifests and part pictures |
| `scripts/run_look.py` | `stl/microduck-look/` | `reports/microduck-look/assembly.json`, `summary.json`, `stl/microduck-look/images/`, `robot/microduck-look/`, `config/microduck-look/build.json`, `docs/microduck-look.md` (about two minutes; not part of `regenerate.py`) |
| `scripts/run_look.py --sim [--feet web or comb]` | the above, `microduck/look/sim.py` | the above and `reports/microduck-look/sim.json`, `config/microduck-look/gait.json`, `gait_comb.json` (seeded search for each set of feet, a few minutes each; the committed report was made with `--generations 25 --popsize 14`) |
| `python -m microduck.buildpics` | `config/builds.json`, `stl/`, the assembly and walkers models, `robot/lego/wheeled/viewer.json` | `docs/images/build-*.png`, `reports/builds.json` (the card pictures; about 40 seconds; not part of `regenerate.py`) |
| `python -m microduck.componentpics` | `config/component_images.json`, `config/hardware.json`, `config/bases.json`, `walkers/config/` | `docs/components/*.png` (the drawings), `reports/component_images.json`, `site/credits.html` (not part of `regenerate.py`) |
| `python -m microduck.sitechrome` | the masthead, footer and head tags it holds, `config/compat.json` (the trademark notice) | the shared regions of every `site/*.html` |
| `scripts/make_logo.py` | its own list of shapes, the colours of `site/style.css` | `site/assets/logo*.svg`, `favicon.svg`, the PNG icons, `social-preview.png`, `logo-preview.html` (not part of `regenerate.py`) |
| `scripts/build_site.py` | `reports/`, `robot/`, `docs/images/`, `stl/`, `config/hardware.json` | `site/data/`, `site/images/`, `site/stl/` (ignored by git; the Pages workflow runs this) |

Run the design's `build.py` and commit there first: the manifest records the
design commit the STLs came from, and a test refuses a manifest made from
uncommitted design changes. Without a design directory `fetch_stls.py` keeps
the committed `stl/`, so the other steps run from a plain checkout.

The outputs are deterministic on one machine: regenerating without changing
an input leaves `git status` clean. The tests check that the committed
description and firmware table match what the generator writes.

## Tests

    python -m pytest

The firmware control
core is compiled with the host `g++` or `clang++` if there is one.

## Previewing the site

    python scripts/build_site.py
    python -m http.server --directory site 8000

The site serves the STLs from `stl/` as downloads and uses them in the 3D view.
