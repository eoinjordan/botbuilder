# Build yours: finished builds and the configurator

The site's landing page, `site/index.html`, opens with a row of finished
builds as cards. Choosing one shows its recipe: a short tag, the files to
print with their pictures, the parts, wiring, power, software, the numbers
from the analysis and the assembly steps. The configurator is the sidebar
beside the recipe: it asks what parts you have and changes the recipe to
that robot. A recipe can be linked, printed, saved as a PDF, or downloaded
as a zip with its STL files.

## Finished builds

`config/builds.json` lists them: id, name, one-line description, the
selection, the picture and the order. Nothing about them is written in the
page. A selection names only the fields that make the build; the rest take
the defaults, so the biped's camera follows `config/assembly.json`. Each
must resolve to a recipe tagged Simulated with files, part pictures and,
where one is written, a program: `tests/test_builds.py` fails for a build
that no longer does, instead of the card showing a lesser tag.

| Build | Selection | Picture drawn from |
|---|---|---|
| Microduck biped | UNO Q, six servos on the Braccio shield, round display eyes, comb feet | the assembly model at the stand pose |
| EV3 crank walker | EV3 brick, its own motors, Pixy2 in the fixed mount | the walkers model `ev3-pixy2` |
| 51515 hub crank walker | 51515 hub, its own motors, no camera | the walkers model `hub-51515` |
| Pi Build HAT crank walker | Pi Zero 2 W, Build HAT, 51515 motors, Pi camera | the walkers model `pi-zero-2w-51515` |
| Pi two-wheeled rover | Pi Zero 2 W, TT motors on an H-bridge, printed wheels with O-rings at the back, drag skid | `robot/lego/wheeled/viewer.json` |

The two-wheeled build is the Pi with TT motors because, of the UNO Q and Pi
builds in the variants summary with the wheels at the back, the TT drives
are the fastest (0.59 m/s against 0.44 with the Build HAT motors and 0.23
with the 360 degree servos), all climb 28 degrees, the skid takes an 8 mm
step where the ball takes 4 mm, and the Pi has a program written
(`programs/pi/wheeled/drive_tt.py`) where the UNO Q has none.

A card shows the picture, the name, the tag, the description, the
controller, how it moves, speed and mass from the reports, and the number of
printed parts. It shows "Printed and checked on <date>" when
`config/validated.json` has a record for the build, and nothing otherwise.

The cards are one radio group: Tab reaches the chosen card, the arrow keys
move through them and select. Choosing a card fills the sidebar with that
build. Changing any field makes a custom build: no card is selected, a
"Custom" note appears, and any card or "Back to the first finished build"
returns. On a screen wider than 860 px the sidebar is open beside the
recipe; narrower, it is behind its "Customise" control and the cards scroll
sideways inside their own row.

The address `?build=<id>` selects a finished build; `?build=<id>&lego=off`
starts from it and changes the fields named. The long form with every field
keeps working, and a long form that equals a finished build selects its
card.

`python -m microduck.buildpics` draws one 400 x 300 picture of each whole
robot into `docs/images/build-<id>.png`, all in the same three-quarter
view, and records in `reports/builds.json` the checksum of the picture and
of everything it was drawn from. A test compares both, so a changed part or
model cannot keep an old picture: run the command again after changing the
geometry. A build with no model of the whole robot gets its part pictures
side by side instead; none of the five needs that.

What has been simulated, checked or assumed is in [status.md](status.md), not
in the recipes.

## Tags

| Tag | Meaning |
|---|---|
| Simulated | In the reports: the biped's default build (`reports/assembly.json`, `reports/sim.json`), and every walker and two-wheeled build the variants summary lists as analysed in simulation. |
| Assembly checked | In `reports/assembly.json` only: the biped's other faces and cameras, the Raspberry Pi decks, the turning head. |
| Designed | Parts and files as far as they exist for the selection, with no numbers of its own. |
| In analysis | A walker or two-wheeled build with no summary entry yet. |
| Needs a part | Possible once the part the recipe names exists. |
| Not possible | A physical or electrical impossibility, with the reason and the nearest alternative. |

The tags are read when the site is built, from the reports and from
`reports/variants/summary.json`. They are not written in the configurator's
data. A build or a part the owner has printed and checked carries a dated
mark from `config/validated.json`; see [admin.md](admin.md).

## What can be selected

- Controller: Arduino UNO Q, Raspberry Pi Zero 2 W, full-size Raspberry Pi,
  LEGO Robot Inventor 51515 hub, LEGO EV3 brick, M5Stack Core.
