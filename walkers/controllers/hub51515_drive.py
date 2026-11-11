# SPDX-License-Identifier: MIT
# Target: pybricks-python on the Robot Inventor 51515 hub (https://code.pybricks.com)
#
# NOT RUN ON HARDWARE. This file is syntax-checked only. Directions and
# speeds are to be confirmed with the wheels off the floor.
#
# Wheeled 51515 build: medium angular motors on ports A (left) and B (right),
# a 56 mm wheel on each, a skid or ball under the shelf. Differential drive:
# one speed per wheel, held by the motor encoders.

from pybricks.hubs import InventorHub
from pybricks.pupdevices import Motor
from pybricks.parameters import Port, Direction, Button, Color, Stop
from pybricks.tools import wait, StopWatch

CRUISE_DEG_S = 890           # 80 percent of the motor's 185 rpm
RAMP_DEG_S2 = 900

hub = InventorHub()
# The motors are mirror images. Swap both if the robot runs backward.
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


hub.light.on(Color.GREEN)
drive(CRUISE_DEG_S, CRUISE_DEG_S, 2000)          # straight
drive(-CRUISE_DEG_S / 2, CRUISE_DEG_S / 2, 800)  # turn on the spot
drive(CRUISE_DEG_S / 2, CRUISE_DEG_S, 2000)      # arc to the left
left.stop()
right.stop()
