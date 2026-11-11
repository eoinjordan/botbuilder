# SPDX-License-Identifier: MIT
"""The simulator behind the robot's own socket.

Listens on 127.0.0.1:8766 and answers the command lines exactly as the App
Lab agent on the UNO Q does, with the MuJoCo emulation in place of the
servos. Point scripts/play.py --tcp 127.0.0.1:8766 or scripts/calibrate.py at
it to rehearse a session without hardware. The simulation runs in real time
while a client is connected.

    python scripts/virtual_robot.py [--port 8766] [--once]
"""
import argparse
import socket
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from microduck.protocol import TICK_MS  # noqa: E402
from microduck.sim import DuckSim  # noqa: E402


def serve(port: int, once: bool = False, ready=None, pose: str = "stand") -> None:
    sim = DuckSim()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("127.0.0.1", port))
        server.listen(1)
        if ready:
            ready(server.getsockname()[1])
        while True:
            client, _ = server.accept()
            sim.reset(pose)
            start = time.monotonic()
            with client:
                client.settimeout(TICK_MS / 1000.0 / 4)
                buffer = b""
                while True:
                    while sim.now_ms + TICK_MS <= (time.monotonic() - start) * 1000.0:
                        sim.tick()
                    try:
                        chunk = client.recv(256)
                    except socket.timeout:
                        continue
                    except OSError:
                        break
                    if not chunk:
                        break
                    buffer += chunk
                    while b"\n" in buffer:
                        line, buffer = buffer.split(b"\n", 1)
                        reply = sim.send(line.decode("ascii", errors="replace").strip())
                        client.sendall(reply.encode("ascii") + b"\n")
            print(f"client left: fell={sim.fell_at is not None} tilt={sim.tilt_deg():.1f} deg", flush=True)
            if once:
                return


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--once", action="store_true", help="exit when the first client leaves")
    args = parser.parse_args()
    serve(args.port, args.once, ready=lambda p: print(f"virtual robot on 127.0.0.1:{p}", flush=True))
