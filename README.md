# Microduck on Braccio servos and an Arduino UNO Q: simulation to real

A small printed biped, checked digitally before anything is printed:
assembled from its STL files and a model of the servos, tested for fit and
balance, described as URDF and MJCF, emulated in MuJoCo, and given the
firmware and tools to play the same joint commands on the real robot.

> **Status: verified in simulation only.** The robot has never been
> assembled or powered. The parts have not been printed as a set. The UNO Q
> sketch has not been built or flashed. Dimensions the makers do not publish
> are assumed and listed in [docs/assembly.md](docs/assembly.md).

![assembled robot at the neutral pose, interferences in red](docs/images/assembly-iso.png)

## The robot

A Microduck-style biped rebuilt around the six servos of a stock TinkerKit
Braccio kit. Four SR431 servos at the hips (two on the torso for hip roll,
one on each yoke for hip pitch), two SR311 servos at the far end of the
thighs for knee pitch, shins with fixed feet, a fixed head, an Arduino UNO Q
and the Braccio shield strapped to a deck, servos held by cable ties. Seven
printed parts and three fit-test pieces.

Six actuated joints: left and right hip roll, hip pitch, knee pitch. No yaw,
no ankles.

For comparison, Pollen Robotics' Microduck has five joints per leg (hip yaw,
roll, pitch, knee, ankle) and four in the neck and head, weighs about 800 g
and stands about 25 cm tall. This one has three per leg, weighs about 500 g
by the model and stands 283 mm.

## What the digital assembly test found

Full report with pictures: [docs/assembly.md](docs/assembly.md). Numbers:
[reports/assembly.json](reports/assembly.json).

- **Interference.** Each hip roll servo, centred in its torso cradle, runs
  into the deck: 1055 mm3 of overlap. The case end reaches 2 mm into the 4 mm
  plate and the mounting ear goes through the rest. The UNO Q centred between the deck rails
  overlaps the neck root by 3.3 mm; moving it 3.25 mm forward clears it.
- **Cable ties.** On every cradle one of the two ties is in line with the
  output shaft (slot pair 10.9 mm from the cradle centre, shaft 10.75 mm on
  the assumed SR431). Only the tie at the far end can pass over the case.
- **Fits.** Every case sits between its rails with 0.5 mm a side, fully on
  its plate; all tie slots are open; all six horn screw holes are on their
  shaft axes with a free path for a screwdriver. The board has 0.52 mm to
  each deck rail.
- **Joint sweeps.** Hip pitch turns a full half turn each way without
  contact. Hip roll is free from -55 to +180 degrees on the left (mirror on
  the right): inward, the shins meet. The knee is free from -137 to +115
  degrees. With 3 degrees of margin and the servos' 180 degrees of travel the
  limits are hip roll -52 to +90, hip pitch and knee -90 to +90.
- **Mass.** 501 g: servos 302 g (published), printed parts 144 g (PLA at 60
  percent of solid, assumed), board 30 g and shield 25 g (assumed). 597 g if
  printed solid.
- **Balance.** With the legs straight down the centre of mass is 8.8 mm
  behind the heels: it falls backward. With the thighs swung 45 degrees back
  and the knees turned to keep the soles level it is 37 mm inside the support
  polygon. That is the stand pose. On one foot it is 62 mm outside, and still
  38 mm outside with the stance hip rolled 30 degrees. It cannot stand on one
  foot.
- **An open choice.** The design does not say which face of the thigh meets
  the hip horn. Both were checked. With the horn on the rail face the feet
  are 172 mm apart; on the flat face, 320 mm. The description uses the rail
  face.

## What the simulation did

Full results: [docs/simulation.md](docs/simulation.md). Numbers:
[reports/sim.json](reports/sim.json).

- **It stands.** Ten seconds at the stand pose, peak tilt 0.2 degrees. The
  hip pitch servos need 0.09 N m of their 1.2 N m, the knees 0.02 of 0.30.
- **Straight legs fall.** At the neutral pose it tips backward in 0.4 s, as
  the assembly test predicted.
- **The gait shuffles.** The open-loop weight shift and step keeps the robot
  up for the whole run and moves it 41 mm in 11 s. Both feet stay on the
  floor the whole time. The best of 54 parameter sets inside the speed limit
  manages 101 mm in 11 s (9 mm/s). None fell. With no ankle and feet 172 mm
  apart the weight never gets onto one foot, so there is no step.
- **Watchdog.** Commands cut in mid gait: the controller holds and the robot
  stays up. Relaxed instead, it falls in 0.3 s.

![the default gait in simulation](docs/images/sim-gait.gif)

What the simulation suggests changing is listed at the end of
[docs/simulation.md](docs/simulation.md). Those are suggestions; the parts
are the owner's and were not edited.

## Walk, jump, sit: the motion study

Full results: [docs/motion.md](docs/motion.md). The servo model gains a dead
band, gear play, a series spring, the command delay and the 4 A supply limit,
and a seeded search looks for open-loop motions on the geometry as drawn and
on one variant. Simulation only.

