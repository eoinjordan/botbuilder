# Build yours: the configurator

The site's landing page, `site/index.html`, asks what parts you have and
answers with a recipe for that robot. The answer starts with a status,
because most combinations are not buildable from what this project knows.

Nothing here has been printed, assembled or powered. One combination has been
simulated, and only in simulation.

## Status

| Status | Meaning |
|---|---|
| Analysed, stands in simulation | Covered by `reports/assembly.json` and `reports/sim.json`: the UNO Q biped with the Braccio shield, the camera preset the reports were generated for, the camera mount with nothing moving, and the pin holes and studs on the parts. |
| Assembly checked, not simulated | In `reports/assembly.json` only: the UNO Q biped with one of the other camera presets; the biped on the Raspberry Pi Zero 2 W or the full-size Raspberry Pi torso (fit and static balance, the Pi and its servo driver as one block); and the UNO Q biped with the turning head (pan only between printed stops, tilt set by hand, no joint in the simulation or the command format). No simulation was run for any of them. |
| Being analysed | A crank walker or wheeled variant whose design and analysis are in progress on another branch. No mass, stability or speed figure is shown until its summary file exists. |
| Defined, not designed | The parts are named, but no complete design or analysis exists. Also what a covered biped becomes when the mount is left empty, the pin holes and studs are taken off, or the selection needs a torso that is not committed (a Pi deck with another camera or with the turning head, the turning head with a camera cradle that was not checked). |
| Not possible | With the reason, and the nearest selection that is possible for the same controller. |

What is "analysed" and what is "assembly checked" is read from the reports
each time the site is built, not written in the configurator's data: the
preset of the selected assembly variant is the simulated one; the entries
under `camera_presets`, `controllers` and `turning_head` are the
assembly-only ones.

As of this commit there are 51,840 distinct selections: 1 analysed, 6
assembly checked, 65 defined, 2,089 being analysed and 49,679 not possible.

The reports also put the 51515 hub and the EV3 brick on the servo biped as
carried blocks and give a static balance figure for each. Neither can drive
hobby servos, so both stay "not possible" as controllers of the biped; the
figure is shown in that answer as a note and changes no verdict.

## What can be selected

- Controller: Arduino UNO Q, Raspberry Pi Zero 2 W, full-size Raspberry Pi
  (biped only), LEGO Robot Inventor 51515 hub, LEGO EV3 brick, M5Stack Core.
- Locomotion: six-servo biped, two-motor crank walker, two driven wheels.
- Actuators and driver: Braccio servos on the Braccio shield or on an I2C
  servo driver; 51515 motors on the Build HAT or on the hub; EV3 motors on
  the brick or on the M5Stack BaseX; M5Stack 360 degree servos or yellow TT
  gear motors on an H-bridge board as wheel drives.
- Camera: none, AI-Thinker ESP32-CAM, Espressif ESP-EYE, Espressif
  ESP32-S3-EYE, a standard Pixy2 with its pan-tilt kit and LEGO cable, a
  Raspberry Pi Camera Module 2. On the biped the camera is one of the three
  ESP32 boards or none. "None" there means the mount is left empty: the
  mount is part of the torso, and the torso listed is the default preset's.
- Head: the camera mount with nothing moving; the biped's turning head with
  an SG90-class servo or an M5Stack 360 degree servo (pan only, tilt set by
  hand); the Pixy pan-tilt servos; a LEGO motor. The 360 degree servo turns
  continuously and holds no angle, and the recipe says so.
- Pin holes and studs compatible with LEGO elements, on or off. The committed
  biped parts have them; "off" means regenerating the parts with the design
  generator's `LEGO` switches (torso, thigh, shin, foot) set to False, and
  that set is not in the repository and was not analysed. The LEGO-motor
  bases need them on.
- For wheels only: driven wheels at the front or back, a roller or a drag
  skid as third support, and the wheel: printed solid with an O-ring or
  rubber band (the default), printed hub with a TPU tyre, stock LEGO wheels,
  or the stock 65 mm TT wheel.

The default camera is not written in the configurator's data. It is read
from `config/assembly.json` (`camera.preset`), the same value the assembly
test uses, so one switch changes both. The verdict still follows the reports:
after changing the preset, regenerate them.

## Which locomotion each controller supports

The `support` table in `config/compat.json` is the only place that says this.

| Controller | Locomotion | Drive | Status source |
|---|---|---|---|
| UNO Q | biped | Braccio shield | reports/, per camera preset and head |
| UNO Q | wheeled | 360 degree servos, or TT motors on an H-bridge | variants summary |
| Raspberry Pi Zero 2 W | biped | I2C servo driver | reports/ (assembly only) |
| Raspberry Pi, full size | biped | I2C servo driver | reports/ (assembly only) |
| Raspberry Pi Zero 2 W | crank walker, wheeled | 51515 motors on the Build HAT | variants summary |
| Raspberry Pi Zero 2 W | wheeled | 360 degree servos, or TT motors on an H-bridge | variants summary |
| 51515 hub | crank walker, wheeled | 51515 motors on the hub | variants summary |
| EV3 brick | crank walker, wheeled | EV3 motors on the brick | variants summary |
| M5Stack Core | crank walker, wheeled | EV3 motors on the BaseX | variants summary |

## Six joints and four ports

The biped has six position joints. The EV3 brick has four output ports, the
Build HAT four connectors and the BaseX four motor ports. The owner's LEGO
prototypes (the `microduck-lego` design directory) do not drive six joints:
each is a two-motor parallel-crank walker. One motor per side turns two
cranks through three 16-tooth gears, each leg hangs from the two crank tips,
and a third motor may pan the head. The configurator therefore offers the
LEGO-motor bases as that mechanism and refuses the biped on them, saying why.
The prototype README states that fit is untested and no walking controller
exists.

