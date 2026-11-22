"""Local live lidar dashboard. Run with uv run python -m robot.dashboard."""
import argparse
from collections import deque
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import threading
import time
import secrets
from serial.tools import list_ports

from .lidar import Parser, detect_port, open_port
from .ports import discover
from .gps import GPSState, read_gps
from .imu import IMUState, read_imu
from .magnetometer import MagState, read_mag
from .compass import heading
from .drive import DriveController, make_handler


class ScanState:
    def __init__(self):
        self.lock = threading.Lock()
        self.samples = deque(maxlen=20000)
        self.last = 0.0
        self.packets = 0
        self.speed = 0
        self.crc_errors = 0
        self.error = "Waiting for sensor"
        self.port = ""
        self.hint = None

    def snapshot(self):
        with self.lock:
            now = time.monotonic()
            while self.samples and self.samples[0][0] < now - 0.25:
                self.samples.popleft()
            live = now - self.last < 1 and not self.error
            return dict(live=bool(live), error=self.error, port=self.port,
                        age_ms=round((now-self.last)*1000) if self.last else None,
                        packets=self.packets, hz=round(self.speed/360, 2),
                        crc_errors=self.crc_errors,
                        points=[p[1:] for p in self.samples] if live else [])


def read_sensor(state, device, stop):
    while not stop.is_set():
        try:
            selected = device() if callable(device) else device or detect_port()
            if not selected:
                raise RuntimeError("Lidar not found. Waiting for it to appear on a USB port.")
            with open_port(selected) as port:
                parser = Parser()
                with state.lock:
                    state.port = selected
                    state.error = "Waiting for sensor"
                last = time.monotonic()
                while not stop.is_set():
                    packets = parser.feed(port.read(512))
                    now = time.monotonic()
                    with state.lock:
                        for packet in packets:
                            state.samples.extend((now, p.angle_deg, p.distance_mm, p.intensity)
                                                 for p in packet.points if p.distance_mm > 0 and p.intensity > 0)
                            state.packets += 1
                            state.speed = packet.speed_deg_s
                            state.last = last = now
                            state.error = ""
                        state.crc_errors = parser.bad_crc
                    if now-last > 3:
                        raise RuntimeError("No valid packets. Check sensor power and connection.")
        except Exception as exc:
            with state.lock:
                state.error = str(exc)
                state.samples.clear()
            stop.wait(2)


