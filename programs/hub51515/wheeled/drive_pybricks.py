# SPDX-License-Identifier: MIT
#
# Two-wheeled Robot Inventor 51515 build. Robot Creator code target:
# pybricks-python. The hub must run Pybricks firmware.
# Ports: A = left medium angular motor, B = right medium angular motor, a
# 56 mm wheel on each, a skid or ball under the shelf.
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
# a robot: try it first with the wheels off the floor.
#
# What it does: shows an arrow and waits for the left button, runs a short
# demonstration (straight, arc, spin, stop), then remote control from the
# hub buttons: left button = spin left, right button = spin right, both =
# forward. The centre button stops the program.

from pybricks.hubs import InventorHub
from pybricks.pupdevices import Motor
from pybricks.parameters import Port, Direction, Button, Color, Stop
from pybricks.tools import wait, StopWatch

CRUISE_DEG_S = 890           # 80 percent of the motor's 185 rpm: about 0.43 m/s on 56 mm wheels
RAMP_DEG_S2 = 900            # ramped start: a hard start lifts the support with the wheels at the back
TURN_DEG_S = 300

hub = InventorHub()
# The motors are mirror images. Swap both if the robot runs backward. For
# wheels at the front, swap both and pin the head on the other way round.
left = Motor(Port.A, Direction.COUNTERCLOCKWISE)
right = Motor(Port.B, Direction.CLOCKWISE)

for motor in (left, right):
    motor.control.limits(CRUISE_DEG_S, RAMP_DEG_S2)


def drive(left_deg_s, right_deg_s, milliseconds):
    """Run each wheel at its own speed for a time, then brake."""
    left.run(left_deg_s)
    right.run(right_deg_s)
    watch = StopWatch()
    while watch.time() < milliseconds:
        wait(10)
    left.brake()
    right.brake()


def demonstration():
    drive(CRUISE_DEG_S, CRUISE_DEG_S, 2000)          # straight
    drive(CRUISE_DEG_S / 2, CRUISE_DEG_S, 2000)      # arc to the left
    drive(-TURN_DEG_S, TURN_DEG_S, 1000)             # spin
    wait(300)


def remote():
    """Drive from the hub's left and right buttons until the program is stopped."""
    hub.display.char("R")
    while True:
        pressed = hub.buttons.pressed()
        if Button.LEFT in pressed and Button.RIGHT in pressed:
            left.run(CRUISE_DEG_S)
            right.run(CRUISE_DEG_S)
        elif Button.LEFT in pressed:
            left.run(-TURN_DEG_S)
            right.run(TURN_DEG_S)
        elif Button.RIGHT in pressed:
            left.run(TURN_DEG_S)
            right.run(-TURN_DEG_S)
        else:
            left.brake()
            right.brake()
        wait(20)


hub.light.on(Color.ORANGE)
hub.display.char("L")                # press the left button to start
while Button.LEFT not in hub.buttons.pressed():
    wait(20)
while hub.buttons.pressed():
    wait(20)
hub.light.on(Color.GREEN)
demonstration()
remote()
