# SPDX-License-Identifier: MIT
"""The safety layer between the browser control page and the robot's socket.

The page (site/control.js) turns a game controller into joint targets and
posts them here; this class decides whether a target is passed on as a J
line. It follows web/control.py of unoq-braccio-sketchbot: motion is off
unless the server was started with it, a session must be armed with an
operator confirmation, every move must carry the session token and a held
enable control, moves are rate limited and nothing is queued, and any link
error disarms.

A stop is the status line and then, if the board is running, the hold
command H: one line that makes the commanded angles of that instant the
target, so no controller tick can fall inside the stop. A board whose
firmware answers ERR UNKNOWN to H gets the older J line with the reported
angles instead.

A move the controller refuses because it would bring one leg into the other
(ERR CLEAR) is not an error of the link: the reply goes back to the page,
which says so, and the session stays armed.

The soft limits, the speed limit and the watchdog stay in the firmware (or
in the simulator's copy of it). Targets are also clamped here so a reply can
say what was clamped.
"""
from __future__ import annotations

import math
import secrets
import threading
import time

from . import motions, protocol

LEASE_S = 15.0
MIN_INTERVAL_S = 0.03
CHECKLIST = ("supply", "stand", "calibrated", "switch", "clear")
JUMP_WARNING = ("Jump is off for the real robot. Landing loads can strip servo gears and crack printed parts. "
                "Set \"allow_jump\": true in config/calibration.json only after the robot has stood and walked.")


class ControlBusy(ValueError):
    """Refused for now; the caller may try again. Nothing was queued."""


def parse_status(reply: str) -> dict:
    """STAT mode=RUN age_ms=40 wd=500 q=0.0,45.0,... as a dict."""
    parts = reply.split()
    if not parts or parts[0] != "STAT":
        raise RuntimeError(f"unexpected status reply: {reply!r}")
    fields = dict(part.split("=", 1) for part in parts[1:] if "=" in part)
    q = [float(v) for v in fields["q"].split(",")]
    if len(q) != 6 or not all(math.isfinite(v) for v in q):
        raise RuntimeError("status did not carry six joint angles")
    return {"mode": fields["mode"], "age_ms": int(fields["age_ms"]), "wd": int(fields["wd"]), "q": q}


