import binascii
import struct
import unittest

from robot import ports
from robot.lidar import crc8


def lidar_frame():
    data = struct.pack("<BBHH", 0x54, 0x2C, 3600, 100)
    data += b"".join(struct.pack("<HB", 1000, 90) for _ in range(12))
    data += struct.pack("<HH", 200, 1)
    return data + bytes([crc8(data)])


def nmea(body):
    checksum = 0
    for char in body:
        checksum ^= ord(char)
    return f"${body}*{checksum:02X}\r\n".encode()


def v1(tag, count):
    body = ",".join([tag, "1", "100", "1"] + ["5"] * (count - 4))
    return f"{body}*{binascii.crc_hqx(body.encode(), 0xFFFF):04X}\r\n".encode()


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        self.now += 0.01
        return self.now


def fake_factory(behaviour):
    """behaviour: {(device, baud): bytes streamed} plus optional replies to STATUS."""
    class Fake:
        def __init__(self, port=None, baudrate=0, **_):
            self.baud, self.port, self.sent, self.buffer = baudrate, None, b"", b""

        def open(self):
            self.buffer = behaviour.get((self.port, self.baud), b"")
            if isinstance(self.buffer, Exception):
                raise self.buffer

        def read(self, size=1):
            data, self.buffer = self.buffer[:size], self.buffer[size:]
            return data

        def write(self, data):
            self.sent += data
            reply = behaviour.get((self.port, "reply"))
            if reply and data == b"STATUS\n":
                self.buffer += reply
            return len(data)

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    return Fake


class ClassifyTests(unittest.TestCase):
    def classify(self, behaviour, device="/dev/a"):
        return ports.classify(device, fake_factory(behaviour), listen=0.5, motor_wait=1.0, clock=Clock())

    def test_each_device_is_recognised_by_its_traffic(self):
        cases = {
            "lidar": {("/dev/a", 230400): lidar_frame() * 4},
            "gps": {("/dev/a", 9600): nmea("GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,")},
            "imu": {("/dev/a", 115200): v1("IMU1", 17)},
            "mag": {("/dev/a", 115200): v1("MAG1", 10)},
            "left": {("/dev/a", "reply"): b"LSTAT,OK\n"},
            "right": {("/dev/a", "reply"): b"RSTAT,OK\n"},
        }
        for role, behaviour in cases.items():
            with self.subTest(role=role):
                self.assertEqual(self.classify(behaviour), role)

    def test_silent_port_is_unknown_and_corrupt_frames_are_ignored(self):
        self.assertIsNone(self.classify({}))
        bad = v1("IMU1", 17).replace(b"*", b"*0")
        self.assertIsNone(self.classify({("/dev/a", 115200): bad}))


class DiscoverTests(unittest.TestCase):
    def test_roles_do_not_depend_on_port_names(self):
        for left, right in (("/dev/ttyUSB1", "/dev/ttyUSB3"), ("/dev/ttyUSB9", "/dev/ttyUSB2")):
            behaviour = {(left, "reply"): b"LSTAT,OK\n", (right, "reply"): b"RSTAT,OK\n",
                         ("/dev/ttyUSB4", 230400): lidar_frame() * 4}
            report = ports.discover([left, right, "/dev/ttyUSB4"], factory=fake_factory(behaviour),
                                    listen=0.5, motor_wait=1.0, clock=Clock())
            self.assertEqual(report["roles"], {"left": left, "right": right, "lidar": "/dev/ttyUSB4"})

    def test_conflict_error_and_skip(self):
        behaviour = {("/dev/a", 115200): v1("IMU1", 17), ("/dev/b", 115200): v1("IMU1", 17),
                     ("/dev/c", 115200): OSError("I/O error")}
        report = ports.discover(["/dev/a", "/dev/b", "/dev/c", "/dev/d"], skip=["/dev/d"],
                                factory=fake_factory(behaviour), listen=0.5, motor_wait=1.0, clock=Clock())
        self.assertEqual(report["roles"], {})
        self.assertEqual(report["conflicts"], {"imu": ["/dev/a", "/dev/b"]})
        self.assertIn("I/O error", report["ports"]["/dev/c"]["error"])
        self.assertNotIn("/dev/d", report["ports"])


if __name__ == "__main__":
    unittest.main()
