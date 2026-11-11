# Driving the robot from a browser

Status: the simulator target works in the page. The real target is not run
on hardware: it has only been driven against the virtual robot
(`scripts/virtual_robot.py`, the simulator behind the board's socket).

`site/control.html` drives the robot from a game controller, the keyboard or
on-screen buttons. It has two targets and one switch; the simulator is the
default.

## Input

The browser's Gamepad API covers USB and Bluetooth pads alike once the
operating system has paired them. Pairing is done in the operating system,
not in the page. A pad is reported only after a button is pressed on it, and
some browsers have no Gamepad API, so the keyboard and the on-screen buttons
do everything the pad does.

| Action | Pad, standard mapping | Keyboard | On screen |
|---|---|---|---|
| Enable (dead-man) | hold LB or RB | hold Shift | holding any motion button |
| Walk forward and back, turn | left stick | W A S D or arrows | Fwd, Back, Left, Right |
| Head pan and tilt | right stick | none | none |
| Stand, sit | A, X | 1, 2 | Stand, Sit |
| Jump | hold Y for 0.8 s | hold 3 | hold Jump |
| Stop | B | Escape, always | Stop, always |
| Expert: choose joint, jog | d-pad left and right, up and down | [ ] and - = | Joint, - and + |

Stick values inside 0.2 of centre are zero; the rest is rescaled to the full
range. A pad that appears with the enable button already held, or a stick
already over, does nothing until it has been seen at rest once.

## What exists and what does not

The page does not invent motions. It reads a manifest
(`microduck/motions.py`): named trajectories in the repository's joint
command format and the ranges of the parametric gait.

    trajectories/manifest.json
    {
      "version": 1,
      "gait": {"params": "config/gait.json", "forward": [min, max], "turn": [min, max]},
      "motions": {"stand": {"file": "trajectories/stand.csv", "label": "Stand"},
                  "sit": {...}, "jump": {...}},
      "unavailable": {"<name>": "<reason>"}
    }

- `forward` scales `step_amplitude_deg` of the gait, inside -1 to 1. A range
  that starts at 0 means no walking back.
- `turn` is the difference in step scale between the legs (left step scaled
  by forward minus turn, right by forward plus turn), inside -1 to 1. `[0, 0]`
  means no turning.
- A trajectory that is missing, malformed, outside the joint limits or over
  the speed limit is disabled, with that as the reason.

Without the file the manifest is built from what the repository has. On this
commit that is:

| Action | State |
|---|---|
| Walk forward | available: the default gait of `microduck/gait.py` |
| Stand | available: `trajectories/stand.csv` |
| Walk back | disabled: only the forward gait has been simulated |
| Turn | disabled: the default gait has no turn parameter and the robot has no hip yaw |
| Sit, jump | disabled: no trajectory yet |
| Head pan and tilt | disabled: the head is fixed, the robot has six leg joints |
| Stop | always |

Expert mode jogs one joint at 15 deg/s inside its soft limits.

The step from input to command (`nextCommand` in `site/control.js`) knows
nothing about legs: walking is a forward value and a turn value. A target
with two driven wheels could take the same command and turn it into wheel
speeds. That is not written.

## The simulator target

The page keeps a copy of the firmware's rules for the lines it sends (soft
limits, 120 deg/s speed limit, 500 ms watchdog; `PlaybackController`) and
moves the joints of the 3D view with it. This is playback of the commands,
not physics: there is no gravity or contact, the lowest point is placed on
the floor, and nothing falls. `tests/test_control.py` checks the copy against
`microduck/protocol.py` line for line, and plays the lines a held pad
produces into the MuJoCo model, where the robot stays up.

## The real target

A page on https GitHub Pages cannot reach a robot on your network. The
browser blocks http and ws requests from an https page (mixed content), and
no web page can open a raw TCP socket. The public page therefore shows the
real target as not reachable and does not pretend otherwise.

As in unoq-braccio-sketchbot, where the Studio page is served from the UNO Q
by `web/server.py` next to the arm agent, the control page is served by a
small standard-library HTTP server that talks to the agent's TCP port:
`app_lab/microduck_agent/control_server.py`. Page and API share one origin,
so nothing is mixed. Run it from a checkout:

    python scripts/virtual_robot.py
    python app_lab/microduck_agent/control_server.py --allow-motion

