#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Target: Raspberry Pi, Python library "gpiozero", TB6612FNG driver board.
#
# NOT RUN ON HARDWARE. This file is syntax-checked only. Directions are to be
# confirmed with the wheels off the floor.
#
# Wheeled Pi build on two yellow TT gear motors through a TB6612FNG:
#   PWMA GPIO12, AIN1 GPIO5, AIN2 GPIO6      left motor
#   PWMB GPIO13, BIN1 GPIO20, BIN2 GPIO21    right motor
#   STBY GPIO16, VM from a separate 6 V pack, grounds joined
# Speed is open loop: the plain TT motor has no encoder, so equal duty does
# not give a straight line. The encoder version of the motor would close it.

import time

from gpiozero import DigitalOutputDevice, Motor

LEFT_SIGN = 1            # the motors are mirror images
RIGHT_SIGN = -1          # swap both signs if the robot runs backward
RAMP_S = 1.0             # a hard start lifts the support with the wheels at the back

standby = DigitalOutputDevice(16)
left = Motor(forward=5, backward=6, enable=12, pwm=True)
right = Motor(forward=20, backward=21, enable=13, pwm=True)


def set_wheel(motor, command):
    """Duty from -1 to 1."""
    command = max(-1.0, min(1.0, command))
    if command >= 0:
        motor.forward(command)
    else:
        motor.backward(-command)


def drive(left_command, right_command, seconds):
    steps = 10
    for i in range(1, steps + 1):
        set_wheel(left, LEFT_SIGN * left_command * i / steps)
        set_wheel(right, RIGHT_SIGN * right_command * i / steps)
        time.sleep(RAMP_S / steps)
    time.sleep(max(0.0, seconds - RAMP_S))
    left.stop()
    right.stop()


def main():
    standby.on()
    try:
        drive(1.0, 1.0, 2.0)         # straight, as far as the two motors agree
        drive(-0.5, 0.5, 1.5)        # turn on the spot
        drive(0.5, 1.0, 2.0)         # arc to the left
    finally:
        left.stop()
        right.stop()
        standby.off()


if __name__ == "__main__":
    main()
