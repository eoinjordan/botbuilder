// SPDX-License-Identifier: MIT
#pragma once

#include "DuckControl.hpp"

// Servo output for the Braccio shield on the UNO Q.
void duckServosBegin(const duck::Table &table);
// Soft start the rail, then start the pulses one joint at a time.
void duckServosEnable(const duck::Controller &controller);
// Stop every pulse; the servos go limp.
void duckServosRelax();
// Write the controller's current pulse widths.
void duckServosWrite(const duck::Controller &controller);