- As drawn it does not truly step. The best gait found stamps along at
  11.7 mm/s: a sole clears the floor by 2.53 mm for 0.06 s while the
  standing foot slips further than the lifted foot advances, and the turn
  input does not steer it.
- The jump is a hop: nothing touches the floor for 0.08 s and the centre of
  mass rises 5.02 mm in that time. It needs the firmware speed limit raised and
  is not allowed on real hardware by default.
- Sitting is a squat on the servo travel stops, 58.2 mm lower. It holds
  with the servos relaxed, only the soles touch the floor, and standing up
  again takes 0.402 of the knee torque limit.
- Variant `comb_feet`, a proposal of the study and not the owner's design:
  new soles whose fingers cross the centreline and interleave. It steps at
  38.1 mm/s with 12.97 mm of clearance and turns at about 3.54 and -3.14 deg/s.
  The part change is specified in [docs/generator-changes.md](docs/generator-changes.md).

Motion files for both, with what each is allowed to do, are listed in
`trajectories/manifest.json`; `python scripts/run_motion.py` regenerates them.

## Simulation to real

One line format carries joint angles in degrees to the simulator and to the
board. A calibration table per servo (shield channel, zero, direction) and
the joint limits from the assembly test turn them into pulses. The firmware's
control core (soft limits, speed limit, watchdog, one-joint calibration) is
plain C++ that is also compiled for the host and compared, line for line,
with the Python controller that drives the simulator.

    python scripts/play.py trajectories/stand.csv              simulator
    python scripts/virtual_robot.py                            the simulator behind the board's socket
    python scripts/play.py trajectories/gait.csv --tcp 127.0.0.1:8766
    python scripts/play.py trajectories/stand.csv --tcp <uno-q>:8766 --real

Hardware links open only with `--real`. Steps, the command set and what was
reused from unoq-braccio-sketchbot: [docs/sim-to-real.md](docs/sim-to-real.md).
Power: [docs/power.md](docs/power.md). Six stalled servos can ask for about
10 A (assumed stall currents; the maker publishes none) against the kit's
5 V 4 A supply, and the UNO Q needs its own 5 V 3 A.

## Layout

| Path | What |
|---|---|
| `config/` | bought-part data with sources, placement assumptions, calibration, gait |
| `microduck/` | model, assembly test, renderer, description generator, simulator, protocol, player |
| `scripts/` | fetch the STLs, run each stage, regenerate everything, play, calibrate, virtual robot |
| `reports/` | generated: assembly and simulation results as JSON |
| `robot/` | generated: URDF, MJCF, joint table, viewer model |
| `trajectories/` | generated: stand and gait as CSV |
| `app_lab/microduck_agent/` | the UNO Q app: sketch for the microcontroller, relay for the Linux side |
| `docs/` | generated reports, pictures, sim-to-real steps, power, how to regenerate |
| `site/` | the GitHub Pages site |
| `tests/` | headless pytest suite |

## Running it

    python -m venv .venv
    .venv/Scripts/python -m pip install -r requirements-dev.txt
    .venv/Scripts/python -m pytest
    .venv/Scripts/python scripts/play.py trajectories/gait.csv

The simulation, the player and most tests run from what is committed. The
assembly test and the description generator need the printable STLs, which
are not in this repository:

    python scripts/regenerate.py --design-dir /path/to/microduck-braccio-unoq

See [docs/regenerate.md](docs/regenerate.md).

## The printable parts and where their shape comes from

The printable parts are flat plates with servo cradles, horn blanks and a
board deck. The design's generator took the convex outline of each of 15
Microduck meshes in one projection as the starting silhouette of a plate; no
surface, joint or mechanism of those meshes is in the parts, and the result
does not look like the original (see the pictures in
[docs/assembly.md](docs/assembly.md)). The idea of a small duck-like biped is
owed to the [Microduck by Pollen Robotics](https://github.com/pollen-robotics/microduck_rl).

The STLs are not committed; `scripts/fetch_stls.py` reads them from the local
design directory.

## Unverified

- Physical fit of anything: no part has been printed against a servo.
- Every assumed dimension: servo ears, shaft position, horn size, board and
  shield mass, print density and infill.
- Holding torque, backlash, tie slip, flex of the 4 mm plates.
- Floor friction and the contact model, on which the shuffle depends.
- Servo direction and zero in the calibration table.
- The sketch: not built, not flashed. `Serial` as the header UART, relax by
  zero duty and the `String` Bridge function are to be checked at first build.
- Stall currents, and how the Braccio shield shares power with the UNO Q.

## Publishing

1. Create the repository `eoinjordan/microduck-braccio-unoq-sim` on GitHub and
   push `main`.
2. In the repository settings, under Pages, set the source to GitHub Actions.
3. Run the "Publish Site" workflow, or push a change under `site/`. The site
   appears at https://eoinjordan.github.io/microduck-braccio-unoq-sim/.

## Licence

MIT for the code and documentation, see [LICENSE](LICENSE). Third-party
material and sources: [NOTICE](NOTICE).
