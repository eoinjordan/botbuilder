#!/usr/bin/env pybricks-micropython
# SPDX-License-Identifier: MIT
#
# Two-wheeled EV3 build. Robot Creator code target: pybricks-ev3.
# Ports: B = left large motor, C = right large motor, a wheel on each motor's
# axle, a skid or ball under the shelf.
#
# Load:
#   1. Mindstorms Robot Creator (https://eoinjordan.github.io/mindstorms-robot-creator/):
#      choose an EV3 profile and the pybricks-ev3 target, pick "Custom (edit
#      below)", paste this file into the editor and use Download .py. Robot
#      Creator does not send programs to an EV3; copy the file to the brick
#      with one of the tools below.
#   2. EV3 MicroPython (Pybricks) microSD image with the LEGO MicroPython
#      extension for VS Code: open this file in a project and press F5.
#
# This file is a complete program. It also works as the customCode body of
# Robot Creator's code_generate, because it repeats its own imports and
# makes its own motor objects.
#
# Calls used are from https://pybricks.com/ev3-micropython/ev3devices.html,
# hubs.html, motors.html and parameters.html. Not yet run on a robot: try it
# first with the wheels off the floor.
#
# What it does: a short demonstration (straight, arc, spin, stop), then
# remote control from the brick buttons until the centre button is pressed:
# up = forward, down = back, left and right = spin.

from pybricks.hubs import EV3Brick
from pybricks.ev3devices import Motor
from pybricks.parameters import Port, Direction, Color, Stop, Button
from pybricks.tools import wait, StopWatch

CRUISE_DEG_S = 790           # 80 percent of the motor's 165 rpm: about 0.3 m/s on 43.2 mm wheels
RAMP_DEG_S2 = 800            # ramped start: a hard start lifts the support with the wheels at the back
TURN_DEG_S = 300

# The motors are mirror images. Swap both if the robot runs backward. For
# wheels at the front, swap both and pin the head on the other way round.
left = Motor(Port.B, Direction.CLOCKWISE)
right = Motor(Port.C, Direction.COUNTERCLOCKWISE)
ev3 = EV3Brick()

for motor in (left, right):
    motor.control.limits(CRUISE_DEG_S, RAMP_DEG_S2, 100)


def drive(left_deg_s, right_deg_s, milliseconds):
    """Run each wheel at its own speed for a time, then brake."""
    left.run(left_deg_s)
    right.run(right_deg_s)
    watch = StopWatch()
    while watch.time() < milliseconds and Button.CENTER not in ev3.buttons.pressed():
        wait(10)
    left.brake()
    right.brake()


def demonstration():
    drive(CRUISE_DEG_S, CRUISE_DEG_S, 2000)          # straight
    drive(CRUISE_DEG_S / 2, CRUISE_DEG_S, 2000)      # arc to the left
    drive(-TURN_DEG_S, TURN_DEG_S, 1000)             # spin
    wait(300)


def remote():
    """Drive from the brick buttons. Centre ends the program."""
    ev3.screen.clear()
    ev3.screen.print("Up/down: drive")
    ev3.screen.print("Left/right: spin")
    ev3.screen.print("Centre: stop")
    while True:
        pressed = ev3.buttons.pressed()
        if Button.CENTER in pressed:
            break
        if Button.UP in pressed:
            left.run(CRUISE_DEG_S)
            right.run(CRUISE_DEG_S)
        elif Button.DOWN in pressed:
            left.run(-CRUISE_DEG_S / 2)
            right.run(-CRUISE_DEG_S / 2)
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


ev3.light.on(Color.GREEN)
demonstration()
while ev3.buttons.pressed():
    wait(20)
remote()
left.stop()
right.stop()
