# Turning head (option, biped)

An option in place of the fixed camera mount: one small servo turns the
camera left and right, and the camera's tilt is set by hand. Geometry and the
assembly test only. It is not in the URDF, the MJCF, the simulation, the
joint command format or the firmware; those are for the fixed mount. Nothing
has been printed, fitted, wired or powered.

Numbers and pictures: the "Turning head" section of
[assembly.md](assembly.md). Parts: `stl/01_torso_unoq_pan_head.stl`,
`stl/head_pan_platform.stl`, `stl/head_tilt_cradle_<camera>.stl`, and the fit
piece `stl/fit_sg90_cradle.stl`.

## The servos the owner has

M5Stack's product pages (sources in `config/hardware.json`, `head_servo`):

| | Servo Kit 360 | Servo Kit 180 |
|---|---|---|
| Kind | continuous rotation: the pulse sets speed and direction, not angle | position servo, 0 to 180 degrees |
| Named as | "SG90 Servo 360" | "SG90 Servo 180" |
| Mass | 9 g | 9 g |
| Supply | 4.8 to 6.0 V | 4.8 to 6.0 V |
| Stall torque | 1.6 kg cm at 4.8 V | 1.6 kg cm at 4.8 V |
| Stall current | 750 mA | 750 mA |
| Signal | 50 Hz, 0.5 to 2.5 ms | 50 Hz, 0.5 to 2.5 ms |
| Listed size | 40 x 12 x 36 mm (the product, apparently with its bracket) | the same |

The BALA-C and BALA-C PLUS pages list "2 x 9G Servos", "rotation angle 360",
and a base with an L9110S motor driver behind an I2C microcontroller. That
suggests the BALA-C drives its two servos as plain motors rather than with
servo pulses; M5Stack does not say so outright. If the owner's servos came
out of a BALA-C base rather than a Servo Kit box, check that they still have
a three-wire servo lead and respond to pulses before planning around them.

Not published by M5Stack: the body dimensions of the servo alone, where the
shaft sits, the hole positions of the LEGO-compatible bracket and adapter
plates, the speed of the 360 version, its neutral pulse, and whether the 180
and 360 versions share a case. Both are named SG90, so the cradle here is
drawn for the generic SG90 body, to the largest of the figures two data
sheets give (23 x 12.5 mm body, 19.5 mm below the ears, ears 32.5 mm across),
and is assumed to take either version. The fit piece is how to find out.

## What a continuous servo means for a camera joint

A continuous-rotation servo has no position feedback. At a neutral pulse it
stops, more or less: the neutral point drifts with temperature and voltage
and has a dead band, so it can creep. It cannot be told to go to an angle and
it does not hold one against a load when the pulses stop.

So the design does this:

- **Pan only by servo.** The pan axis is vertical, so gravity does not turn
  it and a stopped servo stays put. Tilt would have to hold the camera
  against gravity, which this servo cannot do reliably, so tilt is a friction
  joint on one M3 screw, set by hand (10 degrees below level by default, free
  for about 12 degrees each way before the cradle meets the platform).
- **Printed end stops.** A peg under the platform meets a post each side of
  the servo at about 75 degrees left and right of centre. The camera lead
  needs slack for that travel and no more; the servo cannot wind it up.
- **Knowing the angle.** On power-up, turn slowly one way until the stop
  (long enough to cross the whole travel), call that -75 degrees, then turn
  back for a timed interval to reach centre. After that every move is timed.
  The speed of the 360 version is not published and varies with voltage and
  load, so expect an error of the order of 10 to 20 percent of each move,
  adding up: go back to a stop to re-home after a few moves. Running into a
  stop stalls the servo at up to 750 mA; keep the homing pulse close to
  neutral and short.
- **A better option, provided for.** Beside the left stop post there is a
  seat with two 2 mm holes 6.5 mm apart for a subminiature lever switch, so
  the stop can be sensed instead of stalled against. A potentiometer on the
  axis was not drawn.
- **The 180 degree version** of the same servo gives real position control
  and needs none of this. If its body is the SG90's it drops into the same
  pocket (assumed, not checked). With it the stops are a safety limit only.

## Holding the servo and the platform

The servo hangs through a pocket in a tab at the deck front, ears on the tab,
held by its own two screws in 1.6 mm pilot holes. The M5Stack kit's own
LEGO-compatible bracket is not used to hold the body because its dimensions
are not published.

