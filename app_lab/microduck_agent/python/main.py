# SPDX-License-Identifier: MIT
"""Microduck agent, Linux side of the UNO Q, for Arduino App Lab.

Opens a TCP server on :8766 and relays each newline-terminated command line
to the microcontroller sketch's ``duck_line`` Bridge function, returning its
one-line reply. The command set is in docs/sim-to-real.md; this file adds
nothing to it and holds no state, so the microcontroller's limits and
watchdog apply whatever the client does.

The server loop follows braccio_remote_agent/python/main.py in
unoq-braccio-sketchbot: one client at a time, the connection kept open for a
stream of lines.

Not run on hardware.
"""

from arduino.app_utils import App, Bridge
import socket
import time


HOST = "0.0.0.0"
PORT = 8766
MAX_LINE = 96


def handle_command(line):
    line = line.strip()
    if not line or len(line) > MAX_LINE or not line.isascii():
        return "ERR ARGS"
    result = Bridge.call("duck_line", line)
    return str(result) if result is not None else "ERR BRIDGE"


def loop():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((HOST, PORT))
        server.listen(1)
        server.settimeout(1.0)
        print(f"Microduck agent listening on {PORT}")

        while True:
            try:
                client, address = server.accept()
            except socket.timeout:
                time.sleep(0.05)
                continue

            with client:
                client.settimeout(30.0)
                buffer = ""
                while True:
                    try:
                        chunk = client.recv(256)
                    except socket.timeout:
                        break
                    if not chunk:
                        break
                    buffer += chunk.decode("ascii", errors="replace")
                    if len(buffer) > 4096:
                        break
                    while "\n" in buffer:
                        line, buffer = buffer.split("\n", 1)
                        if not line.strip():
                            continue
                        response = handle_command(line)
                        try:
                            client.sendall((response + "\n").encode("ascii"))
                        except OSError:
                            break
            # When the client goes away nothing more is sent to the sketch, so
            # its watchdog takes over.


App.run(user_loop=loop)
