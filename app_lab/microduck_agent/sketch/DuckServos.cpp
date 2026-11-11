// SPDX-License-Identifier: MIT
//
// Servo output for the Braccio shield on the Arduino UNO Q (arduino:zephyr).
//
// The approach is the one unoq-braccio-sketchbot uses for the stock arm
// (app_lab/braccio_remote_agent/sketch/UnoQBraccioBridge.cpp): RoboServo to
// claim a PWM channel per shield pin, RoboZephyrBackend::writeDuty to set a
// 16-bit duty for an exact pulse width, the soft-start pin held low and then
// raised before any torque, and the joints energised one at a time so six
// servos never start together. What differs: pulses can be stopped again
// (duty 0) so the watchdog and the R command can relax the servos.
//
// NOT BUILT: the arduino:zephyr core and RoboServo were not available on the
// machine this was written on. Review before the first flash.
#include "DuckServos.h"

#include <Arduino.h>
#include <RoboServo.h>
#include <RoboZephyrBackend.h>

#include "BraccioPulse.hpp"

namespace {
// Same figures as the sketchbot driver: let the rail settle before any
// torque, and leave a gap between joints so the inrush does not brown out
// the board.
const int SOFT_START_MS = 600;
const int STAGGER_MS = 180;

RoboServo servos[duck::JOINTS];
const duck::Table *table = nullptr;
bool energised = false;

void writePulse(int index, int pulseUs) {
  if (!servos[index].attached()) return;
  const uint32_t duty = pulseUs > 0 ? BraccioPulse::dutyForMicroseconds(pulseUs) : 0;
  RoboZephyrBackend::writeDuty(servos[index].getChannel(), duty,
                               BraccioPulse::FREQUENCY_HZ, BraccioPulse::RESOLUTION_BITS);
}
}  // namespace

void duckServosBegin(const duck::Table &t) {
  table = &t;
  pinMode(t.soft_start_pin, OUTPUT);
  digitalWrite(t.soft_start_pin, LOW);
  energised = false;
}

void duckServosEnable(const duck::Controller &controller) {
  if (energised || table == nullptr) return;
  digitalWrite(table->soft_start_pin, LOW);
  delay(50);
  digitalWrite(table->soft_start_pin, HIGH);
  delay(SOFT_START_MS);
  for (int i = 0; i < duck::JOINTS; i++) {
    if (!servos[i].attached()) {
      servos[i].attach(table->joints[i].pin, table->min_us, table->max_us);
    }
    writePulse(i, controller.pulseUs(i));
    delay(STAGGER_MS);
  }
  energised = true;
}

void duckServosRelax() {
  for (int i = 0; i < duck::JOINTS; i++) writePulse(i, 0);
  energised = false;
}

void duckServosWrite(const duck::Controller &controller) {
  if (!energised) return;
  for (int i = 0; i < duck::JOINTS; i++) writePulse(i, controller.pulseUs(i));
}