The platform is 7.8 mm thick with four pin holes compatible with LEGO Technic
elements at 8 mm from the axis, and a centre hole for the horn screw. It is
meant to pin onto the kit's LEGO-compatible adapter plate on the servo
output. The hole pattern is the parameter `ADAPTER_HOLES` in the design's
`build.py`: measure the adapter with calipers and set it. With a plain SG90
horn, drill through the horn into the platform instead, as for the leg horns.
The height of the horn face above the deck (`PAN_SEAT_Z`, 18.5 mm) and the
shaft's distance from the body centre (5.6 mm) are assumed too.

LEGO, Technic, Mindstorms and SPIKE are trademarks of the LEGO Group, which
does not sponsor or endorse this.

## Signal and power

The Braccio shield's six channels drive the legs. Candidates for one more
servo signal, to be checked, not assumed:

- **A spare pin of the UNO Q.** The board's Zephyr core marks D2, D3, D5 to
  D13, D20 and D21 as PWM capable
  (https://raw.githubusercontent.com/arduino/ArduinoCore-zephyr/main/variants/arduino_uno_q_stm32u585xx/arduino_uno_q_stm32u585xx.overlay).
  The shield uses 3, 5, 6, 9, 10, 11 and 12, which leaves D2, D7, D8, D13,
  D20 and D21. Whether the shield brings those pins out, and whether the core
  can run one of them at 50 Hz beside the others, has not been checked.
- **A pin of the camera board.** On the AI-Thinker ESP32-CAM, GPIO 12, 13,
  14, 15 and 2 are free when the card slot is not used, and GPIO 4 lights the
  flash LED (https://randomnerdtutorials.com/esp32-cam-ai-thinker-pinout/, a
  third-party guide). That would keep the head self-contained. GPIO 12 is
  also a boot strapping pin on the ESP32, so prefer 13, 14 or 15.

Power: one servo adds up to 750 mA at 5 V when stalled against a stop and a
few tens of mA when turning freely (M5Stack gives 60 mA with no load). Take
it from the servo supply, not from the camera's or the UNO Q's 5 V pin.

No firmware for the head exists in this repository.

## Pixy on a pan-tilt base

For the builds with an EV3 brick the owner has a Pixy camera with Charmed
Labs' pan-tilt kit. `stl/head_pixy_plate_pixy2.stl` and
`stl/head_pixy_plate_pixy1.stl` are flat plates, 64 x 56 x 4 mm, with a pin
hole compatible with LEGO Technic elements in a pad at each corner (48 x 56
mm apart, on the 8 mm grid), two slots 3.2 mm wide and 20 mm long, 25 mm
apart, for the screws of the pan-tilt base, and, on the Pixy2 plate, the
three 3 mm board holes Charmed Labs dimensions, for mounting the camera
without the pan-tilt. The plates are not placed on the biped and were not
part of its assembly test.

Published by Charmed Labs: Pixy2 board 38.25 x 42 mm, 10 g, three 3 mm holes
at (5.1, 31.3), (16, 38.8) and (22.4, 38.8) mm from the top left corner
(https://docs.pixycam.com/wiki/doku.php?id=wiki:v2:dimensions); the pan-tilt
kit's two servos plug into the Pixy2 itself
(https://docs.pixycam.com/wiki/doku.php?id=wiki:v2:assembling_pantilt_mechanism).
Not published: the pan-tilt base's size and hole positions, so the slot
spacing and length are parameters to measure; and anything about the first
Pixy's board, for which the plate has slots only.

With an EV3: the Pixy answers an EV3 sensor port only when it runs the LEGO
version of its firmware
(https://docs.pixycam.com/wiki/doku.php?id=wiki:v2:can_i_use_my_regular_pixy_with_lego_mindstorms).
The documented EV3 block has no input that moves the pan-tilt servos
(https://docs.pixycam.com/wiki/doku.php?id=wiki:v2:pixy_lego_block), and no
page says the LEGO firmware runs them. As far as the documentation shows, the
EV3 cannot command the Pixy's pan-tilt; the pan-tilt demo runs on the Pixy
itself under its general firmware. Whether the standard edition takes the
LEGO firmware was not confirmed from the pages read.
