# SPDX-License-Identifier: MIT
#
# Crank walker, Robot Inventor 51515 hub on its stock firmware. Robot Creator
# code target: lego-stock-python.
# Ports: A = left medium angular motor, B = right medium angular motor, each
# on its side's rear gear axle.
#
# Load:
#   1. Mindstorms Robot Creator (https://eoinjordan.github.io/mindstorms-robot-creator/):
#      choose a 51515 profile and the lego-stock-python target, pick "Custom
#      (edit below)", paste this file into the editor and use Download .lms.
#      Open that project in the LEGO MINDSTORMS app and run it from there.
#      Robot Creator does not send programs to a hub on stock firmware.
#   2. The LEGO MINDSTORMS Robot Inventor app: new Python project, paste the
#      file, connect and press play.
#
# This file is a complete program. It also works as the customCode body of
# Robot Creator's code_generate, because it repeats its own imports and
# makes its own motor objects.
#
# Calls used: Motor(port), start(speed=...), stop(), get_position(),
# get_degrees_counted(), hub.speaker.beep() and wait_for_seconds(), all from
# the "mindstorms" module described in the app's Python knowledge base. The
# first four and the last two are also what Robot Creator generates.
# run_to_position() and the button and light-matrix calls are left out
# because their arguments could not be checked here. Not yet run on a robot:
# try it first with the robot held off the floor.
#
# These motors report their absolute position, 0 to 359, so the program
# homes itself: each side creeps round until it reads its zero. Find the two
# zeros once: set the left foot at its lowest and the right foot at its
# highest by hand, run with READ_ZEROS = True and copy the two numbers. The
# walker cannot steer. It walks for WALK_SECONDS and stops.

from mindstorms import MSHub, Motor
from mindstorms.control import wait_for_seconds

READ_ZEROS = False
LEFT_ZERO = 0            # get_position() with the left foot at its lowest: measure
RIGHT_ZERO = 0           # get_position() with the right foot at its highest: measure
SPEED = 30               # percent; about 55 rpm on these motors. Keep below 50.
HOME_SPEED = 10
HOME_TOLERANCE_DEG = 4
PHASE_GAIN = 0.3         # percent of trim per degree of phase error
MAX_TRIM = 10
MAX_ERROR_DEG = 60
WALK_SECONDS = 20
TICK_S = 0.02

# The two drives are mirror images. Swap both signs if the robot walks backward.
LEFT_SIGN = -1
RIGHT_SIGN = 1

hub = MSHub()
left = Motor('A')
right = Motor('B')


def wrap(angle):
    """Angle in degrees wrapped to -180..180."""
    return (angle + 180) % 360 - 180


def home(motor, sign, zero):
    """Creep forward until the absolute position reads zero."""
    motor.start(speed=sign * HOME_SPEED)
    while abs(wrap(motor.get_position() - zero)) > HOME_TOLERANCE_DEG:
        wait_for_seconds(0.01)
    motor.stop()


def walk():
    left_start = left.get_degrees_counted()
    right_start = right.get_degrees_counted()
    ticks = int(WALK_SECONDS / TICK_S)
    for tick in range(ticks):
        ramp = min(1.0, tick * TICK_S / 0.5)
        left_turn = LEFT_SIGN * (left.get_degrees_counted() - left_start)
        right_turn = RIGHT_SIGN * (right.get_degrees_counted() - right_start)
        error = left_turn - right_turn          # positive: the right side is behind
        if abs(error) > MAX_ERROR_DEG:
            break
        trim = max(-MAX_TRIM, min(MAX_TRIM, PHASE_GAIN * error))
        left.start(speed=int(LEFT_SIGN * SPEED * ramp))
        right.start(speed=int(RIGHT_SIGN * (SPEED * ramp + trim)))
        wait_for_seconds(TICK_S)
    left.stop()
    right.stop()


if READ_ZEROS:
    print("LEFT_ZERO =", left.get_position())
    print("RIGHT_ZERO =", right.get_position())
else:
    home(left, LEFT_SIGN, LEFT_ZERO)
    home(right, RIGHT_SIGN, RIGHT_ZERO)
    hub.speaker.beep()
    wait_for_seconds(1)
    walk()
