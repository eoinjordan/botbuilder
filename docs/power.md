# Power

Nothing here has been measured. The figures are the makers' where a source is
given and assumptions where it says so.

## Published figures

| Item | Figure | Source |
|---|---|---|
| Braccio kit supply | regulated 5 V, 4000 mA | https://store-usa.arduino.cc/products/tinkerkit-braccio-robot |
| SR431 torque | 12.2 kg-cm at 4.8 V, 14.5 kg-cm at 6.0 V | same |
| SR431 speed | 0.20 s/60 deg at 4.8 V, 0.18 s/60 deg at 6.0 V | same |
| SR311 torque | 3.1 kg-cm at 4.8 V, 3.8 kg-cm at 6.0 V | same |
| SR311 speed | 0.14 s/60 deg at 4.8 V, 0.12 s/60 deg at 6.0 V | same |
| UNO Q USB-C input | 5 V, up to 3 A; the board asks for a 5 V / 3 A contract only | https://docs.arduino.cc/resources/datasheets/ABX00162-datasheet.pdf |
| UNO Q VIN | 7 to 24 V | same |
| UNO Q 5 V pin (5V_SYS) | 5 V, up to 3 A, diode-OR with the other inputs | same |

The Braccio shield feeds the servos from the kit supply at 5 V. The maker
rates the servos at 4.8 V and 6.0 V, so this repository uses the 4.8 V
figures: 1.196 N m and 300 deg/s for the SR431, 0.304 N m and 429 deg/s for
the SR311.

## Not published

The maker gives no stall or running current for either servo. Assumed here,
as typical for analog servos of these sizes at 5 V: 2.0 A stalled for an
SR431 and 1.0 A for an SR311.

## What follows

- Six stalled servos: 4 x 2.0 A + 2 x 1.0 A = 10 A, 2.5 times the 4 A kit
  supply. The arm the kit was sold for rarely stalls more than two joints at
  once; a biped that falls or jams can stall all six.
- In simulation the stand pose needs about 0.09 N m at each hip pitch servo
  (8 percent of its limit) and the estimated draw is about 0.5 A. The default
  gait peaks near 0.33 N m at the hips, about 1.1 A on average by the same
  estimate. These are estimates from torque, not currents.
- The UNO Q needs its own 5 V 3 A source on USB-C. Do not run the servos from
  the board's 5 V pin: its 3 A limit is below two stalled SR431s.
- Whether the Braccio shield joins its servo rail to the board's 5 V pin has
  not been checked on the UNO Q. Check the shield before powering both.
- The sketchbot repository found that energising six servos together browns
  the UNO Q out and resets it. The sketch here keeps its remedy: soft-start
  pin low, then high, 600 ms settle, then one joint every 180 ms.
- Size the supply and wiring for the stall figure, or fuse it, and put a
  switch in the servo supply within reach. A software stop or the watchdog
  does not cut power.
- The round display and its XIAO run from their own 3.7 V lithium cell under
  the deck and charge through the XIAO's USB-C port (about 485 mA, Seeed's
  figure). They take nothing from the 5 V supplies, which is an advantage:
  the eyes stay up when the servo rail sags. The camera board, if it is an
  ESP32-CAM or ESP-EYE, still needs 5 V.
- The camera board adds about 0.3 A at 5 V (ESP32-CAM, maker's figure with
  the flash LED on). Feed it from the controller side, not the servo rail.
  See [camera.md](camera.md).
- The optional turning head adds one 9 g servo: up to 0.75 A at 5 V when
  stalled against a stop (M5Stack's figure). See [head.md](head.md).
- The robot is tethered. No battery, regulator or charger is part of this
  design, and the mass and balance figures do not include one.
