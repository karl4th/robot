"""Read the robot's sensors and print them once a second, without the control server.

Serial sensors (lidar, GPS, Nano IMU) are found by their traffic on USB ports
and extra Pi UARTs such as /dev/ttyAMA5; an MPU6050 on the Pi I2C pins is used
when no Nano IMU answers. Motors are never commanded. A read-only page with the
live readings is served on --http-port (default 8765); it has no controls.
Run on the Pi:

    .venv/bin/python -m robot.sensors

and open http://<pi-ip>:8765 on a phone or laptop in the same network.
"""

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import threading
import time

from .dashboard import ScanState, read_sensor
from .gps import GPSState, read_gps
from .imu import IMUState, read_imu
from .imu_i2c import BUS, read_imu_i2c
from .ports import discover

PAGE = Path(__file__).resolve().parent.parent / "web" / "sensors.html"


def summary(scan, gps, imu):
    """One status line per sensor, from the readers' snapshots."""
    lines = []
    if scan is not None:
        s = scan.snapshot()
        lines.append(f"lidar {s['port'] or '-'}: " + (f"live {s['hz']} Hz, {s['packets']} packets, "
                                                      f"{s['crc_errors']} CRC errors" if s["live"] else s["error"]))
    if gps is not None:
        g = gps.snapshot()
        if g["status"] == "live":
            state = (f"fix {g['latitude']:.6f},{g['longitude']:.6f}, {g['satellites']} sats, "
                     f"HDOP {g['hdop']}")
        elif g["status"] == "no_fix":
            state = f"no fix yet, {g['satellites'] or 0} sats, {g['messages']} messages"
        else:
            state = g["error"] or g["status"]
        lines.append(f"gps {g['port']}: {state}")
    if imu is not None:
        i = imu.snapshot()
        sample = i["sample"]
        if i["status"] == "live" and sample:
            a, w = sample["accel_g"], sample["gyro_dps"]
            state = (f"live {i['hz']:.1f} Hz, accel g [{a[0]:+.3f} {a[1]:+.3f} {a[2]:+.3f}], "
                     f"gyro dps [{w[0]:+.2f} {w[1]:+.2f} {w[2]:+.2f}], {sample['temperature_c']:.1f} C")
        else:
            state = i["error"] or i["status"]
        lines.append(f"imu {i['port']}: {state}")
    return lines


def readings(scan, gps, imu):
    """Everything the page shows, as one JSON-ready dict."""
    return {"time": time.time(),
            "lidar": scan.snapshot() if scan is not None else None,
            "gps": gps.snapshot() if gps is not None else None,
            "imu": imu.snapshot() if imu is not None else None}


def make_handler(scan, gps, imu, page=PAGE):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path == "/api/readings":
                data, kind = json.dumps(readings(scan, gps, imu)).encode(), "application/json"
            elif path in ("/", "/index.html"):
                data, kind = page.read_bytes(), "text/html"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", kind + "; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, *_):
            pass

    return Handler


def main():
    cli = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    cli.add_argument("--seconds", type=float, default=0, help="Stop after this long; 0 runs until Ctrl+C")
    cli.add_argument("--i2c-bus", default=BUS, help="I2C device for a Pi-wired MPU6050; 'none' disables it")
    cli.add_argument("--gps-baud", type=int, default=9600)
    cli.add_argument("--host", default="0.0.0.0", help="Address for the read-only web page")
    cli.add_argument("--http-port", type=int, default=8765, help="Web page port; 0 disables the page")
    cli.add_argument("--quiet", action="store_true", help="Do not print readings every second")
    args = cli.parse_args()

    report = discover()
    roles = report["roles"]
    print("Serial ports: " + (", ".join(f"{r}={d}" for r, d in sorted(roles.items())) or "none"), flush=True)
    for role, devices in report["conflicts"].items():
        print(f"Ambiguous {role}: {', '.join(devices)}; not used", flush=True)

    stop = threading.Event()
    scan = gps = imu = None
    jobs = []
    if "lidar" in roles:
        scan = ScanState()
        jobs.append((read_sensor, (scan, roles["lidar"], stop)))
    if "gps" in roles:
        gps = GPSState(roles["gps"])
        jobs.append((read_gps, (gps, args.gps_baud, stop)))
    if "imu" in roles:
        imu = IMUState(roles["imu"])
        jobs.append((read_imu, (imu, None, stop)))
    elif args.i2c_bus != "none" and os.path.exists(args.i2c_bus):
        imu = IMUState(f"{args.i2c_bus}@0x68")
        jobs.append((read_imu_i2c, (imu, stop)))
    if not jobs:
        print("No sensors found.", file=sys.stderr)
        return 1
    for target, arguments in jobs:
        threading.Thread(target=target, args=arguments, daemon=True).start()

    server = None
    if args.http_port:
        server = ThreadingHTTPServer((args.host, args.http_port), make_handler(scan, gps, imu))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        print(f"Readings page: http://{args.host}:{args.http_port}", flush=True)

    started = time.monotonic()
    try:
        while not args.seconds or time.monotonic() - started < args.seconds:
            time.sleep(1)
            if not args.quiet:
                print(time.strftime("%H:%M:%S") + "  " + "\n          ".join(summary(scan, gps, imu)), flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        if server is not None:
            server.shutdown()
            server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
