"""Read D500 measurement packets without sending device commands."""

import argparse
from dataclasses import asdict, dataclass
import json
import math
import struct
import sys
import time

import serial
from serial.tools import list_ports


@dataclass(frozen=True)
class Point:
    angle_deg: float
    distance_mm: int
    intensity: int


@dataclass(frozen=True)
class Packet:
    speed_deg_s: int
    timestamp_ms: int
    points: list[Point]


def crc8(data: bytes) -> int:
    crc = 0
    for value in data:
        crc ^= value
        for _ in range(8):
            crc = ((crc << 1) ^ (0x4D if crc & 0x80 else 0)) & 0xFF
    return crc


class Parser:
    """Incremental 47-byte packet decoder, with recovery after corrupt input."""

    def __init__(self):
        self.buffer = bytearray()
        self.bad_crc = 0

    def feed(self, data: bytes) -> list[Packet]:
        self.buffer.extend(data)
        packets = []
        while len(self.buffer) >= 2:
            start = self.buffer.find(b"\x54\x2c")
            if start < 0:
                self.buffer[:] = self.buffer[-1:] if self.buffer[-1] == 0x54 else b""
                break
            del self.buffer[:start]
            if len(self.buffer) < 47:
                break
            frame = bytes(self.buffer[:47])
            if crc8(frame[:-1]) != frame[-1]:
                self.bad_crc += 1
                del self.buffer[0]
                continue
            del self.buffer[:47]
            speed, first = struct.unpack_from("<HH", frame, 2)
            last, timestamp = struct.unpack_from("<HH", frame, 42)
            if first >= 36000 or last >= 36000:
                continue
            step = ((last - first) % 36000) / 11
            points = []
            for i in range(12):
                distance, intensity = struct.unpack_from("<HB", frame, 6 + 3 * i)
                points.append(Point(((first + step * i) / 100) % 360, distance, intensity))
            packets.append(Packet(speed, timestamp, points))
        return packets


def open_port(device: str) -> serial.Serial:
    port = serial.Serial(port=None, baudrate=230400, timeout=0.2, exclusive=True)
    port.dtr = False
    port.rts = False
    port.port = device
    port.open()
    return port


def detect_port() -> str:
    matches = []
    for info in list_ports.comports():
        if info.vid is None:
            continue
        print(f"Probing {info.device}...", file=sys.stderr)
        try:
            with open_port(info.device) as port:
                parser = Parser()
                count = 0
                deadline = time.monotonic() + 2
                while time.monotonic() < deadline:
                    count += len(parser.feed(port.read(512)))
                    if count >= 3:
                        matches.append(info.device)
                        break
        except (serial.SerialException, OSError) as exc:
            print(f"  {exc}", file=sys.stderr)
    if len(matches) != 1:
        raise RuntimeError(f"Expected one lidar, found {len(matches)}: {matches}. Use --port explicitly.")
    return matches[0]


def nonnegative(value: str) -> float:
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise argparse.ArgumentTypeError("Must be a finite nonnegative number")
    return result


def main() -> int:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--list-ports", action="store_true")
    cli.add_argument("--port", help="Serial device; default: detect USB serial lidar")
    cli.add_argument("--seconds", type=nonnegative, default=0, help="Duration; 0 runs until Ctrl+C")
    cli.add_argument("--output", help="Write raw decoded packets as JSONL (new file only)")
    args = cli.parse_args()
    if args.list_ports:
        for info in list_ports.comports():
            print(f"{info.device}: {info.description} [{info.hwid}]")
        return 0
    output = None
    try:
        device = args.port or detect_port()
        if args.output:
            output = open(args.output, "x", encoding="utf-8")
        with open_port(device) as port:
            print(f"Reading {device} at 230400 baud. Ctrl+C to stop.", file=sys.stderr)
            parser = Parser()
            start = last_valid = last_report = time.monotonic()
            packets_total = points_total = 0
            nearest = None
            while not args.seconds or time.monotonic() - start < args.seconds:
                packets = parser.feed(port.read(512))
                for packet in packets:
                    last_valid = time.monotonic()
                    packets_total += 1
                    points_total += len(packet.points)
                    for point in packet.points:
                        if point.distance_mm > 0 and point.intensity > 0:
                            if nearest is None or point.distance_mm < nearest.distance_mm:
                                nearest = point
                    if output:
                        record = {"received_unix_ns": time.time_ns(), **asdict(packet)}
                        output.write(json.dumps(record) + "\n")
                now = time.monotonic()
                if now - last_valid > 3:
                    raise RuntimeError("No valid measurement packets for 3 seconds. Check port, power and wiring.")
                if packets and now - last_report >= 1:
                    closest = "none" if nearest is None else f"{nearest.distance_mm} mm @ {nearest.angle_deg:.1f} deg"
                    print(f"packets={packets_total} points={points_total} rotation={packets[-1].speed_deg_s / 360:.2f} Hz nearest={closest} crc_errors={parser.bad_crc}", flush=True)
                    nearest = None
                    last_report = now
                    if output:
                        output.flush()
            print(f"Finished: packets={packets_total}, points={points_total}, crc_errors={parser.bad_crc}")
            if not packets_total:
                raise RuntimeError("No valid measurement packets received.")
        return 0
    except KeyboardInterrupt:
        print("\nStopped.", file=sys.stderr)
        return 0
    except (serial.SerialException, OSError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    finally:
        if output:
            output.close()


if __name__ == "__main__":
    sys.exit(main())
