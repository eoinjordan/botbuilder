# Flashing the UNO Q

Status: not run on hardware. These steps have never been run on a board and
the sketch has not been built (see `docs/sim-to-real.md`, "Build state").

The site's Flash page (`site/flash.html`) writes the commands below from the
address, user and directories you type. It is the pattern of the setup page
of unoq-braccio-sketchbot: the page builds commands, you run them in your own
SSH session. The page opens no connection, has no password or key field and
sends nothing anywhere. Nothing is flashed from the browser: the sketchbot
site does not do that either, and an App Lab sketch is built on the board.

## What must already be there

- The UNO Q on your network, reachable over SSH as the `arduino` user. Wi-Fi
  and SSH are set up with Arduino App Lab; neither the page nor these steps do
  it.
- `git` and `arduino-app-cli` (the App Lab command line) on the board.
- Internet access on the board for the clone and for the first build.

## Before the first flash

1. Disconnect the servo supply. The first start of the app flashes the
   microcontroller.
2. Put the robot on a stand or lay it down, feet clear of the bench.
3. Plan no motion before calibration. The zeros and directions in
   `config/calibration.json` are starting values.
4. The board starts relaxed: no pulse leaves it before an `E` line.

## Manual steps

With the address `unoq.local`, the user `arduino` and the default
directories, the page gives exactly these, one command per block. The first
runs on your computer, the rest in the SSH session it opens.

    ssh 'arduino@unoq.local'

    git clone --depth 1 'https://github.com/eoinjordan/botbuilder.git' "$HOME"/'botbuilder'

    mkdir -p "$HOME"/'ArduinoApps'

    cp -R "$HOME"/'botbuilder/app_lab/microduck_agent' "$HOME"/'ArduinoApps/microduck_agent'

    arduino-app-cli app start "$HOME"/'ArduinoApps/microduck_agent'

    arduino-app-cli app logs "$HOME"/'ArduinoApps/microduck_agent'

    printf 'S\n' | nc -w 2 127.0.0.1 8766

    python3 "$HOME"/'botbuilder/app_lab/microduck_agent/control_server.py' --bind 0.0.0.0 --port 7101

What they do:

1. Open a session on the board. The password or key prompt is SSH's own.
2. Fetch this repository into the home directory.
3. Make the App Lab apps directory if it is missing.
4. Copy the app (the sketch and the Linux-side relay) into it.
5. `app start` compiles the sketch on the board, flashes the microcontroller
   and starts the relay. The first build takes a few minutes.
6. The log should show `Microduck agent listening on 8766`.
7. The status check, below.
8. Optional: serve the control page from the board on port 7101. Motion stays
   disabled unless `--allow-motion` is added. See `docs/control.md`.

## After the flash

The status command is the line `S` on port 8766. A freshly flashed board
answers:

    STAT mode=RELAX age_ms=1234 wd=500 q=0.0,52.0,-52.0,0.0,52.0,-52.0

`mode=RELAX` means no pulses, until an `E` line. `age_ms` is the time since
the last joint command (on a fresh board, since boot). `wd=500` is the
watchdog time in milliseconds. `q` is the commanded pose, the stand pose
after boot. No answer: read the app log and check that nothing else holds
port 8766.

## Updating

App Lab rebuilds the sketch only when the copy in the apps directory
changes, so the copy is replaced:

    git -C "$HOME"/'botbuilder' pull --ff-only origin main

    arduino-app-cli app stop "$HOME"/'ArduinoApps/microduck_agent'

    rm -rf "$HOME"/'ArduinoApps/microduck_agent'

    cp -R "$HOME"/'botbuilder/app_lab/microduck_agent' "$HOME"/'ArduinoApps/microduck_agent'

    arduino-app-cli app start "$HOME"/'ArduinoApps/microduck_agent'

Then the log and the status check as above.

## From your computer instead

The page can wrap each board command in `ssh`, so nothing is typed on the
board. The wrapped command is one single-quoted argument:

    ssh 'arduino@unoq.local' 'mkdir -p "$HOME"/'\''ArduinoApps'\'''

## How the values are made safe

- Host: letters, digits, dots and inner hyphens, or an IPv6 address.
- User: a Linux user name.
- Directories: relative to the home directory; letters, digits, dot,
  underscore, hyphen and slash; no `.` or `..` part, no part starting with a
  hyphen.
- Every value is then single-quoted. Inside single quotes the shell expands
  nothing, so quotes, semicolons, backticks and `$()` cannot start a command.
  Control characters, newlines included, are refused.

`tests/test_flash.py` runs the generated commands through a real shell with
stand-in programs and checks hostile input.

## Other controllers

| Controller | Flash steps |
|---|---|
| Arduino UNO Q | written above, not run on hardware |
| AI Thinker ESP32-CAM | not written |
| Raspberry Pi | not written |
| LEGO hubs | not written |
| M5Stack | not written |

There is no firmware for an ESP32-CAM in this repository. In the sketchbot
arrangement the camera board is flashed by hand from the Arduino IDE over its
serial port (esp32 boards package, PSRAM enabled, Huge APP partition,
Upload); neither its site nor its SSH commands flash it. So there is no
command to give, and the page gives none.

The page accepts the selection in the address, for example
`flash.html?base=unoq_braccio`. For a controller without steps it says "not written"
and shows no command.

## Reused from unoq-braccio-sketchbot

- The arrangement: a static page that builds commands for the UNO Q's Linux
  side, a copyable `ssh 'arduino@host'` line, a servo-power-disconnected
  confirmation before anything that flashes, and no secrets in the page.
- The steps: clone into the home directory, copy the App Lab app into
  `~/ArduinoApps`, `arduino-app-cli app start` to build, flash and run,
  `app logs` and an `nc` status line to check, and stop, remove, copy, start
  to flash again (its `scripts/install_unoq.sh` and
  `app_lab/braccio_remote_agent/README.md`).
- The host name check follows `web/src/setup-model.js`.

Different here: one command per block instead of one downloaded installer
script, so every step can be read before it runs; nothing is fetched with
`curl` and nothing is installed as a service by these steps.
