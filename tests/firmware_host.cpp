// SPDX-License-Identifier: MIT
//
// Host harness for the firmware's control core. Reads a script on stdin:
//
//   L <now_ms> <command line>   -> prints "R <reply>"
//   T <now_ms>                  -> one control tick, prints "P <six pulse widths>"
//
// tests/test_firmware.py runs the same script through the Python reference
// controller and compares the output line by line.
#include <cstdio>
#include <cstdlib>
#include <cstring>

#include "DuckControl.hpp"
#include "DuckTable.h"

int main() {
  duck::Controller controller(duck::TABLE);
  char line[256];
  char reply[128];
  while (std::fgets(line, sizeof(line), stdin)) {
    char *end = nullptr;
    const unsigned long now = std::strtoul(line + 2, &end, 10);
    if (line[0] == 'L') {
      controller.handle(end, static_cast<uint32_t>(now), reply, sizeof(reply));
      std::printf("R %s\n", reply);
    } else if (line[0] == 'T') {
      controller.tick(static_cast<uint32_t>(now));
      std::printf("P");
      for (int i = 0; i < duck::JOINTS; i++) std::printf(" %d", controller.pulseUs(i));
      std::printf("\n");
    }
  }
  return 0;
}
