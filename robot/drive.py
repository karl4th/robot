"""Local two-side serial drive controller."""

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import threading
import time

import serial
from serial.tools import list_ports


BAUD = 115200
COMMAND_PERIOD = 0.05
COMMAND_TIMEOUT = 0.3
STATUS_TIMEOUT = 7.0
STEERING_DEADZONE = 0.15
THROTTLE_DEADZONE = 0.08


class ConnectionCheckError(ValueError):
    def __init__(self, message, checks):
        super().__init__(message)
        self.checks = checks


def mix(x, y):
    """Map a unit joystick vector to left and right drive fractions."""
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and -1 <= v <= 1 for v in (x, y)):
        raise ValueError("Joystick coordinates must be between -1 and 1")
    x = _deadzone(x, STEERING_DEADZONE)
    y = _deadzone(y, THROTTLE_DEADZONE)
    scale = max(1, abs(y + x), abs(y - x))
    return (y + x) / scale, (y - x) / scale


def _deadzone(value, width):
    if abs(value) <= width:
        return 0.0
    return (abs(value) - width) / (1 - width) * (1 if value > 0 else -1)


class DriveController:
    def __init__(self, max_rpm=200, serial_factory=serial.Serial, clock=time.monotonic,
                 status_timeout=STATUS_TIMEOUT):
        self.max_rpm = max_rpm
        self.serial_factory = serial_factory
        self.clock = clock
        self.lock = threading.RLock()
        self.ports = (None, None)
        self.devices = (None, None)
        self.invert = (False, False)
        self.target = (0, 0)
        self.last_command = 0.0
        self.session = None
        self.sequence = -1
        self.checks = {"left": None, "right": None}
        self.status_timeout = status_timeout
        self.error = ""
        self.stop_event = threading.Event()
        self.worker = None

    def available_ports(self):
        return [{"device": p.device, "description": p.description}
                for p in list_ports.comports(include_links=True)]

    def snapshot(self):
        with self.lock:
            return {"ports": self.available_ports(), "left": self.ports[0],
                    "right": self.ports[1], "connected": all(self.devices),
                    "max_rpm": self.max_rpm, "error": self.error,
                    "target": list(self.target), "checks": self.checks}

    def _probe(self, device, expected, port):
        deadline = time.monotonic() + self.status_timeout
        next_request = 0.0
        response = "No STATUS response"
        while time.monotonic() < deadline:
            now = time.monotonic()
            if now >= next_request:
                command = b"STATUS\n"
                if device.write(command) != len(command):
                    raise serial.SerialException("Incomplete status request")
                next_request = now + 0.3
            line = device.readline().decode("ascii", errors="replace").strip()
            if line in ("LSTAT,OK", "RSTAT,OK", "L OK", "R OK"):
                return {"port": port, "expected": expected, "response": line,
                        "matched": line == expected,
                        "role_matched": line[0] == expected[0]}
            if line.startswith("# CAN DEAD"):
                response = "Motor controller initialization failed"
                break
        return {"port": port, "expected": expected, "response": response,
                "matched": False, "role_matched": False}

    def _send(self, left, right):
        for device, rpm in zip(self.devices, (left, right)):
            if device is not None:
                command = f"{rpm},0\n".encode("ascii")
                if device.write(command) != len(command):
                    raise serial.SerialException("Incomplete motor command")

    def _disconnect(self):
        for device in self.devices:
            if device is not None:
                try:
                    command = b"0,0\n"
                    device.write(command)
                except (OSError, serial.SerialException):
                    pass
                try:
                    device.close()
                except (OSError, serial.SerialException):
                    pass
        self.devices = (None, None)
        self.ports = (None, None)
        self.target = (0, 0)
        self.session = None
        self.sequence = -1

    def configure(self, left, right, invert_left=False, invert_right=False):
        if (not all(isinstance(p, str) for p in (left, right))
                or Path(left).resolve() == Path(right).resolve()):
            raise ValueError("Choose two different serial ports")
        if not all(isinstance(v, bool) for v in (invert_left, invert_right)):
            raise ValueError("Inversion settings must be booleans")
        if {left, right} - {p["device"] for p in self.available_ports()}:
            raise ValueError("Select ports from the current device list")
        with self.lock:
            self._disconnect()
            self.checks = {"left": {"port": left, "expected": "LSTAT,OK", "response": "Not checked", "matched": False},
                           "right": {"port": right, "expected": "RSTAT,OK", "response": "Not checked", "matched": False}}
            opened = []
            try:
                for port in (left, right):
                    opened.append(self.serial_factory(port, BAUD, timeout=0.1, write_timeout=0.1))
                for side, device, port, expected in zip(("left", "right"), opened, (left, right),
                                                        ("LSTAT,OK", "RSTAT,OK")):
                    try:
                        self.checks[side] = self._probe(device, expected, port)
                    except (OSError, serial.SerialException) as exc:
                        self.checks[side] = {"port": port, "expected": expected,
                                             "response": f"Serial error: {exc}", "matched": False,
                                             "role_matched": False}
                if not all(check["matched"] for check in self.checks.values()):
                    legacy = any(check["response"] in ("L OK", "R OK") for check in self.checks.values())
                    self.error = ("Board sides identified, but the installed firmware uses an unverified drive protocol"
                                  if legacy and all(check.get("role_matched") for check in self.checks.values())
                                  else "Motor board identity check failed")
                    raise ConnectionCheckError(self.error, self.checks.copy())
                self.devices = tuple(opened)
                self.ports = (left, right)
                self.invert = (invert_left, invert_right)
                self._send(0, 0)
            except (OSError, serial.SerialException, ConnectionCheckError) as exc:
                for device in opened:
                    try:
                        device.close()
                    except (OSError, serial.SerialException):
                        pass
                self.devices = (None, None)
                self.error = str(exc)
                if isinstance(exc, ConnectionCheckError):
                    raise
                raise ConnectionCheckError(f"Could not open motor ports: {exc}", self.checks.copy()) from exc
            self.target = (0, 0)
            self.last_command = 0.0
            self.session = secrets.token_urlsafe(24)
            self.sequence = -1
            self.error = ""
            return self.session

    def session_snapshot(self, session):
        with self.lock:
            if not self.session or session != self.session or not all(self.devices):
                raise ValueError("Motor boards are not connected")
            return {"left": self.ports[0], "right": self.ports[1],
                    "checks": self.checks, "max_rpm": self.max_rpm}

    def command(self, session, x, y, sequence):
        with self.lock:
            if not self.session or session != self.session or not all(self.devices):
                raise ValueError("Connect motor ports first")
            if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 0:
                raise ValueError("Invalid command sequence")
            if sequence <= self.sequence:
                return list(self.target)
            left, right = mix(x, y)
            self.target = tuple(round(v * self.max_rpm) * (-1 if inv else 1)
                                for v, inv in zip((left, right), self.invert))
            self.last_command = self.clock()
            self.sequence = sequence
            try:
                self._send(*self.target)
            except (OSError, serial.SerialException) as exc:
                self.error = f"Motor connection lost: {exc}"
                self._disconnect()
                raise ValueError(self.error) from exc
            return list(self.target)

    def halt(self, session, sequence):
        with self.lock:
            if session != self.session or not self.session:
                raise ValueError("Connect motor ports first")
            if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 0:
                raise ValueError("Invalid command sequence")
            if sequence <= self.sequence:
                return
            self.sequence = sequence
            self.target = (0, 0)
            self.last_command = 0.0
            try:
                self._send(0, 0)
            except (OSError, serial.SerialException) as exc:
                self.error = f"Motor connection lost: {exc}"
                self._disconnect()
                raise ValueError(self.error) from exc

    def tick(self):
        with self.lock:
            if not all(self.devices):
                return
            if self.clock() - self.last_command > COMMAND_TIMEOUT:
                self.target = (0, 0)
            try:
                self._send(*self.target)
            except (OSError, serial.SerialException) as exc:
                self.error = f"Motor connection lost: {exc}"
                self._disconnect()

    def start(self):
        self.worker = threading.Thread(target=self._run, daemon=True)
        self.worker.start()

    def _run(self):
        while not self.stop_event.wait(COMMAND_PERIOD):
            self.tick()

    def close(self):
        self.stop_event.set()
        if self.worker:
            self.worker.join(timeout=1)
        with self.lock:
            self._disconnect()


