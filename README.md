![Botbuilder](site/assets/logo.svg)

# Botbuilder: build your own bot from the parts you have

Printed robots for the controllers, motors and cameras you already own. The
site's first page shows five finished builds to pick from, and a
configurator beside them: pick a controller (Arduino UNO Q,
Raspberry Pi, LEGO 51515 hub, LEGO EV3 brick, M5Stack Core), a locomotion
(six-servo biped, two-motor crank walker, two driven wheels), a drive and a
camera, and it answers with what can honestly be said about that robot:
status first, then the files to print, parts, wiring, power and software.
See [Build yours](#build-yours).

The biped is the one design analysed so far, and most of this README is about
it. Site: https://eoinjordan.github.io/botbuilder/. What has been simulated,
checked or assumed, and the owner's own print checks, are in
[docs/status.md](docs/status.md).

## The biped: Microduck on Braccio servos and an Arduino UNO Q

A small printed biped, checked digitally before anything is printed:
assembled from its STL files and a model of the servos, tested for fit and
balance, described as URDF and MJCF, emulated in MuJoCo, and given the
firmware and tools to play the same joint commands on the real robot.

![assembled robot at the neutral pose, interferences in red](docs/images/assembly-iso.png)

## The robot

A Microduck-style biped rebuilt around the six servos of a stock TinkerKit
Braccio kit. Four SR431 servos at the hips (two on the torso for hip roll,
one on each yoke for hip pitch), two SR311 servos at the far end of the
thighs for knee pitch, shins with fixed comb feet whose fingers cross the
centre line, an Arduino UNO Q and the
Braccio shield strapped to a deck, a head at the front edge of the deck
with a round display as the eyes and a camera board above it, servos held by
cable ties. Seven printed parts and seven
fit-test pieces. The torso, thighs, shins and feet carry pin holes and studs
compatible with LEGO Technic and System elements, for decoration. LEGO,
Technic, Mindstorms and SPIKE are trademarks of the LEGO Group, which does
not sponsor or endorse this. The head is part of the torso: a Seeed Studio Round
Display for XIAO, screen forward, with an Espressif ESP-EYE above it by
default; the camera below, an AI-Thinker ESP32-CAM, the camera alone and a
turning head are options. See [docs/camera.md](docs/camera.md).

Six actuated joints: left and right hip roll, hip pitch, knee pitch. No yaw,
no ankles.

For comparison, Pollen Robotics' Microduck has five joints per leg (hip yaw,
roll, pitch, knee, ankle) and four in the neck and head, weighs about 800 g
and stands about 25 cm tall. This one has three per leg, weighs about 500 g
by the model and stands 314 mm to the top of the camera mount.

## What the digital assembly test found

Full report with pictures: [docs/assembly.md](docs/assembly.md). Numbers:
[reports/assembly.json](reports/assembly.json).

- **Interference.** None at the neutral pose. As first drawn each hip roll
  servo ran 2 mm into the deck and its ear went through it (1055 mm3); the
  cradles now hang 2.5 mm lower and the deck corner is cut away for the ear,
  which leaves 0.5 mm under the deck and 0.75 mm beside the assumed ear. The
  neck that the UNO Q ran into is gone with the head.
- **Face.** A round display stands in a ring at the deck front, screen
  forward as the eyes, with the ESP-EYE on a shelf above it between two
  posts with 0.5 mm each side, USB connector up so that the head is 124 mm
  tall and not 149 mm. Display, camera and print do not overlap. The lens
  looks the way the toes point, 10 degrees below level, 245 mm above the
  floor at the stand pose. A cone of 40 degrees half angle in front of it is
  clear at the neutral and stand poses and through the walk; a thigh has to
  come 15 degrees forward of straight down to enter it, and the walk keeps
  the thighs 47 to 60 degrees back. With the camera below the display
  instead the lens is at 192 mm. The display's size and mass are assumed,
  and its battery is strapped under the deck.
- **Other controllers.** The deck has torso variants for a Raspberry Pi Zero
  2 W, a full-size Raspberry Pi and the LEGO 51515 hub. As blocks of their
  mass they clear the print and the camera, and the robot still balances at
  a stand pose in each case: the heavier the controller, the further back
  the thighs go (38, 42 and 50 degrees; 63 with an EV3 brick of an assumed
  300 g, which has no torso of its own). The static stand margin stays near
  37 mm. Geometry and static balance only; none was simulated. Raspberry Pi
  is a trademark of Raspberry Pi Ltd.
- **Turning head, an option.** A second torso carries a 9 g servo under a tab
  at the deck front; it turns the camera 75 degrees each way between printed
  stops, and tilt is set by hand on one screw. It meets nothing, costs the
  legs no travel inside their limits and leaves the stand margin at 36.7 mm or
  more at either stop. It is geometry only, not in the simulation or the
  joint commands. The owner's M5Stack 360 servos are continuous rotation:
  [docs/head.md](docs/head.md) says what that means.
