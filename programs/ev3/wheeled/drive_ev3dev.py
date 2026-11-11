#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
#
# Two-wheeled EV3 build. Robot Creator code target: ev3dev-python.
# Ports: outB = left large motor, outC = right large motor, a wheel on each
# motor's axle, a skid or ball under the shelf.
#
# Load:
#   1. Mindstorms Robot Creator (https://eoinjordan.github.io/mindstorms-robot-creator/):
#      choose an EV3 profile and the ev3dev-python target, pick "Custom (edit
#      below)", paste this file into the editor and use Download .py. Robot
#      Creator does not send programs to an EV3; copy the file to the brick
#      with one of the tools below.
#   2. ev3dev on a microSD card: copy the file over SSH (scp) or with the
#      ev3dev-browser extension for VS Code, make it executable and run it.
#
# This file is a complete program. It also works as the customCode body of
# Robot Creator's code_generate, because it repeats its own imports and
# makes its own motor objects.
#
# Calls used are from
# https://ev3dev-lang.readthedocs.io/projects/python-ev3dev/en/stable/motors.html
# and button.html. Not yet run on a robot: try it first with the wheels off
# the floor.
#
# What it does: a short demonstration (straight, arc, spin, stop), then
# remote control from the brick buttons until the back button is pressed:
# up = forward, down = back, left and right = spin.

import time

from ev3dev2.button import Button
from ev3dev2.motor import LargeMotor, OUTPUT_B, OUTPUT_C, SpeedDPS

CRUISE_DEG_S = 790           # 80 percent of the motor's 165 rpm: about 0.3 m/s on 43.2 mm wheels
TURN_DEG_S = 300
RAMP_S = 1.0                 # ramped start: a hard start lifts the support with the wheels at the back

# The motors are mirror images. Swap both signs if the robot runs backward.
LEFT_SIGN = 1
RIGHT_SIGN = -1

buttons = Button()
left = LargeMotor(OUTPUT_B)
right = LargeMotor(OUTPUT_C)


def wheels(left_deg_s, right_deg_s):
    left.on(SpeedDPS(LEFT_SIGN * left_deg_s))
    right.on(SpeedDPS(RIGHT_SIGN * right_deg_s))


def halt():
    left.stop(stop_action="brake")
    right.stop(stop_action="brake")


def drive(left_deg_s, right_deg_s, seconds):
    """Ramp both wheels up to their speeds, hold, then brake."""
    start = time.time()
    while time.time() - start < seconds and not buttons.backspace:
        k = min(1.0, (time.time() - start) / RAMP_S)
        wheels(k * left_deg_s, k * right_deg_s)
        time.sleep(0.02)
    halt()


def demonstration():
    drive(CRUISE_DEG_S, CRUISE_DEG_S, 2.0)           # straight
    drive(CRUISE_DEG_S / 2, CRUISE_DEG_S, 2.0)       # arc to the left
    drive(-TURN_DEG_S, TURN_DEG_S, 1.0)              # spin
    time.sleep(0.3)


def remote():
    """Drive from the brick buttons. The back button ends the program."""
    print("Up/down: drive. Left/right: spin. Back: stop.")
    while not buttons.backspace:
        if buttons.up:
            wheels(CRUISE_DEG_S, CRUISE_DEG_S)
        elif buttons.down:
            wheels(-CRUISE_DEG_S / 2, -CRUISE_DEG_S / 2)
        elif buttons.left:
            wheels(-TURN_DEG_S, TURN_DEG_S)
        elif buttons.right:
            wheels(TURN_DEG_S, -TURN_DEG_S)
        else:
            halt()
        time.sleep(0.02)


demonstration()
remote()
left.stop(stop_action="coast")
right.stop(stop_action="coast")
