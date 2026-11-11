#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Target: Raspberry Pi, Python library "gpiozero" with the pigpio pin factory
# (run the pigpio daemon; it times the pulses better than software PWM).
#
# The stop pulse and
# the directions are to be found with the wheels off the floor.
#
# Wheeled Pi build on two 360-degree servos: left on GPIO12, right on GPIO13
# (the two hardware PWM channels). Servo power comes from a separate 4.8 to
# 6 V pack with its ground joined to the Pi's. Speed is open loop: there is
# no feedback, so equal commands do not give a straight line. Trim LEFT_TRIM
# and RIGHT_TRIM until each wheel stands still at zero.

import time

from gpiozero import Servo
from gpiozero.pins.pigpio import PiGPIOFactory

LEFT_PIN = 12
RIGHT_PIN = 13
LEFT_SIGN = 1            # the servos are mirror images
RIGHT_SIGN = -1          # swap both signs if the robot runs backward
LEFT_TRIM = 0.0          # added to the command so that zero means stopped
RIGHT_TRIM = 0.0
MIN_PULSE_S = 0.0005     # the servo kit's range: 0.5 to 2.5 ms
MAX_PULSE_S = 0.0025

factory = PiGPIOFactory()
left = Servo(LEFT_PIN, min_pulse_width=MIN_PULSE_S, max_pulse_width=MAX_PULSE_S, pin_factory=factory)
right = Servo(RIGHT_PIN, min_pulse_width=MIN_PULSE_S, max_pulse_width=MAX_PULSE_S, pin_factory=factory)


def clamp(value):
    return max(-1.0, min(1.0, value))


def drive(left_command, right_command, seconds):
    """Commands from -1 to 1. The servo's own speed curve is not linear."""
    left.value = clamp(LEFT_SIGN * left_command + LEFT_TRIM)
    right.value = clamp(RIGHT_SIGN * right_command + RIGHT_TRIM)
    time.sleep(seconds)
    left.value = clamp(LEFT_TRIM)
    right.value = clamp(RIGHT_TRIM)


def main():
    try:
        drive(1.0, 1.0, 2.0)         # straight, as far as the two servos agree
        drive(-0.5, 0.5, 1.0)        # turn on the spot
        drive(0.5, 1.0, 2.0)         # arc to the left
    finally:
        left.detach()
        right.detach()


if __name__ == "__main__":
    main()
