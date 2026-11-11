#!/usr/bin/env pybricks-micropython
# SPDX-License-Identifier: MIT
# Target: pybricks-ev3 (the EV3 MicroPython image, https://pybricks.com/ev3-micropython/)
#
# NOT RUN ON HARDWARE. This file is syntax-checked only. Directions, gains and
# the homing pose are to be confirmed with the robot held off the floor.
#
# Crank walker, EV3 build: large motors on ports B (left) and C (right), one
# per side on the rear gear axle. The legs must stay half a turn apart.
#
# The EV3 motor encoders are relative: they count from wherever the motor was
# when the program started. So the phase is set by hand once per run: turn
# the left cranks until the left foot is at its lowest and the right cranks
# until the right foot is at its highest, then press the centre button. From
# there both motors track one angle reference, the right one 180 degrees
# ahead, so the phase is held by the encoders.

from pybricks.hubs import EV3Brick
from pybricks.ev3devices import Motor
from pybricks.parameters import Port, Direction, Color, Stop, Button
from pybricks.tools import wait, StopWatch

SPEED_DEG_S = 360        # crank speed: 60 rpm, 48 mm/s by the kinematics
RAMP_MS = 500            # time to reach that speed
TICK_MS = 10
MAX_LAG_DEG = 60         # stop if a side falls this far behind its reference

# The two drives are mirror images, so the motors turn opposite ways seen
# from outside. Swap both directions if the robot walks backward.
LEFT_DIRECTION = Direction.CLOCKWISE
RIGHT_DIRECTION = Direction.COUNTERCLOCKWISE

ev3 = EV3Brick()
left = Motor(Port.B, LEFT_DIRECTION)
right = Motor(Port.C, RIGHT_DIRECTION)


def reference(elapsed_ms):
    """Crank angle of the left side in degrees after elapsed_ms, with a
    linear ramp up to SPEED_DEG_S."""
    if elapsed_ms < RAMP_MS:
        return SPEED_DEG_S * elapsed_ms * elapsed_ms / (2000.0 * RAMP_MS)
    return SPEED_DEG_S * (elapsed_ms - RAMP_MS / 2.0) / 1000.0


def wait_for_centre():
    while Button.CENTER not in ev3.buttons.pressed():
        wait(20)
    while ev3.buttons.pressed():
        wait(20)


def home():
    """Take the pose set by hand as left foot down (0) and right foot up
    (180). Both motors coast until the button is pressed."""
    left.stop()
    right.stop()
    ev3.light.on(Color.ORANGE)
    ev3.screen.print("Left foot down,")
    ev3.screen.print("right foot up,")
    ev3.screen.print("then press centre")
    wait_for_centre()
    left.reset_angle(0)
    right.reset_angle(180)
    left.hold()
    right.hold()


def walk():
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
    # Hold where they are: stopping at any phase is stable in simulation.
    left.hold()
    right.hold()


home()
wait(500)
walk()
wait(1000)
left.stop()
right.stop()