- **Cable ties.** Each cradle has four slot pairs. The two away from the
  shaft end give two tie paths over the case clear of the shaft and horn on
  all six cradles (assumed shaft position and horn size). As first drawn
  there were two pairs and one of them was in line with the shaft.
- **Fits.** Every case sits between its rails with 0.5 mm a side, fully on
  its plate; all tie slots are open; all six horn screw holes are on their
  shaft axes with a free path for a screwdriver. The board has 0.52 mm to
  each deck rail.
- **Joint sweeps.** The soles interleave, so one leg moved alone soon meets
  the other sole: hip roll 3 degrees inward, hip pitch 9 to 11 degrees, knee
  18 degrees. Whether the soles meet depends on both legs together, which a
  limit per joint cannot say, so the limits come from the sweeps with the
  two shin parts left out against each other: hip roll is then free from -39
  degrees (a finger reaches the other thigh) and hip pitch to +66. With 3
  degrees of margin and the servos' 180 degrees of travel the limits are
  hip roll -35 to +90, hip pitch -90 to +62, knee -90 to +90.
- **The two soles.** At the stand pose they are 9.8 mm apart at the nearest
  point. One sole can lead the other by 26 mm on the floor each way before
  they meet. Both hips rolled the same way, as in a weight shift, stay clear
  for at least 50 degrees. The controller's limits do not stop one leg being
  driven into the other sole; a gait has to respect it.
- **Pin holes and studs.** 23 pin holes in pads of beam thickness and 32
  studs. Every hole is open for a 4.8 mm pin over 7.8 mm, at least 24 mm
  from a joint axis; none cost any joint range. At the stand pose, static
  balance carries about 750 g of decoration on the rear of the deck before
  the margin is gone; 100 g there leaves 34 mm of the 47 mm.
- **Mass.** 562 g: servos 302 g (published), printed parts 173 g (PLA at 60
  percent of solid, assumed), board 30 g and shield 25 g (assumed), camera
  8 g, display with its XIAO 15 g and its battery 8.5 g (all three
  assumed). 677 g if printed solid. The comb shins should be printed solid,
  which the 60 percent figure understates by a few grams.
- **Balance.** With the legs straight down the centre of mass is 2.7 mm
  behind the heels: it falls backward. With the thighs swung 52 degrees back
  and the knees turned to keep the soles level it is 47 mm inside the support
  polygon. That is the stand pose. On one foot alone, the other level with
  it, the centre of mass is inside the sole: by 32 mm on the left foot and
  21 mm on the right. With the flat soles it was 62 mm outside. This is
  static and rigid; the design README has a hand calculation of how much the
  sole and shin give (about 0.5 mm at the centre line in PLA).
- **An open choice.** The design does not say which face of the thigh meets
  the hip horn. Both were checked. With the horn on the rail face the feet
  are 60 mm apart, sole centre to sole centre, and the shins 172 mm; on the
  flat face the shins are 320 mm apart. The description uses the rail
  face.

## What the simulation did

Full results: [docs/simulation.md](docs/simulation.md). Numbers:
[reports/sim.json](reports/sim.json).

- **It stands.** Ten seconds at the stand pose, peak tilt 0.3 degrees. The
  hip pitch servos need 0.09 N m of their 1.2 N m, the knees 0.04 of 0.30.
- **Straight legs fall.** At the neutral pose it tips backward in 0.5 s, as
  the assembly test predicted.
- **The gait steps.** The gait in `config/gait.json`, tuned for the comb
  soles by the motion study below, keeps the robot up for the whole run and
  moves it 531 mm in 11 s (48.2 mm/s) in this first, simpler servo model. The
  feet leave the floor in turn: a whole sole lifts up to 6.03 mm and both
  feet are loaded 38 percent of the time. Of 54 parameter sets around it,
  18 ask for a pose the leg clearance rule refuses and were not run; the
  best of the other 36 inside the speed limit manages 370 mm in 11 s and
  0 fell.
- **Watchdog and power off.** Commands cut in mid gait: the controller holds
  and the robot stays up. With the pulses stopped at the stand pose it sinks
  until hip pitch and knee reach the ends of the servo travel and stays on
  its soles; that rests on the real servo stops being at 90 degrees and
  taking the weight, which is one of the open points in the status notes,
  so the watchdog default stays hold.

![the gait in simulation](docs/images/sim-gait.gif)

What the simulation suggests changing is listed at the end of
[docs/simulation.md](docs/simulation.md). Those are suggestions; the parts
are the owner's and were not edited.

## Walk, turn, jump, sit: the motion study

Full results: [docs/motion.md](docs/motion.md). The MuJoCo model with a
fuller servo (dead band, gear play, a series spring, the command delay, the
4 A supply limit) and a seeded search over the parameters of the gait in
`microduck/gait.py`.

