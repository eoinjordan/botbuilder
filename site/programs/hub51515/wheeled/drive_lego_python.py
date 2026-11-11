# SPDX-License-Identifier: MIT
#
# Two-wheeled Robot Inventor 51515 build on the hub's stock firmware. Robot
# Creator code target: lego-stock-python.
# Ports: A = left medium angular motor, B = right medium angular motor, a
# 56 mm wheel on each, a skid or ball under the shelf.
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
# Calls used: Motor(port), start(speed=...), stop(), hub.speaker.beep() and
# wait_for_seconds(), from the "mindstorms" module described in the app's
# Python knowledge base; they are the calls Robot Creator itself generates.
# There is no remote-control loop here: the button and light-matrix calls
# are left out because their arguments could not be checked. Not yet run on
# a robot: try it first with the wheels off the floor.
#
# What it does: beeps, then straight, arc, spin and stop, each with a ramped
# start.

from mindstorms import MSHub, Motor
from mindstorms.control import wait_for_seconds

CRUISE = 60              # percent
TURN = 25
RAMP_S = 1.0             # ramped start: a hard start lifts the support with the wheels at the back
RAMP_STEPS = 10

# The motors are mirror images. Swap both signs if the robot runs backward.
LEFT_SIGN = -1
RIGHT_SIGN = 1

hub = MSHub()
left = Motor('A')
right = Motor('B')


def drive(left_speed, right_speed, seconds):
    """Ramp both wheels up to their speeds, hold, then stop."""
    for step in range(1, RAMP_STEPS + 1):
        left.start(speed=int(LEFT_SIGN * left_speed * step / RAMP_STEPS))
        right.start(speed=int(RIGHT_SIGN * right_speed * step / RAMP_STEPS))
        wait_for_seconds(RAMP_S / RAMP_STEPS)
    wait_for_seconds(max(0, seconds - RAMP_S))
    left.stop()
    right.stop()
    wait_for_seconds(0.3)


hub.speaker.beep()
wait_for_seconds(1)
drive(CRUISE, CRUISE, 2.5)           # straight
drive(CRUISE / 2, CRUISE, 2.5)       # arc to the left
drive(-TURN, TURN, 1.5)              # spin
hub.speaker.beep()