is the rehearsal without hardware (two terminals; open
http://127.0.0.1:7101/). On the UNO Q, next to the agent:

    python3 app_lab/microduck_agent/control_server.py --bind 0.0.0.0 --allow-motion

or on your computer, as a bridge to the board:

    python app_lab/microduck_agent/control_server.py --robot unoq.local:8766 --real --allow-motion

`microduck-control.service` in the same directory is a user unit for the
board in the form of the sketchbot's `sketchbot-studio.service`; it starts
the server with motion disabled.

The server has no login. Use a trusted network and never forward port 7101
or 8766 to the Internet.

| Request | Does |
|---|---|
| `GET /api/state` | status line of the robot, whether motion is allowed, whether a session is armed |
| `POST /api/arm` | checks the checklist, sends `E` if the board is relaxed, returns a session token |
| `POST /api/joints` | one set of six joint targets, sent as a `J` line |
| `POST /api/stop` | the stop sequence, and the session ends |
| `POST /api/relax` | `R`: no pulses; a standing robot falls |

## Safety on the real target

In the page:

- Motion only while an enable control is held. Releasing it stops.
- Stop and the Escape key always work.
- A lost controller, a hidden tab, a window that loses focus, a closed page
  or a failed request stops.
- After a stop the enable control must be released once before anything
  moves again, and the real target must be armed again.
- At most 20 commands a second, one request in flight, nothing queued.
- Arming requires every box of the pre-flight checklist: joints calibrated,
  robot on a stand or held, supply sized for stall current, a hand on the
  supply switch, legs clear.
- Jump is disabled on the real target unless `"allow_jump": true` is in
  `config/calibration.json` (it is absent, so off). Landing loads can strip
  servo gears and crack printed parts.

In the server (`microduck/webcontrol.py`):

- No motion unless it was started with `--allow-motion`.
- A robot address that is not this machine needs `--real`.
- Arming needs the operator confirmation and the whole checklist; one armed
  session at a time; the session lapses after 15 s without a move.
- Every move needs the session token and `held: true`.
- A move sooner than 30 ms after the last is refused, not queued.
- Targets must be six finite numbers; they are clamped to the soft limits.
- A motion named `jump`, or any named motion that is not in the manifest, is
  refused. The server relays joint targets and cannot tell what a stream of
  them amounts to, so this check rests on the name the page sends; the
  limits below do not.
- Requests from another origin are refused.
- Any link error ends the session.

In the firmware, unchanged: soft limits, the 120 deg/s speed limit and the
500 ms watchdog apply to every `J` line whatever sent it.

## The stop sequence, and the protocol

Nothing was added to the command set. A stop is:

    S                          read the present commanded angles
    J <those six angles>       make them the target, so motion ends here

and then silence. With no more `J` lines the watchdog puts the board in HOLD
after 500 ms. Stop does not relax the servos, because a relaxed robot falls,
and it does not cut servo power: keep the switch.

## Tests

- `tests/js/control.test.mjs` (Node): pad state to command as a pure
  function (dead zones, scaling, dead-man, stop on disconnect, jump hold,
  availability), the motion engine and the playback controller.
- `tests/test_control.py`: the manifest, the page's gait and playback
  controller against the Python reference, the safety layer with a fake link,
  and the HTTP server against `scripts/virtual_robot.py`.
- `tests/test_control_page.py`: both pages in headless Chrome over the
  DevTools protocol with a synthetic gamepad, in the simulator target and,
  served by the control server, against the virtual robot. Skipped when
  Chrome or the `websockets` package is missing.

No test opens a serial port or a connection to another machine.

## Reused from unoq-braccio-sketchbot

- Page served from the board by a standard-library HTTP server beside the
  agent's TCP relay; the public site only links and explains.
- Motion off by default on the server, an armed session with an operator
  confirmation, a held enable control on every move, a rate limit that
  refuses instead of queueing, same-origin check, disarm on any link error.
- `deadzone()` and the rest-before-use gate for a newly connected pad
  (`web/src/input.js`), hold-to-run on-screen buttons, Escape to stop,
  release on hidden tab and on pad disconnect.

Different here: the board has a watchdog, so a stop can rely on it; commands
are streamed joint targets from a gait or a trajectory rather than single
bounded steps.
