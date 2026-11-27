import struct
import threading
import unittest
from unittest.mock import patch

from robot import ports
from robot.imu import IMUState, parse_imu
from robot.imu_i2c import CONFIG, configure, frame, read_imu_i2c


class FakeBus:
    def __init__(self, identity=0x68, sticky=True, samples=3, stop=None):
        self.registers = {0x75: identity}
        self.sticky, self.samples, self.stop = sticky, samples, stop
        self.closed = False

    def write(self, register, value):
        if self.sticky:
            self.registers[register] = value

    def read(self, register, count):
        if register == 0x3B:
            self.samples -= 1
            if self.samples <= 0 and self.stop:
                self.stop.set()
            # 1 g on Z, small rotation about X
            return struct.pack(">7h", 0, 0, 16384, 1000, 131, 0, 0)
        return bytes([self.registers.get(register, 0)])

    def close(self):
        self.closed = True


class FrameTests(unittest.TestCase):
    def test_frame_is_a_valid_imu1_line_in_physical_units(self):
        sample = parse_imu(frame(7, 140, struct.pack(">7h", 0, -8192, 16384, 1000, 131, -262, 0)))
        self.assertEqual(sample["format"], "v1")
        self.assertEqual((sample["sequence"], sample["device_ms"], sample["flags"]), (7, 140, 1))
        self.assertEqual(sample["accel_g"], [0, -0.5, 1])
        self.assertEqual(sample["gyro_dps"], [1, -2, 0])
        self.assertEqual(sample["accel_raw"], [0, -8192, 16384])

    def test_clipped_raw_values_are_rejected_downstream(self):
        with self.assertRaises(ValueError):
            parse_imu(frame(0, 0, struct.pack(">7h", 32767, 0, 16384, 0, 0, 0, 0)))


class ConfigureTests(unittest.TestCase):
    def test_writes_and_verifies_configuration(self):
        bus = FakeBus()
        configure(bus, sleep=lambda _: None)
        for register, value in CONFIG:
            self.assertEqual(bus.registers[register], value)

    def test_wrong_chip_and_lost_writes_fail(self):
        with self.assertRaisesRegex(RuntimeError, "WHO_AM_I"):
            configure(FakeBus(identity=0x70), sleep=lambda _: None)
        with self.assertRaisesRegex(RuntimeError, "did not keep"):
            configure(FakeBus(sticky=False), sleep=lambda _: None)


class ReaderTests(unittest.TestCase):
    def test_reader_feeds_state_and_closes_bus(self):
        stop = threading.Event()
        bus = FakeBus(samples=3, stop=stop)
        state = IMUState("/dev/i2c-1@0x68")
        with patch("robot.imu_i2c.configure"):
            read_imu_i2c(state, stop, bus_factory=lambda: bus)
        self.assertEqual(state.samples, 3)
        self.assertEqual(state.snapshot()["sample"]["accel_g"], [0, 0, 1])
        self.assertTrue(bus.closed)

    def test_bus_error_is_reported_on_the_state(self):
        stop = threading.Event()

        def broken():
            stop.set()
            raise OSError("No such device")

        state = IMUState("/dev/i2c-1@0x68")
        read_imu_i2c(state, stop, bus_factory=broken)
        self.assertIn("I2C: No such device", state.snapshot()["error"])


class OnboardUartTests(unittest.TestCase):
    def test_extra_pi_uarts_are_probed_but_not_bluetooth(self):
        with patch("robot.ports.list_ports.comports", return_value=[]), \
                patch("robot.ports.glob.glob", return_value=["/dev/ttyAMA5"]) as found:
            self.assertEqual(ports.serial_devices(), ["/dev/ttyAMA5"])
        self.assertEqual(found.call_args.args[0], "/dev/ttyAMA[1-9]*")


if __name__ == "__main__":
    unittest.main()
