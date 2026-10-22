"""Local live lidar dashboard. Run with uv run python -m robot.dashboard."""
import argparse
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
import time
import secrets

from .lidar import Parser, detect_port, open_port
from .gps import GPSState, read_gps
from .imu import IMUState, read_imu
from .magnetometer import MagState, read_mag
from .compass import heading


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
            selected = device or detect_port()
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


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--port", help="Serial device; otherwise detect automatically")
    cli.add_argument("--gps-port", help="GPS serial device; omitted disables GPS")
    cli.add_argument("--gps-baud", type=int, default=9600)
    cli.add_argument("--imu-port", help="IMU serial device; omitted disables IMU")
    cli.add_argument("--imu-baud", type=int, choices=(9600, 115200), help="Default: detect 115200 or 9600")
    cli.add_argument("--imu-accel-range", type=int, choices=(2, 4, 8, 16), default=2)
    cli.add_argument("--imu-gyro-range", type=int, choices=(250, 500, 1000, 2000), default=250)
    cli.add_argument("--mag-port", help="Magnetometer serial device; omitted disables it")
    cli.add_argument("--mag-baud", type=int, choices=(9600, 115200), help="Default: detect 115200 or 9600")
    cli.add_argument("--mag-range", type=int, choices=(2, 8), default=8)
    cli.add_argument("--http-port", type=int, default=8765)
    args = cli.parse_args()
    if (args.gps_port or args.imu_port or args.mag_port) and not args.port:
        cli.error('Additional sensors require an explicit lidar --port to avoid probing their ports')
    ports = [str(Path(p).resolve()) for p in (args.port, args.gps_port, args.imu_port, args.mag_port) if p]
    if len(ports) != len(set(ports)):
        cli.error('Each sensor must use a different serial port')
    state, stop = ScanState(), threading.Event()
    gps = GPSState(args.gps_port)
    imu = IMUState(args.imu_port, args.imu_accel_range, args.imu_gyro_range)
    mag = MagState(args.mag_port, args.mag_range)
    control_token = secrets.token_urlsafe(32)
    root = Path(__file__).resolve().parent.parent / "web"

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            if self.path != '/api/calibration':
                self.send_error(404)
                return
            origin = self.headers.get('Origin')
            allowed = {f'http://127.0.0.1:{args.http_port}', f'http://localhost:{args.http_port}'}
            if (origin and origin not in allowed) or ('http://' + self.headers.get('Host', '')) not in allowed or self.headers.get('X-Control-Token') != control_token:
                self.send_error(403)
                return
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 512:
                    raise ValueError('Invalid request size')
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict) or body.get('sensor') not in ('imu', 'mag'):
                    raise ValueError('Unknown sensor')
                controller = imu.calibration if body['sensor'] == 'imu' else mag.calibration
                controller.request(body.get('action'), body.get('session'))
                data = json.dumps({'ok': True}).encode()
                code = 200
            except (ValueError, TypeError) as exc:
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
                if self.headers.get('Host') not in (f'127.0.0.1:{args.http_port}', f'localhost:{args.http_port}'):
                    self.send_error(403)
                    return
                data = json.dumps(dict(token=control_token, imu=imu.calibration.snapshot(), mag=mag.calibration.snapshot())).encode()
                kind = "application/json"
            elif path == "/api/compass":
                now = time.monotonic()
                data = json.dumps(heading(imu.snapshot(now), mag.snapshot(now)), allow_nan=False).encode()
                kind = "application/json"
            elif path == "/api/mag":
                data = json.dumps(mag.snapshot(), allow_nan=False).encode()
                kind = "application/json"
            elif path == "/api/imu":
                data = json.dumps(imu.snapshot(), allow_nan=False).encode()
                kind = "application/json"
            elif path == "/api/gps":
                data = json.dumps(gps.snapshot(), allow_nan=False).encode()
                kind = "application/json"
            elif path == "/api/scan":
                data = json.dumps(state.snapshot()).encode()
                kind = "application/json"
            elif path in ("/", "/app.js", "/style.css"):
                file = root / ("index.html" if path == "/" else path[1:])
                data = file.read_bytes()
                kind = {".html": "text/html", ".js": "text/javascript", ".css": "text/css"}[file.suffix]
            else:
                self.send_error(404)
                return
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

    server = ThreadingHTTPServer(("127.0.0.1", args.http_port), Handler)
    worker = threading.Thread(target=read_sensor, args=(state, args.port, stop), daemon=True)
    worker.start()
    gps_worker = None
    if args.gps_port:
        gps_worker = threading.Thread(target=read_gps, args=(gps, args.gps_baud, stop), daemon=True)
        gps_worker.start()
    imu_worker = None
    if args.imu_port:
        imu_worker = threading.Thread(target=read_imu, args=(imu, args.imu_baud, stop), daemon=True)
        imu_worker.start()
    mag_worker = None
    if args.mag_port:
        mag_worker = threading.Thread(target=read_mag, args=(mag, args.mag_baud, stop), daemon=True)
        mag_worker.start()
    print(f"Dashboard: http://127.0.0.1:{args.http_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        server.server_close()
        worker.join(timeout=3)
        if gps_worker:
            gps_worker.join(timeout=3)
        if imu_worker:
            imu_worker.join(timeout=3)
        if mag_worker:
            mag_worker.join(timeout=3)


if __name__ == "__main__":
    main()