- Locomotion: six-servo biped, two-motor crank walker, two driven wheels.
- Actuators and driver: Braccio servos on the Braccio shield or on an I2C
  servo driver; 51515 motors on the Build HAT or on the hub; EV3 motors on
  the brick or on the M5Stack BaseX; M5Stack 360 degree servos or yellow TT
  gear motors on an H-bridge board as wheel drives.
- Camera: none, Seeed XIAO ESP32S3 Sense, AI-Thinker ESP32-CAM, Espressif
  ESP-EYE, Espressif ESP32-S3-EYE, a standard Pixy2 with its pan-tilt kit and
  LEGO cable, a Raspberry Pi Camera Module 2.
- For the biped, the face: the round display as the eyes with the camera
  above (the default) or below it, the display stack with the XIAO Sense
  camera looking forward, or the camera mount alone. And the feet: comb or
  flat.
- Head: the mount with nothing moving; the biped's turning head with an
  SG90-class servo or an M5Stack 360 degree servo (pan by servo, tilt set by
  hand); the Pixy pan-tilt servos; a LEGO motor.
- Pin holes and studs compatible with LEGO elements, on or off.
- For wheels: driven wheels at the front or back; a roller, a drag skid or a
  printed idler wheel as third support; and the wheel: printed solid with an
  O-ring or rubber band (the default), printed hub with a TPU tyre, stock
  LEGO wheels, or the stock 65 mm TT wheel.

The default camera, face and feet are not written in the configurator's
data. They are read from `config/assembly.json` (`camera.preset`, `face`,
`feet`), the values the assembly test uses, so one switch changes both.

## What is refused, and how the form shows it

Only physical or electrical impossibilities are refused:

- an EV3 brick or a 51515 hub driving hobby servos, or an H-bridge board
  (no such outputs);
- the six-joint biped on LEGO motors (a different mechanism: the crank
  walker), and continuous-rotation drives as leg joints;
- the Braccio servos as a wheel or crank drive (they turn 180 degrees);
- a Build HAT on anything but a Raspberry Pi, and motors or bases on a
  controller whose connector they do not fit;
- the Pi camera on anything but a Raspberry Pi (CSI connector);
- the Pixy on the 51515 hub (LPF2 ports; Charmed Labs documents no
  connection);
- the Pixy pan-tilt head without the Pixy, a hobby-servo head on a LEGO
  controller, a LEGO-motor head without a LEGO motor port;
- on the biped, the display stack without its XIAO Sense camera, and that
  camera without the stack.

Two more are "needs a part": the crank walker on TT motors or 360 degree
servos (a coupling to the gear axle), and the biped on an M5Stack Core (a
torso deck for it).

In the form an option that cannot work with the chosen controller is greyed
out, with its short reason as a tooltip and in the list "Why some options
are greyed out" under the form. A possible option is selectable and, when
chosen, brings the other fields to a compatible state: choosing the EV3
brick selects its crank walker and motors. A link that names every field is
taken as written and may answer "Not possible" with the nearest alternative;
a link that names only some (`?locomotion=wheeled`) is completed.

## Pictures of the bought parts

Every field of the sidebar shows a picture of the chosen option beside it,
and "Pictures" under the field lists all its options as picture buttons;
the field itself stays a native list, which is what a phone and a keyboard
use. The parts list of a recipe shows each bought part with its picture,
and the PDF carries the same pictures with their credits on its last page.

`config/component_images.json` lists the components: openly licensed
photographs from Wikimedia Commons, with author, licence and source as the
file's own page gives them, and drawings made from the dimensions in
`config/hardware.json`, `config/bases.json` and `walkers/config/`. Choices
that are not bought parts (feet, face, wheel end) use the project's own
renders. `site/credits.html`, linked from every footer, is generated from
that file. To replace any picture with a photograph of your own, see
[components/README.md](components/README.md).

## The tour

`site/tour.js` is a guided tour of the site, loaded on every page after the
page's own script. Its steps are content, in `config/tour.json`: the page a
step is on, the control it points at, a title and a short text. A new
visitor to the landing page gets a small "New here?" card to start it or
send it away; it never opens over the page unasked. "Take the tour" in
every footer and the address `?tour=1` start it at any time. It moves
between pages by itself, keeping its place in the session and, in case
nothing can be stored, in the address (`?tourstep=<n>`). A control that is
hidden is opened first (the sidebar on a phone); one that is missing gets a
centred card. `localStorage` `botbuilder-tour` set to `off`, or `?tour=0`,
switches it off; the page tests run that way.