def make_handler(controller, pairing_code, root):
    class Handler(BaseHTTPRequestHandler):
        def respond(self, status, payload):
            data = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path == "/api/state":
                self.respond(200, controller.snapshot())
                return
            names = {"/": ("connect.html", "text/html"),
                     "/drive": ("drive.html", "text/html"),
                     "/connect.js": ("connect.js", "text/javascript"),
                     "/drive.js": ("drive.js", "text/javascript"),
                     "/drive.css": ("drive.css", "text/css")}
            if path not in names:
                self.send_error(404)
                return
            name, kind = names[path]
            data = (root / name).read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", kind + "; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            if self.path not in ("/api/connect", "/api/session", "/api/drive", "/api/stop"):
                self.send_error(404)
                return
            origin = self.headers.get("Origin")
            host = self.headers.get("Host")
            if not host or origin != f"http://{host}":
                self.respond(403, {"error": "Same-origin request required"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 512 or self.headers.get("Content-Type", "").split(";", 1)[0] != "application/json":
                    raise ValueError("Invalid request body")
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise ValueError("Expected a JSON object")
                if self.path == "/api/connect":
                    if body.get("code") != pairing_code:
                        self.respond(403, {"error": "Invalid pairing code"})
                        return
                    session = controller.configure(body.get("left"), body.get("right"),
                                                   body.get("invert_left", False), body.get("invert_right", False))
                    result = {"session": session, "checks": controller.snapshot()["checks"]}
                elif self.path == "/api/session":
                    result = controller.session_snapshot(body.get("session"))
                elif self.path == "/api/drive":
                    result = {"target": controller.command(body.get("session"), body.get("x"), body.get("y"), body.get("sequence"))}
                else:
                    controller.halt(body.get("session"), body.get("sequence"))
                    result = {"target": [0, 0]}
                self.respond(200, result)
            except ConnectionCheckError as exc:
                self.respond(409, {"error": str(exc), "checks": exc.checks})
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                self.respond(400, {"error": str(exc)})

        def log_message(self, *_):
            pass

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--http-port", type=int, default=8766)
    parser.add_argument("--max-rpm", type=int, default=200)
    args = parser.parse_args()
    if not 1 <= args.max_rpm <= 30000:
        parser.error("--max-rpm must be between 1 and 30000")
    controller = DriveController(args.max_rpm)
    code = f"{secrets.randbelow(1_000_000):06d}"
    root = Path(__file__).resolve().parent.parent / "web"
    server = ThreadingHTTPServer((args.host, args.http_port), make_handler(controller, code, root))
    controller.start()
    print(f"Drive server: http://<device-ip>:{args.http_port}  Pairing code: {code}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()
        controller.close()


if __name__ == "__main__":
    main()