class SensorHub:
    """Owns the selected sensor ports and their reader threads."""

    def __init__(self, args):
        self.lock = threading.RLock()
        self.options = args
        self.auto = bool(getattr(args, "auto_ports", False))
        self.known = dict(getattr(args, "discovered", None) or {})
        self.motor_ports = lambda: ()
        self.ports = {"lidar": "auto" if self.auto else None if args.no_lidar else args.port or "auto",
                      "gps": args.gps_port, "imu": args.imu_port, "mag": args.mag_port}
        if self.auto and args.port:
            self.ports["lidar"] = args.port
        self.workers = []
        self.stop = threading.Event()
        self.closed = threading.Event()
        self._start()
        if self.auto:
            threading.Thread(target=self._watch, daemon=True).start()

    def _start(self):
        self.scan = ScanState()
        self.gps = GPSState(self.ports["gps"])
        self.imu = IMUState(self.ports["imu"], self.options.imu_accel_range,
                            self.options.imu_gyro_range)
        self.mag = MagState(self.ports["mag"], self.options.mag_range)
        if self.ports["lidar"] not in (None, "auto"):
            self.scan.hint = self.ports["lidar"]
        if not self.ports["lidar"]:
            self.scan.error = "Lidar not configured"
        for role in ("lidar", "gps", "imu", "mag"):
            if self.ports[role]:
                self._spawn(role)

    def _spawn(self, role):
        o = self.options
        if role == "lidar":
            device = ((lambda: self.scan.hint) if self.auto
                      else None if self.ports["lidar"] == "auto" else self.ports["lidar"])
            target, arguments = read_sensor, (self.scan, device, self.stop)
        elif role == "gps":
            target, arguments = read_gps, (self.gps, o.gps_baud, self.stop)
        elif role == "imu":
            target, arguments = read_imu, (self.imu, o.imu_baud, self.stop)
        else:
            target, arguments = read_mag, (self.mag, o.mag_baud, self.stop)
        worker = threading.Thread(target=target, args=arguments, daemon=True)
        worker.start()
        self.workers.append(worker)

    def _healthy(self):
        return {"lidar": self.scan.snapshot()["live"],
                "gps": self.gps.snapshot()["status"] in ("live", "no_fix"),
                "imu": self.imu.snapshot()["status"] == "live",
                "mag": self.mag.snapshot()["status"] == "live"}

    def _assign(self, role, device):
        """Point a running or new reader at ``device`` without disturbing the others."""
        if role == "lidar":
            self.scan.hint = device
            self.ports["lidar"] = device
            return
        state = {"gps": self.gps, "imu": self.imu, "mag": self.mag}[role]
        fresh = not self.ports[role]
        with state.lock:
            state.port = device
            if fresh:
                state.error = "Waiting for " + role.upper()
        self.ports[role] = device
        if fresh:
            self._spawn(role)

    def rediscover(self):
        """Find sensors that are down by what they send and point their readers at them.

        Healthy sensors, motor boards and ports a reader already holds are not
        probed, so a re-plugged device is found without a restart.
        """
        with self.lock:
            if not self.auto or self.stop.is_set():
                return {}
            health = self._healthy()
            wanted = [role for role, ok in health.items() if not ok]
            if not wanted:
                return {}
            skip = [self.ports[r] for r, ok in health.items() if ok and self.ports[r]]
            skip += [d for d, role in self.known.items() if role in ("left", "right")]
            skip += [p for p in self.motor_ports() if p]
        report = discover(skip=skip)
        with self.lock:
            if self.stop.is_set():
                return {}
            self.known.update({d: r["role"] for d, r in report["ports"].items() if r["role"]})
            for role in wanted:
                if role in report["roles"]:
                    self._assign(role, report["roles"][role])
        return report["roles"]

    def _watch(self):
        while not self.closed.wait(10):
            try:
                self.rediscover()
            except Exception:  # discovery must never take the dashboard down
                pass

    def configure(self, ports, motor_ports):
        if not isinstance(ports, dict) or set(ports) != {"lidar", "gps", "imu", "mag"}:
            raise ValueError("Expected lidar, GPS, IMU and compass ports")
        if any(value is not None and not isinstance(value, str) for value in ports.values()):
            raise ValueError("Invalid sensor port")
        selected = {name: value or None for name, value in ports.items()}
        available = {p.device for p in list_ports.comports(include_links=True)}
        values = [value for value in selected.values() if value]
        if "auto" in values or any(value not in available for value in values):
            raise ValueError("Choose ports from the current device list")
        resolved = [str(Path(value).resolve()) for value in values]
        if len(resolved) != len(set(resolved)):
            raise ValueError("Each sensor needs a different port")
        if set(resolved) & {str(Path(value).resolve()) for value in motor_ports if value}:
            raise ValueError("A sensor port is already assigned to a motor board")
        with self.lock:
            self.stop.set()
            for worker in self.workers:
                worker.join(timeout=3)
            if any(worker.is_alive() for worker in self.workers):
                raise RuntimeError("A sensor reader did not stop; ports were not changed")
            self.workers = []
            self.stop = threading.Event()
            self.auto = False  # an explicit choice in the setup page ends auto mode
            self.ports = selected
            self._start()
            return self.snapshot()

    def snapshot(self):
        with self.lock:
            return {"selected": dict(self.ports),
                    "ports": [{"device": p.device, "description": p.description}
                              for p in list_ports.comports(include_links=True)]}

    def close(self):
        self.closed.set()
        with self.lock:
            self.stop.set()
            for worker in self.workers:
                worker.join(timeout=3)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--port", help="Serial device; otherwise detect automatically")
    cli.add_argument("--no-lidar", action="store_true", help="Run without opening or probing a lidar port")
    cli.add_argument("--gps-port", help="GPS serial device; omitted disables GPS")
    cli.add_argument("--gps-baud", type=int, default=9600)
    cli.add_argument("--imu-port", help="IMU serial device; omitted disables IMU")
    cli.add_argument("--imu-baud", type=int, choices=(9600, 115200), help="Default: detect 115200 or 9600")
    cli.add_argument("--imu-accel-range", type=int, choices=(2, 4, 8, 16), default=2)
    cli.add_argument("--imu-gyro-range", type=int, choices=(250, 500, 1000, 2000), default=250)
    cli.add_argument("--mag-port", help="Magnetometer serial device; omitted disables it")
    cli.add_argument("--mag-baud", type=int, choices=(9600, 115200), help="Default: detect 115200 or 9600")
    cli.add_argument("--mag-range", type=int, choices=(2, 8), default=8)
    cli.add_argument("--auto-ports", action="store_true",
                     help="Identify lidar, GPS, IMU and magnetometer by their traffic instead of port names, "
                          "and re-find them if they are re-plugged. Explicit port options still win.")
    cli.add_argument("--http-port", type=int, default=8765)
    cli.add_argument("--host", default="127.0.0.1", help="HTTP bind address; use 0.0.0.0 for a trusted LAN")
    cli.add_argument("--max-rpm", type=int, default=50, help="Motor speed ceiling")
    args = cli.parse_args()
    if args.no_lidar and args.port:
        cli.error('--no-lidar cannot be combined with --port')
    if args.auto_ports and args.no_lidar:
        cli.error('--auto-ports cannot be combined with --no-lidar')
    args.discovered = {}
    if args.auto_ports:
        report = discover()
        for role, option in (("lidar", "port"), ("gps", "gps_port"), ("imu", "imu_port"), ("mag", "mag_port")):
            if report["roles"].get(role) and not getattr(args, option):
                setattr(args, option, report["roles"][role])
        args.discovered = {d: r["role"] for d, r in report["ports"].items() if r["role"]}
        print("Ports found: " + (", ".join(f"{r}={d}" for r, d in sorted(report["roles"].items())) or "none"), flush=True)
        for role, devices in report["conflicts"].items():
            print(f"Ports ambiguous for {role}: {', '.join(devices)}; not assigned", flush=True)
    if (not args.auto_ports) and (args.gps_port or args.imu_port or args.mag_port) and not (args.port or args.no_lidar):
        cli.error('Additional sensors require an explicit lidar --port to avoid probing their ports')
    ports = [str(Path(p).resolve()) for p in (args.port, args.gps_port, args.imu_port, args.mag_port) if p]
    if len(ports) != len(set(ports)):
        cli.error('Each sensor must use a different serial port')
    if not 1 <= args.max_rpm <= 30000:
        cli.error('--max-rpm must be between 1 and 30000')
    hub = SensorHub(args)
    control_token = secrets.token_urlsafe(32)
    root = Path(__file__).resolve().parent.parent / "web"
    drive = DriveController(args.max_rpm)
    drive.reserved_ports = {str(Path(p).resolve()) for p in hub.ports.values() if p and p != "auto"}
    hub.motor_ports = lambda: [p for p in (drive.snapshot()["left"], drive.snapshot()["right"]) if p]
    configuration_lock = threading.Lock()
    pairing_code = f"{secrets.randbelow(1_000_000):06d}"
    DriveHandler = make_handler(drive, pairing_code, root)

    class Handler(DriveHandler):
        def do_POST(self):
            if self.path == '/api/connect':
                with configuration_lock:
                    return super().do_POST()
            if self.path not in ('/api/calibration', '/api/sensors'):
                return super().do_POST()
            host = self.headers.get('Host')
            origin = self.headers.get('Origin')
            credential = (self.headers.get('X-Control-Token') == control_token
                          if self.path == '/api/calibration' else True)
            if not host or origin != f'http://{host}' or not credential:
                self.send_error(403)
                return
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 1024:
                    raise ValueError('Invalid request size')
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise ValueError('Expected an object')
                if self.path == '/api/sensors':
                    if body.get('code') != pairing_code:
                        self.respond(403, {'error': 'Invalid pairing code'})
                        return
                    with configuration_lock:
                        motor_state = drive.snapshot()
                        result = hub.configure(body.get('ports'), (motor_state['left'], motor_state['right']))
                        drive.reserved_ports = {str(Path(p).resolve()) for p in hub.ports.values() if p}
                    data = json.dumps(result).encode()
                else:
                    if body.get('sensor') not in ('imu', 'mag'):
                        raise ValueError('Unknown sensor')
                    controller = hub.imu.calibration if body['sensor'] == 'imu' else hub.mag.calibration
                    controller.request(body.get('action'), body.get('session'))
                    data = json.dumps({'ok': True}).encode()
                code = 200
            except (ValueError, TypeError, RuntimeError) as exc:
                data = json.dumps({'error': str(exc)}).encode()
                code = 409
            self.send_response(code)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path == "/api/calibration":
                data = json.dumps(dict(token=control_token, imu=hub.imu.calibration.snapshot(), mag=hub.mag.calibration.snapshot())).encode()
                kind = "application/json"
            elif path == "/api/sensors":
                data = json.dumps(hub.snapshot()).encode()
                kind = "application/json"
            elif path == "/api/compass":
                now = time.monotonic()
                data = json.dumps(heading(hub.imu.snapshot(now), hub.mag.snapshot(now)), allow_nan=False).encode()
                kind = "application/json"
            elif path == "/api/mag":
                data = json.dumps(hub.mag.snapshot(), allow_nan=False).encode()
                kind = "application/json"
            elif path == "/api/imu":
                data = json.dumps(hub.imu.snapshot(), allow_nan=False).encode()
                kind = "application/json"
            elif path == "/api/gps":
                data = json.dumps(hub.gps.snapshot(), allow_nan=False).encode()
                kind = "application/json"
            elif path == "/api/scan":
                data = json.dumps(hub.scan.snapshot()).encode()
                kind = "application/json"
            elif path in ("/", "/app.js", "/style.css", "/cockpit.css", "/cockpit-drive.js", "/gps-map.js", "/camera.js", "/sensor-setup.js"):
                file = root / ("index.html" if path == "/" else path[1:])
                data = file.read_bytes()
                kind = {".html": "text/html", ".js": "text/javascript", ".css": "text/css"}[file.suffix]
            else:
                return super().do_GET()
            self.send_response(200)
            self.send_header("Content-Type", kind + "; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer((args.host, args.http_port), Handler)
    drive.start()
    print(f"Cockpit: http://{args.host}:{args.http_port}  Pairing code: {pairing_code}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        drive.close()
        hub.close()


if __name__ == "__main__":
    main()
