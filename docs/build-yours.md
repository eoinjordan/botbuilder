# Build yours: the configurator

`site/build.html` asks what parts you have and answers with a recipe for that
duckbot. The answer starts with a status, because most combinations are not
buildable from what this project knows.

Nothing here has been printed, assembled or powered. Only one combination has
been analysed, and only in simulation.

## Status

| Status | Meaning |
|---|---|
| Analysed, stands in simulation | In `reports/assembly.json` and `reports/sim.json`. Today: the UNO Q biped with the Braccio shield, no camera, fixed head. |
| Being analysed | A crank walker or wheeled variant whose design and analysis are in progress on another branch. No mass, stability or speed figure is shown until its summary file exists. |
| Defined, not designed | The parts are named, but no complete design or analysis exists. Also what an analysed base becomes when a camera, a moving head or LEGO-compatible features are added. |
| Not possible | With the reason, and the nearest selection that is possible for the same controller. |

## What can be selected

- Controller: Arduino UNO Q, Raspberry Pi Zero 2 W, LEGO Robot Inventor 51515
  hub, LEGO EV3 brick, M5Stack Core.
- Locomotion: six-servo biped, two-motor crank walker, two driven wheels.
- Actuators and driver: Braccio servos on the Braccio shield or on an I2C
  servo driver; 51515 motors on the Build HAT or on the hub; EV3 motors on
  the brick or on the M5Stack BaseX; M5Stack 360 degree servos or yellow TT
  gear motors on an H-bridge board as wheel drives.
- Camera: none, a standard Pixy2 with its pan-tilt kit and LEGO cable, an
  AI-Thinker ESP32-CAM, a Raspberry Pi Camera Module 2.
- Head: fixed, the Pixy pan-tilt servos, an M5Stack 360 degree servo, a LEGO
  motor.
- LEGO-compatible features on or off.
- For wheels only: driven wheels at the front or back, a roller or a drag
  skid as third support, and the wheel: printed solid with an O-ring or
  rubber band (the default), printed hub with a TPU tyre, stock LEGO wheels,
  or the stock 65 mm TT wheel.

## Which locomotion each controller supports

The `support` table in `config/compat.json` is the only place that says this.

| Controller | Locomotion | Drive | Status source |
|---|---|---|---|
| UNO Q | biped | Braccio shield | analysed (reports/) |
| UNO Q | wheeled | 360 degree servos, or TT motors on an H-bridge | variants summary |
| Raspberry Pi Zero 2 W | biped | I2C servo driver | defined, not designed |
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

Which Pixy the owner has is not confirmed; Pixy2 is assumed.

## Where the data is

| File | Holds |
|---|---|
| `config/bases.json` | The six bases: outline, mass and its battery assumption, mounting, what it actuates, ports, power, cameras, Robot Creator family and code targets, status. Every figure is marked published (with the maker's URL), assumed (with the reason) or not verified. |
| `config/compat.json` | The options, the support table, the reasons for unsupported rows, and the rules that add recipe content or block a selection. |
| `microduck/recipe.py` | `evaluate(bundle, selection)`: a pure function that walks that data. Standard library only. |
| `site/build.js` | The same walk in JavaScript, and the page. It holds no combination of its own. |
| `site/data/recipe.json` | Written by `scripts/build_site.py`: both JSON files, the report figures, the STL manifest and the variants summary in one file for the page. |

`tests/test_recipe.py` evaluates every combination in Python, checks that
none is empty or contradicts itself and that impossible ones give a reason,
then runs `site/build.js` under Node over the same combinations and compares
the two results. The repository had no headless route for JavaScript; Node is
used when installed and the comparison is skipped when it is not.

    python -m microduck.recipe controller=ev3 locomotion=crank drive=ev3_motors lego=on

## Files from other branches

Both are optional. Without them the recipes show file names only and the
status "being analysed".

- `stl/manifest.json`: any JSON; every string in it ending in `.stl` is taken
  as a path under `stl/`. A recipe file is linked when a path equals its name
  or ends with `/` plus its name (for example `ev3-pixy2/chassis.stl`).
- `reports/variants/summary.json` or `reports/lego/summary.json`: any nesting
  of objects and lists. An object with a `status`, `mass_g`, `mass`,
  `verdict`, `stability` or `stability_verdict` key is an entry. Its
  controller, locomotion and drive are read from the fields `controller` or
  `base`, `locomotion` or `type`, and `drive` or `wheel_drive`, or from the
  keys on the path to it, using the names in `summary_aliases` in
  `config/compat.json`. Optional fields: `wheels`, `support`, `wheel` (to
  narrow an entry), `files` (STL names), `parts` (name, qty, note), `notes`.
  Only the statuses "analysed" and "analysed in simulation" give the
  analysed verdict; "defined..." gives defined; anything else is shown as
  written under "being analysed". An entry without a drive is used only
  where the controller has one drive for that locomotion.

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
- AI-Thinker ESP32-CAM figures against AI-Thinker's own page.
- Free PWM pins on the UNO Q under the Braccio shield.
- Pixy2 libraries on the UNO Q, the Raspberry Pi and an M5Stack Core.

LEGO, Mindstorms and Technic are trademarks of the LEGO Group, which does not
sponsor, authorise or endorse this project. Raspberry Pi is a trademark of
Raspberry Pi Ltd.
