#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Target: Raspberry Pi with the Build HAT, Python library "buildhat"
# (https://buildhat.readthedocs.io/).
#
# Directions, the two
# zero offsets and the gain are to be confirmed with the robot held off the
# floor.
#
# Crank walker, Pi build: 51515 medium angular motors on Build HAT ports A
# (left) and B (right), one per side on the rear gear axle. The legs must
# stay half a turn apart.
#
# These motors have an absolute encoder, so the program can home itself: it
# turns each side to a stored absolute angle. The two offsets depend on how
# the axles were pushed into the motors and are found once: set the left
# foot at its lowest and the right foot at its highest by hand and run
#     python3 buildhat_walker.py --read-offsets

import sys
import time

from buildhat import Motor

LEFT_PORT = "A"
RIGHT_PORT = "B"
LEFT_SIGN = 1            # the drives are mirror images: opposite shaft directions
RIGHT_SIGN = -1          # swap both signs if the robot walks backward
LEFT_ZERO_DEG = 0        # absolute angle with the left foot at its lowest
RIGHT_ZERO_DEG = 0       # absolute angle with the right foot at its highest
SPEED = 30               # Build HAT speed setting, -100 to 100
HOME_SPEED = 15
PHASE_GAIN = 0.3         # speed units per degree of phase error
TICK_S = 0.05
MAX_ERROR_DEG = 60       # stop if the sides drift this far apart


def wrap(angle):
    """Angle in degrees wrapped to -180..180."""
    return (angle + 180.0) % 360.0 - 180.0


def read_offsets(left, right):
    print("LEFT_ZERO_DEG =", left.get_aposition())
    print("RIGHT_ZERO_DEG =", right.get_aposition())


def home(left, right):
    """Turn each side the short way to its stored pose: left foot down,
    right foot up."""
    left.run_to_position(LEFT_ZERO_DEG, HOME_SPEED, blocking=True)
    right.run_to_position(RIGHT_ZERO_DEG, HOME_SPEED, blocking=True)


def walk(left, right, seconds):
    """Run both sides at SPEED and trim the right side so that it stays in
    step with the left. Positions are relative degrees counted since the
    program started, so their difference after homing is the phase error."""
    left_start = left.get_position()
    right_start = right.get_position()
    left.start(LEFT_SIGN * SPEED)
    right.start(RIGHT_SIGN * SPEED)
    end = time.monotonic() + seconds
    try:
        while time.monotonic() < end:
            left_turn = LEFT_SIGN * (left.get_position() - left_start)
            right_turn = RIGHT_SIGN * (right.get_position() - right_start)
            error = left_turn - right_turn          # positive: the right side is behind
            if abs(error) > MAX_ERROR_DEG:
                print("phase error", error, "degrees: stopping")
                break
            trim = max(-10.0, min(10.0, PHASE_GAIN * error))
            right.start(RIGHT_SIGN * int(round(SPEED + trim)))
            time.sleep(TICK_S)
    finally:
        left.stop()
        right.stop()


def main():
    left = Motor(LEFT_PORT)
    right = Motor(RIGHT_PORT)
    if "--read-offsets" in sys.argv:
        read_offsets(left, right)
        return
    home(left, right)
    time.sleep(0.5)
    walk(left, right, 10.0)


if __name__ == "__main__":
    main()
