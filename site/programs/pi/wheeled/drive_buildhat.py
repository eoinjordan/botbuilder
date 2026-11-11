#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Target: Raspberry Pi with the Build HAT, Python library "buildhat"
# (https://buildhat.readthedocs.io/).
#
# NOT RUN ON HARDWARE. This file is syntax-checked only. Directions and
# speeds are to be confirmed with the wheels off the floor.
#
# Wheeled Build HAT build: 51515 medium angular motors on ports A (left) and
# B (right), a 56 mm wheel on each, a skid or ball under the shelf.
# Differential drive: one speed setting per wheel.

import time

from buildhat import Motor

LEFT_SIGN = 1            # the motors are mirror images
RIGHT_SIGN = -1          # swap both signs if the robot runs backward
CRUISE = 60              # Build HAT speed setting, -100 to 100
RAMP_S = 1.0             # a hard start lifts the support with the wheels at the back

left = Motor("A")
right = Motor("B")


def drive(left_speed, right_speed, seconds):
    """Ramp both wheels to their speeds, hold, then stop."""
    steps = 10
    for i in range(1, steps + 1):
        left.start(LEFT_SIGN * int(left_speed * i / steps))
        right.start(RIGHT_SIGN * int(right_speed * i / steps))
        time.sleep(RAMP_S / steps)
    time.sleep(max(0.0, seconds - RAMP_S))
    left.stop()
    right.stop()


def main():
    try:
        drive(CRUISE, CRUISE, 2.0)               # straight
        drive(-CRUISE // 2, CRUISE // 2, 1.5)    # turn on the spot
        drive(CRUISE // 2, CRUISE, 2.0)          # arc to the left
    finally:
        left.stop()
        right.stop()


if __name__ == "__main__":
    main()
