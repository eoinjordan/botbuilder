// SPDX-License-Identifier: MIT
//
// Microduck biped on a Braccio shield: UNO Q microcontroller side.
//
// Takes the command lines of docs/sim-to-real.md from two places:
//   - the Linux side of the UNO Q, through the App Lab Bridge function
//     duck_line (python/main.py relays TCP port 8766 to it), and
//   - the header UART (Serial, D0/D1) at 115200 baud, one line per command.
// Starts relaxed: no pulse leaves the board until an E line arrives.
//
// NOT BUILT and never run on hardware. See firmware notes in the README.
#include <Arduino_RouterBridge.h>

#include "DuckControl.hpp"
#include "DuckServos.h"
#include "DuckTable.h"

static duck::Controller controller(duck::TABLE);
static char reply[128];
static char serialLine[96];
static size_t serialUsed = 0;
static uint32_t nextTick = 0;

// Bridge RPC, served in the loop thread (provide_safe), so it never runs
// in the middle of a control tick.
String duck_line(String line) {
  controller.handle(line.c_str(), millis(), reply, sizeof(reply));
  return String(reply);
}

static void readSerial() {
  while (Serial.available() > 0) {
    const char c = static_cast<char>(Serial.read());
    if (c == '\n') {
      serialLine[serialUsed] = 0;
      controller.handle(serialLine, millis(), reply, sizeof(reply));
      Serial.println(reply);
      serialUsed = 0;
    } else if (serialUsed + 1 < sizeof(serialLine)) {
      serialLine[serialUsed++] = c;
    } else {
      serialUsed = 0;  // over-long line: drop it
    }
  }
}

void setup() {
  Bridge.begin();
  Serial.begin(115200);
  duckServosBegin(duck::TABLE);
  Bridge.provide_safe("duck_line", duck_line);
  nextTick = millis();
}

void loop() {
  readSerial();
  const uint32_t now = millis();
  if (static_cast<int32_t>(now - nextTick) >= 0) {
    nextTick += duck::TICK_MS;
    if (static_cast<int32_t>(now - nextTick) > 200) nextTick = now + duck::TICK_MS;  // after a long block
    controller.tick(now);
    if (controller.mode() == duck::RELAX) {
      duckServosRelax();
    } else {
      duckServosEnable(controller);  // blocks for the soft start the first time only
      duckServosWrite(controller);
    }
  }
  delay(1);
}
