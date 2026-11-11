# Status and assumptions

One place for what has been simulated, checked or assumed. The site, the
recipes and the README do not repeat it. Each recipe carries a short tag
instead: Simulated, Assembly checked, Designed, In analysis, Needs a part or
Not possible.

Builds and parts the owner has printed and checked himself are recorded in
`config/validated.json` and marked on the site with the date. That file is
the only source of such a mark; see [admin.md](admin.md).

## What the tags mean

| Tag | Meaning |
|---|---|
| Simulated | Digitally assembled (`reports/assembly.json`) and run in MuJoCo (`reports/sim.json`). |
| Assembly checked | In the digital assembly only: fit, mass and static balance. |
| Designed | Parts and files as far as they exist for that selection; no analysis numbers. |
| In analysis | Design and analysis in progress on the walkers and two-wheeled builds. |
| Needs a part | Possible once the part the recipe names exists. |
| Not possible | A physical or electrical impossibility, with the reason and the nearest alternative. |

## The biped, as it stood in the README

The robot has never been
assembled or powered. The parts have not been printed as a set. The UNO Q
sketch has not been built or flashed. Dimensions the makers do not publish
are assumed and listed in [docs/assembly.md](assembly.md).

The pages said the same in their own words: the Flash page's commands and
the Control page's real-robot path have been exercised against the virtual
robot (the simulator behind the board's socket) only, and the sketch has not
been built.

## Unverified

- Physical fit of anything: no part has been printed against a servo or a
  camera board.
- The pin holes and studs: no printed one has been tried with a real pin,
  beam or brick. Their nominal dimensions are from secondary sources.
- The other controllers: the masses of the Raspberry Pi boards, the hub's
  battery and the EV3 brick are estimates, and the full-size Pi's hole
  pattern and the EV3's size are not from their makers' pages.
- The turning head: the servo body, shaft position and horn height are
  assumed from SG90 data sheets, the adapter hole pattern is a guess to be
  measured, and no firmware drives it.
- The camera boards: only the ESP32-CAM outline and mass and the ESP32-S3-EYE
  outline are the makers' figures. Lens, button, connector and pin positions,
  board thickness and the other masses are assumed or scaled from pictures.
- The camera firmware on an ESP32-CAM: see [docs/camera.md](camera.md).
- Every assumed dimension: servo ears, shaft position, horn size, board and
  shield mass, print density and infill.
- Holding torque, backlash, tie slip, flex of the 4 mm plates.
- Floor friction and the contact model, on which the shuffle depends.
- Servo direction and zero in the calibration table.
- The sketch: not built, not flashed. `Serial` as the header UART, relax by
  zero duty and the `String` Bridge function are to be checked at first build.
- Stall currents, and how the Braccio shield shares power with the UNO Q.

## The configurator's data

Maker figures and their sources are in `config/bases.json` and
`config/hardware.json`; every figure there is marked published (with the
URL), assumed (with the reason) or not verified. From the first pass over
the makers' documentation:

- EV3 brick dimensions and mass, and EV3 motor torque and stall current, are
  not from a LEGO document.
- The mass of the Raspberry Pi boards, the Build HAT and its outline, the
  51515 hub battery and an M5Stack Core are estimates or missing.
- That the 51515 hub has the same body as the SPIKE Prime hub whose fact
  sheet gives 88 x 56 x 32 mm and 63 g without battery is assumed.
- No specific I2C servo driver board, H-bridge board or TT motor was checked
  against a maker's page. H-bridge pin names follow the chip data sheets.
- Stall currents of the Braccio servos are assumed (2.0 A and 1.0 A); the
  maker publishes none.
- Whether the BALA-C's servos are the Servo Kit 360 part and take a PWM
  signal directly is not established.
- The free PWM pins on the UNO Q under the Braccio shield are candidates
  read from the core's overlay.
- The Pixy2 on an EV3: Charmed Labs documents the LEGO cable and the LEGO
  I2C setting for a regular Pixy2; their EV3 block and Python class have no
  servo call, and whether the Pixy2's own pan-tilt program runs while it
  answers an EV3 is not stated.
- Pixy2 libraries on the UNO Q, the Raspberry Pi and an M5Stack Core were
  not tried.
- The XIAO ESP32S3 Sense head: mount files are being designed.
- Values a builder must measure are marked "measure" in the recipes: the
  M5Stack bracket and adapter hole patterns, the Pixy pan-tilt base, horn
  screws, wheel shafts and the battery size.