## The Pixy camera

From Charmed Labs' documentation (docs.pixycam.com):

- The LEGO cable connects a Pixy2 to an EV3 or NXT sensor port.
- A regular Pixy2 works with LEGO Mindstorms with that cable once "Data out
  port" is set to "LEGO I2C" in PixyMon. No firmware change is called for;
  Pixy2 for LEGO only ships with the LEGO firmware loaded. PixyMon's About
  box says which firmware a camera has.
- The pan-tilt servos plug into the Pixy2. The general API sets them with
  `setServos`. The EV3 block and the EV3 Python class have no servo call.
  Whether the Pixy2's own pan-tilt demo runs while it answers an EV3 is not
  stated: not verified.
- The 51515 hub's ports are LEGO Power Functions 2.0, a different connector.
  No connection is documented, so the configurator refuses that pairing.

Which Pixy the owner has is not confirmed; Pixy2 is assumed. Plates for a
Pixy2 and a first-generation Pixy with the pan-tilt base exist as parts in
`stl/`, but they are not placed on the biped and no check includes them, so
a Pixy on the biped is still refused and no recipe lists the plates.

## Where the data is

| File | Holds |
|---|---|
| `config/bases.json` | The six bases: outline, mass and its battery assumption, mounting, what it actuates, ports, power, cameras, Robot Creator family and code targets, status. Every figure is marked published (with the maker's URL), assumed (with the reason) or not verified. |
| `config/compat.json` | The options, the support table, the reasons for unsupported rows, and the rules that add recipe content or block a selection. |
| `config/assembly.json` | `camera.preset`: the default camera. |
| `stl/manifest.json` | The committed printable files. The biped's print list is chosen by each file's option fields: the six leg parts and the fit pieces with no controller, head or camera option; the torso whose controller, head and camera match the selection; the camera's fit piece for a fixed mount; and for the turning head its platform, fit piece and the cradle of the selected camera. `manifest_map` in `config/compat.json` gives the manifest's names for a controller or head. The hub torso and the Pixy plates are in no recipe. |
| `microduck/recipe.py` | `evaluate(bundle, selection)`: a pure function that walks that data. Standard library only. |
| `site/build.js` | The same walk in JavaScript, and the page. It holds no combination of its own. |
| `site/data/recipe.json` | Written by `scripts/build_site.py`: the data above, what the reports cover per camera, and the variants summary, in one file for the page. |

`tests/test_recipe.py` evaluates every combination in Python, checks that
none is empty or contradicts itself and that impossible ones give a reason,
then runs `site/build.js` under Node over the same combinations and compares
the two results. The repository had no headless route for JavaScript; Node is
used when installed and the comparison is skipped when it is not.

    python -m microduck.recipe controller=ev3 locomotion=crank drive=ev3_motors camera=none

## The site's pages

`index.html` is the configurator and `biped.html` the biped's findings.
Every page carries the same navigation block. Links to pages that other
branches add (`walkers.html`, `flash.html`, `control.html`) are in it but
hidden; `scripts/build_site.py` lists the ones that exist in
`data/pages.json` and `nav.js` shows only those, so there is no dead link.
A new page copies the `<nav id="site-nav">` block and loads `nav.js`.

## Files from other branches

- `stl/manifest.json`: read in its real shape, `files[]` with `file`, `what`
  and `options` (`part` or `fit_piece`, and `controller`, `head`, `camera`
  where they apply; a torso with no controller is the default controller's,
  from `stl/parameters.json`). Those files are copied
  into the site and linked there. Any other string in the manifest ending in
  `.stl` is also taken as a path under `stl/` and linked in the repository,
  so walker and wheeled files listed differently still resolve. A recipe file
  is linked when a path equals its name or ends with `/` plus its name (for
  example `ev3-pixy2/chassis.stl`).
- `reports/variants/summary.json` or `reports/lego/summary.json` (neither
  exists yet): any nesting of objects and lists. An object with a `status`,
  `mass_g`, `mass`, `verdict`, `stability` or `stability_verdict` key is an
  entry. Its controller, locomotion and drive are read from the fields
  `controller` or `base`, `locomotion` or `type`, and `drive` or
  `wheel_drive`, or from the keys on the path to it, using the names in
  `summary_aliases` in `config/compat.json`. Optional fields: `wheels`,
  `support`, `wheel` (to narrow an entry), `files` (STL names), `parts`
  (name, qty, note), `notes`. Only the statuses "analysed" and "analysed in
  simulation" give the analysed verdict; "defined..." gives defined; anything
  else is shown as written under "being analysed". An entry without a drive
  is used only where the controller has one drive for that locomotion.

## Not verified

Marked in the data, and repeated in the recipes that depend on them:

- EV3 brick dimensions and mass; EV3 motor torque and stall current from a
  LEGO document.
- Mass of the Raspberry Pi Zero 2 W, the Build HAT and its outline (the page
  gives a drawing only), the 51515 hub battery, an M5Stack Core.
- That the 51515 hub has the same body as the SPIKE Prime hub whose fact
  sheet gives 88 x 56 x 32 mm and 63 g without battery.
- Any specific I2C servo driver board, H-bridge board or TT motor.
- Whether the BALA-C's servos are the Servo Kit 360 part and take a PWM
  signal directly: the BALA-C base drives them through an L9110S driver.
- Free PWM pins on the UNO Q under the Braccio shield.
- Pixy2 libraries on the UNO Q, the Raspberry Pi and an M5Stack Core.
- The camera boards: see `config/hardware.json` and `docs/camera.md`.

LEGO, Mindstorms and Technic are trademarks of the LEGO Group, which does not
sponsor, authorise or endorse this project. Raspberry Pi is a trademark of
Raspberry Pi Ltd.
