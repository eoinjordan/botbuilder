#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
#
# Crank walker, EV3 brick. Robot Creator code target: ev3dev-python.
# Ports: outB = left large motor, outC = right large motor, each on its
# side's rear gear axle.
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
# and button.html. Not yet run on a robot: try it first with the robot held
# off the floor.
#
# The EV3 motor encoders count from wherever the motors were at power-up, so
# the program cannot find the leg phase by itself. Set the start position by
# hand when asked: left foot at its lowest, right foot at its highest. After
# that the right side's speed is trimmed to keep it half a turn from the
# left. The walker cannot steer.

import time

from ev3dev2.button import Button
from ev3dev2.motor import LargeMotor, OUTPUT_B, OUTPUT_C, SpeedDPS

SPEED_DEG_S = 360        # crank speed: 60 rpm is about 48 mm/s. Keep below 540.
RAMP_S = 0.5
TICK_S = 0.02
PHASE_GAIN = 2.0         # deg/s of trim per degree of phase error
MAX_TRIM = 120
MAX_ERROR_DEG = 60

# The two drives are mirror images. Swap both signs if the robot walks backward.
LEFT_SIGN = 1
RIGHT_SIGN = -1

buttons = Button()
left = LargeMotor(OUTPUT_B)
right = LargeMotor(OUTPUT_C)


def home():
    left.stop(stop_action="coast")
    right.stop(stop_action="coast")
    print("Left foot down, right foot up, then press the centre button")
    while not buttons.enter:
        time.sleep(0.02)
    while buttons.any():
        time.sleep(0.02)
    left.position = 0
    right.position = 0


def walk():
    """Walk until any button is pressed, then hold the legs where they are."""
    start = time.time()
    while not buttons.any():
        elapsed = time.time() - start
        speed = SPEED_DEG_S * min(1.0, elapsed / RAMP_S)
        # Both counts start at zero in the start position, so their
        # difference is the phase error. Positive: the right side is behind.
        error = LEFT_SIGN * left.position - RIGHT_SIGN * right.position
        if abs(error) > MAX_ERROR_DEG:
            break
        trim = max(-MAX_TRIM, min(MAX_TRIM, PHASE_GAIN * error))
        left.on(SpeedDPS(LEFT_SIGN * speed))
        right.on(SpeedDPS(RIGHT_SIGN * (speed + trim)))
        time.sleep(TICK_S)
    left.stop(stop_action="hold")
    right.stop(stop_action="hold")


home()
time.sleep(0.5)
walk()
time.sleep(1.0)
left.stop(stop_action="coast")
right.stop(stop_action="coast")
