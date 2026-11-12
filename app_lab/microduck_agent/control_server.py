# SPDX-License-Identifier: MIT
"""Serve the browser control page next to the robot (standard library only).

A page on https GitHub Pages cannot reach a robot on the local network: the
browser blocks http and ws requests from an https page, and no page can open
a raw TCP socket. So, as web/server.py does in unoq-braccio-sketchbot, the
page is served from here, same origin as its API, by a small HTTP server
that talks to the agent's TCP port. Run it from a checkout of this
repository, on the UNO Q's Linux side or on a computer on the same network:

    python3 app_lab/microduck_agent/control_server.py                 the virtual robot or the agent on this machine
    python3 app_lab/microduck_agent/control_server.py --bind 0.0.0.0  reachable from the local network
    python3 app_lab/microduck_agent/control_server.py --robot unoq.local:8766 --real

Without --allow-motion the page shows the robot's status and sends nothing
that moves it. A robot address that is not this machine needs --real, as in
scripts/play.py. There is no login: use a trusted network and never forward
this port to the Internet.

Not run on hardware.
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from microduck import motions, player, webcontrol  # noqa: E402

SITE = ROOT / "site"
PAGES = {"/": "control.html", "/control.html": "control.html", "/control.js": "control.js",
         "/flash.html": "flash.html", "/flash.js": "flash.js", "/style.css": "style.css", "/tour.js": "tour.js"}
TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
         ".json": "application/json", ".csv": "text/csv; charset=utf-8", ".woff2": "font/woff2", ".txt": "text/plain; charset=utf-8"}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def _send(self, code: int, body: bytes, ctype: str):
        try:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True

    def _json(self, code: int, payload):
        self._send(code, json.dumps(payload, allow_nan=False).encode("utf-8"), "application/json")

    def _file(self, path: Path):
        if not path.is_file():
            return self._send(404, b"Not found", "text/plain")
        ctype = TYPES.get(path.suffix) or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self._send(200, path.read_bytes(), ctype)

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        path = urlsplit(self.path).path
        app = self.server.control
        if path in PAGES:
            return self._file(SITE / PAGES[path])
        if path == "/api/state":
            return self._json(200, app.state())
        if path == "/data/motions.json":
            return self._json(200, app.manifest)
        if path == "/data/joints.json":
            return self._file(ROOT / "robot" / "joints.json")
        if path == "/data/model.json":
            with open(ROOT / "robot" / "model.json", encoding="utf-8") as handle:
                model = json.load(handle)
            model["meshes_published"] = False
            return self._json(200, model)
        if path.startswith("/data/trajectories/"):
            for entry in app.manifest["motions"].values():
                if path == "/data/" + entry["file"]:
                    return self._file(ROOT / entry["source"])
            return self._send(404, b"Not found", "text/plain")
        if path.startswith("/assets/"):
            target = (SITE / path[1:]).resolve()
            if target.is_relative_to((SITE / "assets").resolve()):
                return self._file(target)
        self._send(404, b"Not found", "text/plain")

    def do_POST(self):
        path = urlsplit(self.path).path
        app = self.server.control
        origin = self.headers.get("Origin")
        if (origin and urlsplit(origin).netloc != self.headers.get("Host")) or self.headers.get("Sec-Fetch-Site") == "cross-site":
            return self._json(403, {"error": "Cross-origin control is not allowed"})
        try:
            size = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            size = -1
        if not 0 <= size <= 4096:
            self.close_connection = True
            return self._json(413, {"error": "Invalid request size"})
        raw = self.rfile.read(size) if size else b""
        if path == "/api/stop":
            # Any body, any content type: a page that is closing sends a beacon.
            return self._json(200, app.stop())
        if self.headers.get_content_type() != "application/json":
            return self._json(415, {"error": "Expected application/json"})
        try:
            body = json.loads(raw)
            if not isinstance(body, dict):
                raise ValueError("Expected a JSON object")
            actions = {
                "/api/arm": lambda: app.arm(body.get("confirmed"), body.get("checklist")),
                "/api/joints": lambda: app.joints(body),
                "/api/relax": lambda: app.relax(body.get("confirmed")),
            }
            if path not in actions:
                return self._json(404, {"error": "Unknown action"})
            return self._json(200, actions[path]())
        except webcontrol.ControlBusy as error:
            return self._json(409, {"error": str(error), "retryable": True})
        except (ValueError, TypeError, KeyError) as error:
            return self._json(422, {"error": str(error)})
        except (OSError, RuntimeError) as error:
            app.stop()
            return self._json(503, {"error": str(error) or type(error).__name__})


def make_server(bind: str = "127.0.0.1", port: int = 7101, robot_host: str = "127.0.0.1", robot_port: int = 8766,
                real: bool = False, allow_motion: bool = False) -> ThreadingHTTPServer:
    if robot_host not in player.LOCAL_HOSTS and not real:
        raise player.HardwareNotAllowed(f"{robot_host} is not this machine; pass --real to reach hardware")
    server = ThreadingHTTPServer((bind, port), Handler)
    server.daemon_threads = True
    server.control = webcontrol.ControlApp(
        lambda: player.TcpLink(robot_host, robot_port, real=real, timeout=1.5), allow_motion=allow_motion,
        manifest=motions.load_manifest(), target=f"{robot_host}:{robot_port}", hardware=robot_host not in player.LOCAL_HOSTS)
    return server


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=7101)
    parser.add_argument("--bind", default="127.0.0.1", help="0.0.0.0 to serve the local network")
    parser.add_argument("--robot", default="127.0.0.1:8766", metavar="HOST:PORT", help="the agent's or the virtual robot's socket")
    parser.add_argument("--real", action="store_true", help="allow a robot address that is not this machine")
    parser.add_argument("--allow-motion", action="store_true", help="let an armed page move the robot")
    args = parser.parse_args()
    host, _, port = args.robot.rpartition(":")
    try:
        server = make_server(args.bind, args.port, host or "127.0.0.1", int(port), args.real, args.allow_motion)
    except player.HardwareNotAllowed as error:
        print(f"refused: {error}", file=sys.stderr)
        return 2
    print(f"Microduck control page on http://{args.bind}:{server.server_port}/ for the robot at {args.robot}; "
          f"motion {'available, sessions start disarmed' if args.allow_motion else 'disabled'}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.control.close()
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
