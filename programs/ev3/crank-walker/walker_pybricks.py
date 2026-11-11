#!/usr/bin/env pybricks-micropython
# SPDX-License-Identifier: MIT
#
# Crank walker, EV3 brick. Robot Creator code target: pybricks-ev3.
# Ports: B = left large motor, C = right large motor, each on its side's rear
# gear axle. Port A (optional head motor) is not used here.
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
# hubs.html and parameters.html. Not yet run on a robot: try it first with
# the robot held off the floor.
#
# The EV3 motor encoders count from wherever the motors were at power-up, so
# the program cannot find the leg phase by itself. Set the start position by
# hand when the screen asks: left foot at its lowest, right foot at its
# highest. Mark the cranks so this is quick. After that both motors track
# one angle reference, the right one half a turn ahead, and the encoders
# hold the phase. The walker cannot steer.

from pybricks.hubs import EV3Brick
from pybricks.ev3devices import Motor
from pybricks.parameters import Port, Direction, Color, Stop, Button
from pybricks.tools import wait, StopWatch

SPEED_DEG_S = 360        # crank speed: 60 rpm is about 48 mm/s. Keep below 540.
RAMP_MS = 500
TICK_MS = 10
MAX_LAG_DEG = 60         # stop if a side falls this far behind

# The two drives are mirror images. Swap both if the robot walks backward.
LEFT_DIRECTION = Direction.CLOCKWISE
RIGHT_DIRECTION = Direction.COUNTERCLOCKWISE

ev3 = EV3Brick()
left = Motor(Port.B, LEFT_DIRECTION)
right = Motor(Port.C, RIGHT_DIRECTION)


def reference(elapsed_ms):
    """Left crank angle in degrees after elapsed_ms, ramping up to speed."""
    if elapsed_ms < RAMP_MS:
        return SPEED_DEG_S * elapsed_ms * elapsed_ms / (2000.0 * RAMP_MS)
    return SPEED_DEG_S * (elapsed_ms - RAMP_MS / 2.0) / 1000.0


def wait_for_centre():
    while Button.CENTER not in ev3.buttons.pressed():
        wait(20)
    while ev3.buttons.pressed():
        wait(20)


def home():
    left.stop()
    right.stop()
    ev3.light.on(Color.ORANGE)
    ev3.screen.clear()
    ev3.screen.print("Left foot down,")
    ev3.screen.print("right foot up,")
    ev3.screen.print("then press centre")
    wait_for_centre()
    left.reset_angle(0)
    right.reset_angle(180)
    left.hold()
    right.hold()


def walk():
    """Walk until any button is pressed, then hold the legs where they are."""
    ev3.light.on(Color.GREEN)
    watch = StopWatch()
    while not ev3.buttons.pressed():
        target = reference(watch.time())
        left.track_target(target)
        right.track_target(target + 180)
        if target - left.angle() > MAX_LAG_DEG or target + 180 - right.angle() > MAX_LAG_DEG:
            ev3.light.on(Color.RED)
            break
        wait(TICK_MS)
    left.hold()
    right.hold()


home()
wait(500)
walk()
wait(1000)
left.stop()
right.stop()
