# SPDX-License-Identifier: MIT
"""Index of the programs in programs/ and a syntax check of each.

    python -m walkers.programs      compiles every program and writes programs/index.json

The Pybricks, ev3dev, LEGO stock Python, buildhat and gpiozero modules are
not installed here, so each file is compiled to bytecode only: the syntax is
checked and the imports are not resolved.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROGRAMS = ROOT / "programs"
CREATOR = {"name": "Mindstorms Robot Creator", "url": "https://eoinjordan.github.io/mindstorms-robot-creator/",
           "repository": "https://github.com/eoinjordan/mindstorms-robot-creator"}
# What Robot Creator does with a program for each of its code targets, read from its source.
CREATOR_STEPS = {
    "pybricks-python": "Choose a 51515 profile and the pybricks-python target, pick 'Custom (edit below)', paste the file into "
                       "the editor, connect to the hub over Bluetooth (the hub must run Pybricks firmware) and press Run. It "
                       "sends the editor's text to the hub and runs it; it does not store it on the hub.",
    "lego-stock-python": "Choose a 51515 profile and the lego-stock-python target, pick 'Custom (edit below)', paste the file "
                         "into the editor and use Download .lms. Open that project in the LEGO MINDSTORMS app and run it there. "
                         "Robot Creator does not send programs to a hub on stock firmware.",
    "pybricks-ev3": "Choose an EV3 profile and the pybricks-ev3 target, pick 'Custom (edit below)', paste the file into the "
                    "editor and use Download .py. Robot Creator does not send programs to an EV3: copy the file to the brick "
                    "with the alternative below.",
    "ev3dev-python": "Choose an EV3 profile and the ev3dev-python target, pick 'Custom (edit below)', paste the file into the "
                     "editor and use Download .py. Robot Creator does not send programs to an EV3: copy the file to the brick "
                     "with the alternative below.",
}
ALTERNATIVE = {
    "pybricks-python": "The Pybricks web editor at https://code.pybricks.com: paste, connect, run. This stores the program on the hub.",
    "lego-stock-python": "The LEGO MINDSTORMS Robot Inventor app: new Python project, paste, connect, play.",
    "pybricks-ev3": "The EV3 MicroPython (Pybricks) microSD image with the LEGO MicroPython extension for VS Code.",
    "ev3dev-python": "ev3dev on a microSD card: copy over SSH or with the ev3dev-browser extension for VS Code, then run.",
    "buildhat": "Copy to the Raspberry Pi and run with python3; needs the buildhat package.",
    "gpiozero": "Copy to the Raspberry Pi and run with python3; needs gpiozero, and pigpio for the servo program.",
}
FORM = ("standalone program; also valid as the customCode body of Robot Creator's code_generate, because it repeats its "
        "own imports and makes its own motor objects")
ENTRIES = [
    ("ev3", "crank", "ev3_motors", "pybricks-ev3", "ev3/crank-walker/walker_pybricks.py", {"B": "left large motor", "C": "right large motor"},
     "Sets the phase from a start position set by hand, then walks with the phase held by the encoders until a button is pressed."),
    ("ev3", "crank", "ev3_motors", "ev3dev-python", "ev3/crank-walker/walker_ev3dev.py", {"outB": "left large motor", "outC": "right large motor"},
     "Sets the phase from a start position set by hand, then walks with the right side's speed trimmed to hold the phase."),
    ("ev3", "wheeled", "ev3_motors", "pybricks-ev3", "ev3/wheeled/drive_pybricks.py", {"B": "left large motor", "C": "right large motor"},
     "Ramped start, straight, arc, spin and stop, then remote control from the brick buttons."),
    ("ev3", "wheeled", "ev3_motors", "ev3dev-python", "ev3/wheeled/drive_ev3dev.py", {"outB": "left large motor", "outC": "right large motor"},
     "Ramped start, straight, arc, spin and stop, then remote control from the brick buttons."),
    ("hub51515", "crank", "hub_motors", "pybricks-python", "hub51515/crank-walker/walker_pybricks.py", {"A": "left medium angular motor", "B": "right medium angular motor"},
     "Homes both sides on the absolute encoders, waits for the left button, then walks with the phase held."),
    ("hub51515", "crank", "hub_motors", "lego-stock-python", "hub51515/crank-walker/walker_lego_python.py", {"A": "left medium angular motor", "B": "right medium angular motor"},
     "Homes both sides on the absolute position, then walks for a set time with the right side's speed trimmed to hold the phase."),
    ("hub51515", "wheeled", "hub_motors", "pybricks-python", "hub51515/wheeled/drive_pybricks.py", {"A": "left medium angular motor", "B": "right medium angular motor"},
     "Waits for the left button, then ramped start, straight, arc, spin and stop, then remote control from the hub buttons."),
    ("hub51515", "wheeled", "hub_motors", "lego-stock-python", "hub51515/wheeled/drive_lego_python.py", {"A": "left medium angular motor", "B": "right medium angular motor"},
     "Ramped start, straight, arc, spin and stop. No remote control."),
    ("pi", "crank", "buildhat_51515", "buildhat", "pi/crank-walker/walker_buildhat.py", {"A": "left medium angular motor", "B": "right medium angular motor"},
     "Homes both sides on the absolute encoders, then walks with the right side's speed trimmed to hold the phase."),
    ("pi", "wheeled", "buildhat_51515", "buildhat", "pi/wheeled/drive_buildhat.py", {"A": "left medium angular motor", "B": "right medium angular motor"},
     "Ramped start, straight, spin and arc."),
    ("pi", "wheeled", "m5_360_wheels", "gpiozero", "pi/wheeled/drive_servo.py", {"GPIO12": "left servo", "GPIO13": "right servo"},
     "Straight, spin and arc on two 360-degree servos. Open loop."),
    ("pi", "wheeled", "tt_hbridge", "gpiozero", "pi/wheeled/drive_tt.py", {"GPIO12, 5, 6": "left motor through a TB6612FNG", "GPIO13, 20, 21": "right motor", "GPIO16": "standby"},
     "Ramped start, straight, spin and arc on two TT motors. Open loop."),
]
NOT_WRITTEN = [
    {"controller": "unoq", "locomotion": "wheeled", "reason": "not written: an Arduino sketch cannot be checked here"},
    {"controller": "m5core", "locomotion": "wheeled", "reason": "not written: the BaseX motor registers were not confirmed"},
]


def index() -> dict:
    programs = []
    for controller, locomotion, drive, language, file, ports, what in ENTRIES:
        source = (PROGRAMS / file).read_text(encoding="utf-8")
        compile(source, file, "exec")           # syntax only; imports are not resolved
        item = {"controller": controller, "locomotion": locomotion, "drive": drive, "language": language,
                "file": f"programs/{file}", "ports": ports, "what": what,
                "checked": "compiled to bytecode; imports not resolved"}
        if language in CREATOR_STEPS:
            item["load_with"] = {**CREATOR, "code_target": language, "steps": CREATOR_STEPS[language],
                                 "sends_to_the_brick": language == "pybricks-python"}
            item["form"] = FORM
        item["alternative"] = ALTERNATIVE[language]
        programs.append(item)
    return {"_comment": "Generated by python -m walkers.programs. One entry per program file.",
            "programs": programs, "not_written": NOT_WRITTEN}


def for_build(controller: str, locomotion: str, drive: str) -> list:
    return [p for p in index()["programs"] if (p["controller"], p["locomotion"], p["drive"]) == (controller, locomotion, drive)]


def main() -> int:
    data = index()
    (PROGRAMS / "index.json").write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(f"{len(data['programs'])} programs compiled and listed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
