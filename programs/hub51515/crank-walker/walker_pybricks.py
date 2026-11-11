# SPDX-License-Identifier: MIT
#
# Crank walker, Robot Inventor 51515 hub. Robot Creator code target:
# pybricks-python. The hub must run Pybricks firmware.
# Ports: A = left medium angular motor, B = right medium angular motor, each
# on its side's rear gear axle.
#
# Load:
#   1. Mindstorms Robot Creator (https://eoinjordan.github.io/mindstorms-robot-creator/):
#      choose a 51515 profile and the pybricks-python target, pick "Custom
#      (edit below)", paste this file into the editor, connect to the hub
#      over Bluetooth and press Run. Robot Creator sends the editor's text to
#      the hub and runs it; it does not store it on the hub.
#   2. The Pybricks web editor, https://code.pybricks.com: paste the file,
#      connect and press run. This stores the program on the hub.
#
# This file is a complete program. It also works as the customCode body of
# Robot Creator's code_generate, because it repeats its own imports and
# makes its own motor objects.
#
# Calls used are from https://docs.pybricks.com/en/stable/pupdevices/motor.html
# and https://docs.pybricks.com/en/stable/hubs/primehub.html. Not yet run on
# a robot: try it first with the robot held off the floor.
#
# These motors have an absolute encoder, so the program homes itself. Find
# the two zero angles once: set the left foot at its lowest and the right
# foot at its highest by hand, run the program with READ_ZEROS = True, and
# copy the two numbers it prints into LEFT_ZERO and RIGHT_ZERO. The walker
# cannot steer. The centre button stops the program.

from pybricks.hubs import InventorHub
from pybricks.pupdevices import Motor
from pybricks.parameters import Port, Direction, Button, Color, Stop
from pybricks.tools import wait, StopWatch

READ_ZEROS = False
LEFT_ZERO = 0            # absolute angle with the left foot at its lowest: measure
RIGHT_ZERO = 0           # absolute angle with the right foot at its highest: measure
SPEED_DEG_S = 360        # crank speed: 60 rpm is about 48 mm/s. Keep below 540.
HOME_DEG_S = 120
RAMP_MS = 500
TICK_MS = 10
MAX_LAG_DEG = 60         # stop if a side falls this far behind

hub = InventorHub()
# The two drives are mirror images. Swap both if the robot walks backward.
left = Motor(Port.A, Direction.COUNTERCLOCKWISE)
right = Motor(Port.B, Direction.CLOCKWISE)


def reference(elapsed_ms):
    """Left crank angle in degrees after elapsed_ms, ramping up to speed."""
    if elapsed_ms < RAMP_MS:
        return SPEED_DEG_S * elapsed_ms * elapsed_ms / (2000.0 * RAMP_MS)
    return SPEED_DEG_S * (elapsed_ms - RAMP_MS / 2.0) / 1000.0


def home():
    """At start-up angle() is the absolute angle, -180 to 179. Turn each side
    to its zero, then count from there: left 0, right 180."""
    left.run_target(HOME_DEG_S, LEFT_ZERO, then=Stop.HOLD, wait=True)
    right.run_target(HOME_DEG_S, RIGHT_ZERO, then=Stop.HOLD, wait=True)
    left.reset_angle(0)
    right.reset_angle(180)


def walk(milliseconds):
    watch = StopWatch()
    while watch.time() < milliseconds:
        target = reference(watch.time())
        left.track_target(target)
        right.track_target(target + 180)
        if target - left.angle() > MAX_LAG_DEG or target + 180 - right.angle() > MAX_LAG_DEG:
            hub.light.on(Color.RED)
            break
        wait(TICK_MS)
    left.hold()
    right.hold()


if READ_ZEROS:
    print("LEFT_ZERO =", left.angle())
    print("RIGHT_ZERO =", right.angle())
else:
    hub.light.on(Color.ORANGE)
    home()
    hub.display.char("L")            # press the left button to start
    while Button.LEFT not in hub.buttons.pressed():
        wait(20)
    hub.light.on(Color.GREEN)
    walk(20000)
    wait(1000)
    left.stop()
    right.stop()