## Where the data is

| File | Holds |
|---|---|
| `config/compat.json` | The options, the `support` table (the one place that says which locomotion each controller supports and through which drive), the reasons for the rest, and the rules that add recipe content or block a selection. |
| `config/bases.json` | The controller bases with the makers' figures and sources. |
| `config/assembly.json` | The default camera, face and feet. |
| `config/builds.json` | The finished builds on the cards. |
| `config/tour.json` | The steps of the tour. |
| `config/component_images.json` | The picture of every choice and bought part, with origin, author and licence. |
| `reports/builds.json` | The card pictures and what each was drawn from. |
| `config/validated.json` | The owner's own checks. |
| `stl/manifest.json` | Every printable file with its options and its picture. The biped's print list is chosen by those options: controller, head, face, camera, feet. |
| `reports/assembly.json`, `reports/sim.json` | What was run for the biped. |
| `reports/variants/summary.json` | One entry per walker and two-wheeled build: tag, numbers, files and parts. |
| `programs/index.json` | The program files with their ports and how each is loaded. |
| `microduck/recipe.py` | `evaluate(bundle, selection)`: a pure function that walks that data. Standard library only. |
| `site/build.js` | The same walk in JavaScript, and the page. It holds no combination of its own. |
| `site/export.js` | The PDF and the zip, written in the page with no library. |
| `site/data/recipe.json` | Written by `scripts/build_site.py`: all of the above in one file for the page. |

`tests/test_recipe.py` evaluates every selection in Python, checks that none
is empty or contradicts itself and that only the reasons above refuse one,
then runs `site/build.js` under Node over the same selections and compares
the two results. Node is used when installed; the comparison is skipped when
it is not.

    python -m microduck.recipe controller=ev3 locomotion=crank drive=ev3_motors camera=pixy2

## Programs

For a build with program files the software section lists each one with its
ports, its address on the site (`programs/<controller>/<build>/<file>.py`),
a link that opens it in Robot Creator, and what Robot Creator does with it:
it sends and runs a Pybricks program on the 51515 hub, hands a LEGO app
program over USB or as an `.lms` file, and for an EV3 shows the manual steps,
because it has no way to send a program to an EV3. The Flash page lists the
same programs when a recipe links to it with a LEGO or Raspberry Pi base.

## Part pictures, PDF and zip

`python -m microduck.thumbs` draws a 320 x 240 picture of every STL under
`stl/` with the repository's software rasteriser and records each in the
manifest with the checksum of the STL it shows; a test fails if a part
changes and its picture does not. `scripts/fetch_stls.py` runs it after
writing the manifest.

The PDF is written by `site/export.js` in the browser: text in the standard
Helvetica faces and the pictures copied in as they are (a PNG's compressed
rows are what a PDF image with a PNG predictor holds). No library is loaded,
so the site gains no dependency and the output is tested here: the tests
read the file's cross-reference table, page count, text and image streams.
The Print button and the print stylesheet give the same recipe through the
browser's own "Save as PDF". The zip holds the PDF, the recipe as JSON and
the recipe's STL files.

## The site's pages

`index.html` is the finished builds and the configurator; `biped.html`, `wheeled.html` and
`walkers.html` are the three robot types; `flash.html` and `control.html`
are the tools; `about.html`, `admin.html` and the generated `credits.html`
are linked from the footer; `404.html` is what GitHub Pages serves for an
address that is not there.

The icon and preview tags of the head, the masthead and the footer links
are written into every page by `python -m microduck.sitechrome`, between
comment marks named `shared:head`, `shared:masthead` and `shared:footer`. Change the masthead or the footer there and run
it; a test fails for a page that differs. A new page copies the three empty
marked regions from `about.html`. Every page carries
the same navigation block, ending with the owner's robot-arm project as a
link that opens in a new tab. A new page loads `nav.js`; if it is listed in `OPTIONAL_PAGES` in
`scripts/build_site.py` its link may be written `hidden` with a `data-page`
attribute and is then shown only when the page exists.

The logo in every masthead, the browser icons and the preview picture for
links are written by `python scripts/make_logo.py` from one list of shapes:
a robot head inside a gear with a screwdriver as its antenna, in the site's
green and ink. `site/assets/logo-preview.html` shows it at several sizes.

LEGO, Mindstorms and Technic are trademarks of the LEGO Group, which does not
sponsor, authorise or endorse this project. Raspberry Pi is a trademark of
Raspberry Pi Ltd.