- **It steps.** On the comb soles the tuned gait
  (`config/gait.json`) walks at 44.4 mm/s with a sole
  clear of the floor by 3.85 mm on 99 percent of its steps and a
  peak torque of 0.647 of the limit. It stayed up in all 30 runs over
  floor friction 0.3 to 1.0, mass 0.9 to 1.1 times and disturbed starts,
  worst peak torque 0.696. With flat soles the same search gives
  1.3 mm/s and no steps.
- **It drifts and does not steer.** Walking straight the heading turns by
  about 0.81 deg/s, more with a heavier head (96.2 degrees in 30 s with
  32 g more at the head, at 28.0 mm/s); the step difference does not steer it reliably, so turning is not offered to the control page.
  Tested envelope: forward [0.0, 1.0], turn [0.0, 0.0].
- **The jump is a hop** and stays locked: 0.06 s off the floor with the
  centre of mass rising 0.32 mm. It runs four servos at stall torque from
  a supply that cannot feed them and can strip gears or break parts.
- **Sit and power off.** The sit is a squat to the hip pitch limit. With the
  pulses stopped, in the squat or at the stand pose, the robot sinks on to
  the servo travel stops and stays on its soles; enabled again it stands up
  at 1.0 of the torque limit. Switched off in mid stride the legs fold
  together and one sole comes down against the other.
- **Leg clearance rule.** One joint inside its own limits can swing a comb
  sole into the other. The control core now refuses such a command
  (`ERR CLEAR`) and does not take such a step. Against the meshes over
  42400 poses: 0 accepted collisions, 11.5 percent of free poses refused.

Motions and the tested envelope for the control page:
`trajectories/manifest.json`. `python scripts/run_motion.py` regenerates them.

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

## Build yours

The site's landing page, `site/index.html`, opens with five finished builds
as cards (`config/builds.json`) and has a configurator beside the recipe: pick a
controller (UNO Q, Raspberry Pi, LEGO 51515 hub, LEGO EV3 brick, M5Stack
Core), a locomotion (the six-servo biped, the two-motor crank walker of the
LEGO prototypes, or two driven wheels), drive, camera and head, and read what
can honestly be said about that combination: analysed in simulation, checked
in the digital assembly only, being analysed, defined but not designed, or
not possible with the reason. Only the UNO Q biped with its default camera
has been simulated; other cameras, the two Raspberry Pi decks and the turning
head were checked in the digital assembly only; nothing has been built. The biped's findings are on
`site/biped.html`. Data and sources:
[docs/build-yours.md](docs/build-yours.md).

## Flash and control

The site has a Flash page that writes the SSH commands to install and flash
the App Lab app on a UNO Q (commands only; nothing is flashed from the
browser), and a Control page that drives the robot from a USB or Bluetooth
game controller. Control plays back in the page by default; the real robot
is reached through `app_lab/microduck_agent/control_server.py`, which serves
the same page next to the robot's socket. See [docs/flash.md](docs/flash.md) and
[docs/control.md](docs/control.md).

## Crank walkers and two-wheeled builds

Three crank walkers of the owner's design on LEGO motors, for the EV3 brick,
the Robot Inventor 51515 hub and a Raspberry Pi Zero 2 W with the Build HAT:
printable parts in `stl/lego/`, programs in `programs/`, the assembly and
balance test and the MuJoCo simulation of the crank gait under `walkers/`.
Report: [docs/lego-walkers.md](docs/lego-walkers.md).

The same chassis carries a two-wheeled build for every controller: two driven
wheels (LEGO motors, 360-degree servos or yellow TT motors), a skid or ball,
printed wheels with an O-ring groove or a TPU tyre. Report:
[docs/wheeled-variants.md](docs/wheeled-variants.md). The LEGO programs load
through [Mindstorms Robot Creator](https://github.com/eoinjordan/mindstorms-robot-creator).

## Layout

| Path | What |
|---|---|
| `stl/` | the printable parts of the biped as generated, with a manifest |
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

Everything runs from what is committed, the printable STLs in `stl/`
included. To regenerate after changing the design or a configuration file:

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

The generated STLs are in `stl/`, listed in `stl/manifest.json` with what
each is, its size, checksum and the design commit it came from. They are the
files the assembly test read. `scripts/fetch_stls.py` copies them from the
local design directory after its generator has run.

## Publishing

1. Create the repository `eoinjordan/botbuilder` on GitHub and
   push `main`.
2. In the repository settings, under Pages, set the source to GitHub Actions.
3. Run the "Publish Site" workflow, or push a change under `site/`. The site
   appears at https://eoinjordan.github.io/botbuilder/.

## Licence

MIT for the code and documentation, see [LICENSE](LICENSE). Third-party
material and sources: [NOTICE](NOTICE).
