"""Find which serial port is which device by what it sends, not by its name.

USB serial names (ttyUSB0, cu.usbserial-110) and even hub paths change with
re-plugging, a different hub or a different USB-serial chip. Every device on
this robot is recognisable from its traffic:

* lidar: valid 47-byte packets at 230400 baud;
* GPS: checksummed NMEA sentences at 9600 baud;
* IMU / magnetometer: ``IMU1,`` / ``MAG1,`` frames (or their diagnostics);
* motor boards: answer ``STATUS`` with ``LSTAT,OK`` (left) or ``RSTAT,OK`` (right).

Probing is passive first. Only a port that stays silent is sent ``STATUS``.
USB adapters and extra Raspberry Pi UARTs (``/dev/ttyAMA1``-``9``, e.g. GPS on
UART5 at ``/dev/ttyAMA5``) are probed. Run ``python -m robot.ports`` to print
the current map.
"""
import argparse
import glob
import json
import os
import sys
import threading
import time

import serial
from serial.tools import list_ports

from .gps import parse_nmea
from .imu import parse_imu
from .lidar import Parser
from .magnetometer import parse_mag

ROLES = ("lidar", "gps", "imu", "mag", "left", "right")
LISTEN_SECONDS = 1.5
MOTOR_SECONDS = 7.0
MOTOR_REPLIES = {"LSTAT,OK": "left", "L OK": "left", "RSTAT,OK": "right", "R OK": "right"}


def _open(device, baud, factory):
    port = factory(port=None, baudrate=baud, timeout=0.1, write_timeout=0.5, exclusive=True)
    port.dtr = port.rts = False
    port.port = device
    port.open()
    return port


def _lines(port, seconds, clock):
    """Yield complete lines received on ``port`` for up to ``seconds``."""
    buffer = bytearray()
    deadline = clock() + seconds
    while clock() < deadline:
        buffer.extend(port.read(256))
        while b"\n" in buffer:
            line, _, rest = buffer.partition(b"\n")
            buffer[:] = rest
            yield bytes(line)
        if len(buffer) > 4096:
            buffer.clear()


def _is_lidar(device, factory, seconds, clock):
    with _open(device, 230400, factory) as port:
        parser, count, deadline = Parser(), 0, clock() + seconds
        while clock() < deadline:
            count += len(parser.feed(port.read(512)))
            if count >= 3:
                return True
    return False


def _is_gps(device, factory, seconds, clock):
    with _open(device, 9600, factory) as port:
        for line in _lines(port, seconds, clock):
            try:
                parse_nmea(line)
                return True
            except (ValueError, IndexError, UnicodeError):
                pass
    return False


def _sensor_role(line):
    """Return ``imu`` or ``mag`` for a frame or diagnostic line, else None."""
    try:
        text = line.decode("ascii").strip()
    except UnicodeError:
        return None
    if text.startswith("#"):
        return "imu" if "IMU1" in text else "mag" if "MAG1" in text else None
    try:
        if text.startswith(("IMU1,", "IMU,")):
            return "imu" if parse_imu(line) is not None else None
        if text.startswith(("MAG1,", "MAG,")):
            return "mag" if parse_mag(line) is not None else None
    except (ValueError, IndexError, UnicodeError):
        return None
    return None


def _serial_role(device, factory, listen, motor_wait, clock):
    """Listen at 115200; a silent port is asked ``STATUS`` like a motor board."""
    with _open(device, 115200, factory) as port:
        for line in _lines(port, listen, clock):
            role = _sensor_role(line)
            if role:
                return role
        deadline, next_request = clock() + motor_wait, 0.0
        while clock() < deadline:
            if clock() >= next_request:
                port.write(b"STATUS\n")
                next_request = clock() + 0.3
            for line in _lines(port, 0.3, clock):
                text = line.decode("ascii", errors="replace").strip()
                if text in MOTOR_REPLIES:
                    return MOTOR_REPLIES[text]
                role = _sensor_role(line)
                if role:
                    return role
    return None


def classify(device, factory=serial.Serial, listen=LISTEN_SECONDS,
             motor_wait=MOTOR_SECONDS, clock=time.monotonic):
    """Return the role of the device on ``device``, or None if unrecognised."""
    if _is_lidar(device, factory, listen, clock):
        return "lidar"
    if _is_gps(device, factory, listen, clock):
        return "gps"
    return _serial_role(device, factory, listen, motor_wait, clock)


# Extra PL011 UARTs enabled with dtoverlay=uartN on a Raspberry Pi 4 (pins, not USB).
# ttyAMA0 is left out: with serial0 on the mini UART it carries Bluetooth.
ONBOARD_UARTS = "/dev/ttyAMA[1-9]*"


def serial_devices():
    """Serial ports to probe: USB adapters once each (links and macOS tty.* twins
    removed) plus extra on-board Raspberry Pi UARTs such as /dev/ttyAMA5."""
    found = {}
    for info in list_ports.comports(include_links=True):
        if info.vid is None:
            continue
        real = os.path.realpath(info.device)
        if real.startswith("/dev/tty.") and sys.platform == "darwin":
            continue
        found.setdefault(real, info.device if info.device == real else real)
    for path in glob.glob(ONBOARD_UARTS):
        found.setdefault(os.path.realpath(path), path)
    return sorted(found)


usb_serial_devices = serial_devices


def discover(devices=None, skip=(), factory=serial.Serial, listen=LISTEN_SECONDS,
             motor_wait=MOTOR_SECONDS, clock=time.monotonic):
    """Probe ports in parallel and return ``{"roles", "ports", "conflicts"}``.

    ``roles`` maps a role to a device only when exactly one port claimed it.
    ``ports`` records, per probed device, its role or the reason it has none.
    A role claimed by two ports lands in ``conflicts`` and is not assigned.
    ``skip`` lists ports somebody else already holds open (not touched).
    """
    skipped = {os.path.realpath(p) for p in skip if p}
    devices = [d for d in (serial_devices() if devices is None else devices)
               if os.path.realpath(d) not in skipped]
    results = {}

    def probe(device):
        try:
            role = classify(device, factory, listen, motor_wait, clock)
            results[device] = {"role": role, "error": None if role else "No known device answered"}
        except (serial.SerialException, OSError) as exc:
            results[device] = {"role": None, "error": str(exc)}

    threads = [threading.Thread(target=probe, args=(d,), daemon=True) for d in devices]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    claims = {}
    for device, result in results.items():
        if result["role"]:
            claims.setdefault(result["role"], []).append(device)
    roles = {role: found[0] for role, found in claims.items() if len(found) == 1}
    conflicts = {role: sorted(found) for role, found in claims.items() if len(found) > 1}
    return {"roles": roles, "ports": results, "conflicts": conflicts}


def main():
    cli = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    cli.add_argument("--json", action="store_true", help="Print machine-readable output")
    cli.add_argument("--skip", action="append", default=[], help="Port to leave alone (repeatable)")
    args = cli.parse_args()
    report = discover(skip=args.skip)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        for role in ROLES:
            print(f"{role:6} {report['roles'].get(role, '-')}")
        for device, result in sorted(report["ports"].items()):
            if not result["role"]:
                print(f"unrecognised {device}: {result['error']}")
        for role, devices in report["conflicts"].items():
            print(f"CONFLICT {role}: {', '.join(devices)}")
    return 1 if report["conflicts"] else 0


if __name__ == "__main__":
    sys.exit(main())
