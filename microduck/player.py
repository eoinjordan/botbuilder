# SPDX-License-Identifier: MIT
"""Play a recorded trajectory on the simulator or, only when asked for
explicitly, on the robot.

Every target speaks the same command lines (microduck/protocol.py):

    SimLink      the MuJoCo emulation, in process, stepped in simulated time
    TcpLink      the App Lab agent on the UNO Q (python/main.py, port 8766),
                 or scripts/virtual_robot.py, which is the simulator behind
                 the same socket
    SerialLink   the sketch's header UART through a USB serial adapter

TcpLink to a non-local host and SerialLink are hardware. They are refused
unless the caller passes real=True (the --real flag of scripts/play.py).
"""
from __future__ import annotations

import socket
import time

from . import gait, protocol

LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")


class HardwareNotAllowed(RuntimeError):
    pass


class SimLink:
    """The simulator as a link. Time is simulated: wait() steps the physics."""

    hardware = False

    def __init__(self, sim=None):
        if sim is None:
            from .sim import DuckSim
            sim = DuckSim()
        self.sim = sim

    def send(self, line: str) -> str:
        return self.sim.send(line.strip())

    def wait_until(self, t_ms: int) -> None:
        while self.sim.now_ms < t_ms:
            self.sim.tick()

    def now_ms(self) -> int:
        return self.sim.now_ms

    def close(self) -> None:
        pass


class _RealTime:
    def __init__(self):
        self._start = time.monotonic()

    def now_ms(self) -> int:
        return int((time.monotonic() - self._start) * 1000)

    def wait_until(self, t_ms: int) -> None:
        delay = t_ms / 1000.0 - (time.monotonic() - self._start)
        if delay > 0:
            time.sleep(delay)


class TcpLink(_RealTime):
    def __init__(self, host: str, port: int = 8766, real: bool = False, timeout: float = 3.0):
        self.hardware = host not in LOCAL_HOSTS
        if self.hardware and not real:
            raise HardwareNotAllowed(f"{host} is not this machine; pass --real to drive hardware")
        super().__init__()
        self._sock = socket.create_connection((host, port), timeout)
        self._sock.settimeout(timeout)
        self._buffer = b""

    def send(self, line: str) -> str:
        self._sock.sendall(line.strip().encode("ascii") + b"\n")
        while b"\n" not in self._buffer:
            chunk = self._sock.recv(256)
            if not chunk:
                raise ConnectionError("link closed")
            self._buffer += chunk
        reply, self._buffer = self._buffer.split(b"\n", 1)
        return reply.decode("ascii", errors="replace").strip()

    def close(self) -> None:
        self._sock.close()


class SerialLink(_RealTime):
    hardware = True

    def __init__(self, port: str, real: bool = False, baud: int = 115200, timeout: float = 1.0):
        if not real:
            raise HardwareNotAllowed("a serial port is hardware; pass --real to open it")
        super().__init__()
        import serial  # pyserial, only needed for this link
        self._port = serial.Serial(port, baud, timeout=timeout)

    def send(self, line: str) -> str:
        self._port.write(line.strip().encode("ascii") + b"\n")
        reply = self._port.readline()
        if not reply:
            raise TimeoutError("no reply from the board")
        return reply.decode("ascii", errors="replace").strip()

    def close(self) -> None:
        self._port.close()


def play(link, trajectory: list, cal: protocol.Calibration, enable: bool = True, log=None) -> dict:
    """Send a trajectory row by row at its time stamps.

    Refuses a trajectory that leaves the joint limits or the speed limit, so a
    bad file is caught before the first line is sent. Stops on the first
    reply that is not OK and leaves the rest to the firmware's watchdog.
    """
    problems = gait.check_limits(trajectory, cal)
    if problems:
        t, joint, what = problems[0]
        raise ValueError(f"trajectory not playable: {len(problems)} problems, first at {t} ms on {joint}: {what}")
    status = link.send("S")
    if not status.startswith("STAT"):
        raise RuntimeError(f"unexpected status reply: {status!r}")
    if enable:
        reply = link.send("E")
        if reply != "OK":
            raise RuntimeError(f"enable refused: {reply!r}")
    start = link.now_ms()
    sent = clamped = 0
    for t, q in trajectory:
        link.wait_until(start + t)
        reply = link.send(protocol.format_joints(q))
        if log:
            log(t, q, reply)
        if not reply.startswith("OK"):
            return {"sent": sent, "clamped": clamped, "stopped_at_ms": t, "reply": reply, "final_status": link.send("S")}
        sent += 1
        clamped += reply.startswith("OK CLAMP")
    return {"sent": sent, "clamped": clamped, "stopped_at_ms": None, "reply": "OK", "final_status": link.send("S")}


def calibrate_step(link, index: int, action: str, step: float = 1.0) -> str:
    """One calibration action on joint index: 'begin', '+', '-', 'zero', 'end'."""
    if action == "begin":
        return link.send(f"C {index}")
    if action in ("+", "-"):
        return link.send("N " + protocol.fmt1(step if action == "+" else -step))
    if action == "zero":
        return link.send("Z")
    if action == "end":
        return link.send("X")
    raise ValueError(action)
