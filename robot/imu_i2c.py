"""Read an MPU6050 wired straight to the Raspberry Pi I2C pins.

The reader configures the chip like the Nano sketch (+/-2 g, +/-250 deg/s,
42 Hz low-pass, 50 Hz) and turns each sample into the same CRC-checked
``IMU1`` frame the sketch sends, so ``IMUState`` and the dashboard handle it
unchanged. No calibration is applied here (flags=1): the Nano keeps its
coefficients in its own EEPROM, which a Pi-wired sensor does not have.
Needs ``dtparam=i2c_arm=on`` (``/dev/i2c-1``) and the ``i2c`` group.
"""
import binascii
import fcntl
import os
import struct
import time

I2C_SLAVE = 0x0703
ADDRESS = 0x68
BUS = "/dev/i2c-1"
ACCEL_LSB_PER_G = 16384
GYRO_LSB_PER_DPS = 131
PERIOD = 0.02
# Clock from the X gyro, all axes on, 42 Hz low-pass, 1 kHz / (1 + 19) = 50 Hz,
# +/-250 deg/s, +/-2 g.
CONFIG = ((0x6B, 0x01), (0x6C, 0x00), (0x1A, 0x03), (0x19, 19), (0x1B, 0x00), (0x1C, 0x00))


class Bus:
    """Minimal register access over the Linux i2c-dev interface."""

    def __init__(self, path=BUS, address=ADDRESS):
        self.fd = os.open(path, os.O_RDWR)
        try:
            fcntl.ioctl(self.fd, I2C_SLAVE, address)
        except OSError:
            os.close(self.fd)
            raise

    def write(self, register, value):
        os.write(self.fd, bytes([register, value]))

    def read(self, register, count):
        os.write(self.fd, bytes([register]))
        data = os.read(self.fd, count)
        if len(data) != count:
            raise OSError(f"Short I2C read: {len(data)} of {count} bytes")
        return data

    def close(self):
        os.close(self.fd)


def configure(bus, sleep=time.sleep):
    """Reset and configure the chip, then read every register back."""
    identity = bus.read(0x75, 1)[0]
    if identity != 0x68:
        raise RuntimeError(f"Unexpected MPU6050 WHO_AM_I 0x{identity:02X}")
    bus.write(0x6B, 0x80)
    sleep(0.1)
    for register, value in CONFIG:
        bus.write(register, value)
    sleep(0.1)
    for register, value in CONFIG:
        if bus.read(register, 1)[0] != value:
            raise RuntimeError(f"MPU6050 register 0x{register:02X} did not keep its value")


def frame(sequence, millis, data):
    """Build an ``IMU1`` line from the 14 bytes starting at register 0x3B."""
    ax, ay, az, temp, gx, gy, gz = struct.unpack(">7h", data)
    accel = [round(v * 1000 / ACCEL_LSB_PER_G) for v in (ax, ay, az)]
    gyro = [round(v * 1000 / GYRO_LSB_PER_DPS) for v in (gx, gy, gz)]
    fields = [sequence & 0xFFFFFFFF, millis & 0xFFFFFFFF, 1, ax, ay, az, temp, gx, gy, gz, *accel, *gyro]
    body = "IMU1," + ",".join(map(str, fields))
    return f"{body}*{binascii.crc_hqx(body.encode('ascii'), 0xFFFF):04X}".encode("ascii")


def read_imu_i2c(state, stop, bus_factory=Bus, clock=time.monotonic):
    """Feed ``state`` (an IMUState) from the I2C sensor until ``stop`` is set."""
    while not stop.is_set():
        bus = None
        try:
            bus = bus_factory()
            configure(bus)
            start = clock()
            sequence = 0
            next_at = start
            while not stop.is_set():
                data = bus.read(0x3B, 14)
                now = clock()
                state.ingest(frame(sequence, int((now - start) * 1000), data))
                sequence += 1
                next_at += PERIOD
                stop.wait(max(0.0, next_at - clock()))
        except (OSError, RuntimeError) as exc:
            state.disconnected(f"I2C: {exc}")
            stop.wait(1)
        finally:
            if bus is not None:
                bus.close()
