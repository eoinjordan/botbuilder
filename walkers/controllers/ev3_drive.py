#!/usr/bin/env pybricks-micropython
# SPDX-License-Identifier: MIT
# Target: pybricks-ev3 (the EV3 MicroPython image, https://pybricks.com/ev3-micropython/)
#
# NOT RUN ON HARDWARE. This file is syntax-checked only. Directions and
# speeds are to be confirmed with the wheels off the floor.
#
# Wheeled EV3 build: large motors on ports B (left) and C (right), a wheel on
# each motor's axle, a skid or ball under the shelf. Differential drive: one
# speed per wheel, held by the motor encoders.

from pybricks.hubs import EV3Brick
from pybricks.ev3devices import Motor
from pybricks.parameters import Port, Direction, Color, Stop, Button
from pybricks.tools import wait, StopWatch

WHEEL_DIAMETER_MM = 43.2
TRACK_MM = 144.0             # between the wheel centres
CRUISE_DEG_S = 790           # 80 percent of the motor's 165 rpm
RAMP_DEG_S2 = 800            # a hard start lifts the support with the wheels at the back

# The motors are mirror images. Swap both if the robot runs backward. For
# wheels at the front, reverse both and turn the head round.
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
    while watch.time() < milliseconds and not ev3.buttons.pressed():
        wait(10)
    left.brake()
    right.brake()


ev3.light.on(Color.GREEN)
drive(CRUISE_DEG_S, CRUISE_DEG_S, 2000)          # straight
drive(-CRUISE_DEG_S / 2, CRUISE_DEG_S / 2, 800)  # turn on the spot
drive(CRUISE_DEG_S / 2, CRUISE_DEG_S, 2000)      # arc to the left
left.stop()
right.stop()