class ControlApp:
    def __init__(self, link_factory, allow_motion: bool = False, cal: protocol.Calibration | None = None,
                 manifest: dict | None = None, clock=time.monotonic, target: str = "", hardware: bool = False):
        self.link_factory = link_factory
        self.allow_motion = allow_motion
        self.cal = cal or protocol.load_calibration()
        self.manifest = manifest or motions.load_manifest(cal=self.cal)
        self.jump_enabled = bool(self.manifest["robot"]["allow_jump"]) and "jump" in self.manifest["motions"]
        self.clock = clock
        self.target = target
        self.hardware = hardware
        self.link = None
        self.link_lock = threading.Lock()
        self.auth_lock = threading.Lock()
        self.token = None
        self.armed_until = 0.0
        self.last_move = -1.0e9
        self.sent = 0

    # -- link --
    def _send(self, line: str) -> str:
        """One line, one reply. Caller holds link_lock."""
        try:
            if self.link is None:
                self.link = self.link_factory()
            return self.link.send(line)
        except Exception:
            self._drop()
            raise

    def _drop(self) -> None:
        if self.link is not None:
            try:
                self.link.close()
            except OSError:
                pass
            self.link = None

    def _disarm(self) -> None:
        with self.auth_lock:
            self.token = None
            self.armed_until = 0.0

    # -- reads --
    def state(self) -> dict:
        try:
            with self.link_lock:
                robot = {"connected": True, "status": parse_status(self._send("S")), "error": None}
        except (OSError, RuntimeError, ValueError, KeyError) as error:
            self._disarm()
            robot = {"connected": False, "status": None, "error": str(error) or type(error).__name__}
        remaining = max(0.0, self.armed_until - self.clock())
        return {"microduck_control": 1, "robot": robot, "target": self.target, "hardware": self.hardware,
                "motion_enabled": self.allow_motion, "armed": bool(self.token and remaining),
                "lease_seconds": round(remaining, 1), "jump_enabled": self.jump_enabled,
                "jump_warning": JUMP_WARNING, "min_interval_ms": int(MIN_INTERVAL_S * 1000),
                "checklist": list(CHECKLIST), "run_on_hardware": False}

    # -- writes --
    def arm(self, confirmed=False, checklist=None) -> dict:
        if not self.allow_motion:
            raise ValueError("Motion is disabled on this server. Restart it with --allow-motion to drive the robot.")
        if confirmed is not True:
            raise ValueError("Operator confirmation is required")
        if not isinstance(checklist, list) or set(CHECKLIST) - set(checklist):
            raise ValueError("Tick every item of the pre-flight checklist first")
        with self.auth_lock:
            if self.token and self.clock() < self.armed_until:
                raise ValueError("Another control session is already armed")
        try:
            with self.link_lock:
                status = parse_status(self._send("S"))
                if status["mode"] == protocol.CAL:
                    raise ValueError("The board is in calibration. Leave calibration before driving.")
                if status["mode"] == protocol.RELAX:
                    reply = self._send("E")
                    if reply != "OK":
                        raise RuntimeError(f"enable refused: {reply!r}")
                    status = parse_status(self._send("S"))
        except (OSError, RuntimeError):
            self._disarm()
            raise
        with self.auth_lock:
            self.token = secrets.token_urlsafe(24)
            self.armed_until = self.clock() + LEASE_S
            return {"token": self.token, "lease_seconds": LEASE_S, "status": status}

    def _authorize(self, token, held) -> None:
        with self.auth_lock:
            if (held is not True or not self.token or not isinstance(token, str)
                    or not secrets.compare_digest(token, self.token)):
                raise ValueError("Motion requires an armed session and a held enable control")
            if self.clock() >= self.armed_until:
                self.token = None
                raise ValueError("Control session expired; arm again")

    def joints(self, body: dict) -> dict:
        self._authorize(body.get("token"), body.get("held"))
        q = body.get("q")
        if (not isinstance(q, list) or len(q) != 6
                or not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in q)
                or any(abs(v) > 1000.0 for v in q)):
            raise ValueError("Expected six finite joint angles in degrees")
        motion = body.get("motion")
        if motion is not None and motion not in ("walk", "jog") + motions.ACTIONS:
            raise ValueError("Unknown motion")
        if motion in motions.ACTIONS and motion not in self.manifest["motions"]:
            raise ValueError(f"{motion} is not available: {self.manifest['unavailable'].get(motion, 'not in the manifest')}")
        if motion == "jump" and not self.jump_enabled:
            raise ValueError(JUMP_WARNING)
        if not self.link_lock.acquire(blocking=False):
            raise ControlBusy("Robot link is busy; no move was queued")
        try:
            now = self.clock()
            if now - self.last_move < MIN_INTERVAL_S:
                raise ControlBusy("Motion rate limited; no move was queued")
            target = self.cal.clamp([float(v) for v in q])
            clamped = sum(1 for a, b in zip(q, target) if a != b)
            self._authorize(body.get("token"), body.get("held"))
            reply = self._send(protocol.format_joints(target))
            if reply == "ERR CLEAR":
                self.last_move = self.clock()
                with self.auth_lock:
                    if self.token:
                        self.armed_until = self.clock() + LEASE_S
                return {"ok": False, "refused": "that would bring the feet together", "reply": reply, "clamped": clamped, "q": target}
            if not reply.startswith("OK"):
                raise RuntimeError(f"Robot rejected the move: {reply}")
            self.last_move = self.clock()
            self.sent += 1
            with self.auth_lock:
                if self.token:
                    self.armed_until = self.clock() + LEASE_S
            return {"ok": True, "reply": reply, "clamped": clamped, "q": target}
        except (OSError, RuntimeError):
            self._disarm()
            raise
        finally:
            self.link_lock.release()

    def stop(self) -> dict:
        """Disarm, and if the board is running tell it to stay where its
        command is now. Never raises: stop has to work with a dead link."""
        self._disarm()
        held = False
        if self.allow_motion:
            try:
                with self.link_lock:
                    status = parse_status(self._send("S"))
                    if status["mode"] == protocol.RUN:
                        held = self._send("H") == "OK"
                        if not held:       # firmware without the hold command
                            held = self._send(protocol.format_joints(status["q"])).startswith("OK")
            except (OSError, RuntimeError, ValueError, KeyError):
                pass
        return {"ok": True, "armed": False, "held": held}

    def relax(self, confirmed=False) -> dict:
        """Stop all pulses. A standing robot falls: the page asks first."""
        if not self.allow_motion:
            raise ValueError("Motion is disabled on this server")
        if confirmed is not True:
            raise ValueError("Confirm that the robot is supported: relaxed servos let it fall")
        self._disarm()
        with self.link_lock:
            reply = self._send("R")
        return {"ok": reply == "OK", "reply": reply, "armed": False}

    def close(self) -> None:
        self._disarm()
        with self.link_lock:
            self._drop()
