# From simulation to the robot

Status: every step below the line "On the bench" is untested. The robot has
never been assembled or powered, and the sketch has not been built.

## One command format

The simulator and the board take the same ASCII lines, one command per line,
one reply per line. Angles are joint angles in degrees.

| Line | Meaning | Reply |
|---|---|---|
| `J q0 q1 q2 q3 q4 q5` | joint targets | `OK`, `OK CLAMP n`, `ERR CLEAR` (the target would bring one leg into the other), `ERR DISABLED`, `ERR CAL`, `ERR ARGS` |
| `E` | enable: soft start, then pulses one joint at a time | `OK` |
| `R` | relax: stop all pulses | `OK` |
| `S` | status | `STAT mode=RUN age_ms=40 wd=500 q=0.0,45.0,...` |
| `W ms hold` or `W ms relax` | watchdog time (100 to 10000 ms) and action | `OK` |
| `C index` | calibrate joint 0 to 5; only that joint moves | `OK` |
| `N delta` | nudge it by delta servo degrees, at most 2 | `CAL index servo=.. pulse=..` |
| `Z` | take the present servo angle as that joint's zero | `ZERO index servo_deg` |
| `X` | leave calibration (holds) | `OK` |

Joint order and convention (robot frame x forward, y left, z up):

| Index | Joint | Positive direction | Servo | Shield channel, pin |
|---|---|---|---|---|
| 0 | left_hip_roll | about +x: left foot moves out to the left | SR431 | M1, 11 |
| 1 | left_hip_pitch | about +y: foot moves backward | SR431 | M2, 10 |
| 2 | left_knee | about +y: foot moves backward | SR311 | M5, 5 |
| 3 | right_hip_roll | about +x: right foot moves in to the left | SR431 | M3, 9 |
| 4 | right_hip_pitch | about +y: foot moves backward | SR431 | M4, 6 |
| 5 | right_knee | about +y: foot moves backward | SR311 | M6, 3 |

Zero is the neutral pose: thighs straight down, shins vertical, soles level.
Numbers are strict decimals (no exponents). Tenths of a degree are sent.

What the board does with the lines, and the simulator does identically
because it runs the same logic (`microduck/protocol.py`, mirrored in
`app_lab/microduck_agent/sketch/DuckControl.hpp` and compared in the tests):

- Soft limits: targets are clamped to the joint limits from the assembly test.
- Speed limit: the commanded angle moves at most 120 deg/s (2.4 degrees per 20 ms tick).
- Watchdog: if no `J` line arrives for 500 ms while running, the board holds
  the present command. It can be set to relax instead; in simulation a relaxed
  robot falls in 0.3 s, so hold is the default.
- Starts relaxed. No pulse leaves the board before an `E` line.

## The calibration table

`config/calibration.json`, one row per servo:

    servo_deg = zero_deg + direction * joint_deg
    pulse_us  = 500 + servo_deg * 2000 / 180        (50 Hz)

`channel` and `pin` say where the servo is plugged in on the Braccio shield,
`zero_deg` is the servo angle at the joint's neutral position, `direction` is
+1 or -1. Joint limits are not in this file: they come from the assembly test
through `robot/joints.json`. `scripts/generate_description.py` merges both into
`DuckTable.h` for the sketch, so the board and the simulator read one table.

The shipped zeros (90) and directions are starting values. The directions
assume a servo turns its horn counter-clockwise, seen from the horn side, for
a longer pulse; that has not been checked on these servos.

## Trajectories and the player

A trajectory is a CSV: `t_ms` and the six joint angles, 50 rows a second.
`trajectories/stand.csv` holds the stand pose; `trajectories/gait.csv` is the
open-loop gait. `scripts/play.py` refuses a file that leaves the joint limits
or the speed limit, then sends it row by row:

    python scripts/play.py trajectories/stand.csv                      simulator
    python scripts/virtual_robot.py                                    simulator behind the board's socket
    python scripts/play.py trajectories/gait.csv --tcp 127.0.0.1:8766  the same, over TCP
    python scripts/play.py trajectories/stand.csv --tcp <uno-q>:8766 --real
    python scripts/play.py trajectories/stand.csv --serial COM7 --real

Without `--real` the player opens nothing but the simulator or a socket on
this machine.

## The board side

`app_lab/microduck_agent` is an Arduino App Lab app in the form of the
sketchbot's `braccio_remote_agent`:

- `sketch/` runs on the UNO Q's STM32 (fqbn `arduino:zephyr:unoq`). It keeps
  the control loop and offers one Bridge function, `duck_line`. It also reads
  the same lines from the header UART (`Serial`, 115200 baud).
- `python/main.py` runs on the Linux side, listens on TCP port 8766 and
  relays each line to `duck_line`.

Reused from unoq-braccio-sketchbot: `BraccioPulse.hpp` unchanged (500 to 2500
us at 50 Hz as a 16-bit duty), RoboServo 1.2.0 with
`RoboZephyrBackend::writeDuty`, the shield pins 11, 10, 9, 6, 5, 3 and the
soft-start pin 12, the 600 ms rail settle and 180 ms stagger between joints,
the App Lab layout and build profile, and the shape of the TCP relay. New
here: joint-space commands with a calibration table, a non-blocking 50 Hz
loop, the watchdog, relax by zero duty, and the calibration commands.

Build state: not built. The Arduino CLI on the authoring machine had no
`arduino:zephyr` platform and no RoboServo library, and App Lab builds on the
board, which was not connected. The control core does compile and run on the
host (`tests/test_firmware.py`, with `-Wall -Wextra -Werror`) and matches the
Python reference line for line. The glue in `sketch.ino` and
`DuckServos.cpp` is reviewed only. Open points to check at the first build:

- that `Serial` is the header UART on the UNO Q core in use,
- that a duty of 0 on a RoboServo channel stops the pulse train (used for relax),
- that `Bridge.provide_safe` accepts a `String (String)` function, as the
  library's README example suggests.

## On the bench

1. Print `fit_SR431`, `fit_SR311` and `fit_horn_drill_blank`. Check a servo
   between the rails, the tie paths (the assembly test expects one tie per
   servo to cross the output shaft) and the horn on the blank.
2. Read `docs/assembly.md`. Two things collide as drawn: the hip roll servos
   with the deck. Decide what to change.
3. Rehearse without hardware: `python scripts/virtual_robot.py` in one
   terminal, then `play.py --tcp 127.0.0.1:8766` and `calibrate.py --tcp
   127.0.0.1:8766` in another.
4. Power: see `docs/power.md`. A switch within reach.
5. Build and upload the app in App Lab. Review the three open points above.
6. With the horns off, send `E` and then the stand trajectory so each servo
   goes to its stand angle; fit the horns with the joints as near the stand
   pose as the splines allow. Send `R`.
7. Calibrate one joint at a time, robot held off the bench:
   `python scripts/calibrate.py --joint left_hip_roll --tcp <uno-q>:8766 --real`.
   Nudge with `+` and `-`; if the joint moves the wrong way, flip `direction`
   in the table. Take the zero with `z`, write it into
   `config/calibration.json`, run `scripts/generate_description.py`, rebuild.
8. Stand: `play.py trajectories/stand.csv --real`, one hand on the robot and
   one on the switch. The simulation says it stands with a 37 mm margin and
   under 8 percent of the hip torque limit.
9. Gait last: `play.py trajectories/gait.csv --real`. The simulation says it
   shuffles a few millimetres a second and cannot lift a foot.

A software stop does not cut servo power. Keep the switch.
