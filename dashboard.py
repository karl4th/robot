"""Local live lidar dashboard. Run with uv run dashboard.py."""
import argparse
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
import time

from lidar import Parser, detect_port, open_port
from gps import GPSState, read_gps


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
    cli.add_argument("--http-port", type=int, default=8765)
    args = cli.parse_args()
    if args.gps_port and not args.port:
        cli.error('--gps-port requires an explicit --port for lidar to avoid probing the GPS port')
    if args.gps_port == args.port and args.gps_port:
        cli.error('GPS and lidar must use different serial ports')
    state, stop = ScanState(), threading.Event()
    gps = GPSState(args.gps_port)
    root = Path(__file__).parent / "web"

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path == "/api/gps":
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


if __name__ == "__main__":
    main()
