"""IMU telemetry and acknowledged calibration commands."""
from collections import deque
import math
import re
import threading
import time

import serial
from .sensor_protocol import decode_frame
from .calibration import Calibration

LEGACY = re.compile(r'Acc: X=(-?\d+) Y=(-?\d+) Z=(-?\d+) \| Gyr: X=(-?\d+) Y=(-?\d+) Z=(-?\d+)')


def parse_imu(raw):
    text = raw.decode('ascii').strip()
    if text.startswith('#'):
        return None
    if text.startswith('IMU1,'):
        values = decode_frame(text, 'IMU1', 17, 15)
        seq, timestamp, flags = values[:3]
        raw = values[3:10]
        accel, gyro = values[10:13], values[13:16]
        if any(not -32767 <= v <= 32766 for v in raw):
            raise ValueError('Clipped or invalid raw value')
        if any(abs(v) > 8000 for v in accel) or any(abs(v) > 400000 for v in gyro):
            raise ValueError('Invalid corrected value')
        if raw[:3] == [0, 0, 0]:
            raise ValueError('Invalid gravity sample')
        return dict(accel_raw=raw[:3], temp_raw=raw[3], gyro_raw=raw[4:], format='v1',
                    sequence=seq, device_ms=timestamp, flags=flags,
                    accel_g=[v/1000 for v in accel], gyro_dps=[v/1000 for v in gyro])
    if text.startswith('IMU,'):
        fields = text.split(',')
        if len(fields) != 8 or not all(re.fullmatch(r'-?\d+', f) for f in fields[1:]):
            raise ValueError('Expected seven signed integers')
        ax, ay, az, temp, gx, gy, gz = map(int, fields[1:])
        kind = 'csv'
    else:
        match = LEGACY.fullmatch(text)
        if not match:
            raise ValueError('Unrecognized IMU frame')
        ax, ay, az, gx, gy, gz = map(int, match.groups())
        temp, kind = None, 'legacy'
    values = [ax, ay, az, gx, gy, gz] + ([] if temp is None else [temp])
    if any(not -32768 <= value <= 32767 for value in values):
        raise ValueError('Value outside signed 16-bit range')
    # Failed I2C reads can produce all -1; zero acceleration is also implausible here.
    if all(v == -1 for v in values) or ax == ay == az == 0:
        raise ValueError('Invalid sensor sample')
    return dict(accel_raw=[ax, ay, az], gyro_raw=[gx, gy, gz], temp_raw=temp, format=kind)


class IMUState:
    def __init__(self, port=None, accel_range=2, gyro_range=250):
        self.lock = threading.Lock()
        self.calibration = Calibration('imu')
        self.port = port
        self.baud = None
        self.accel_range, self.gyro_range = accel_range, gyro_range
        self.accel_scale = {2: 16384, 4: 8192, 8: 4096, 16: 2048}[accel_range]
        self.gyro_scale = {250: 131, 500: 65.5, 1000: 32.8, 2000: 16.4}[gyro_range]
        self.last = 0
        self.diagnostic = ""
        self.sample = None
        self.times = deque(maxlen=30)
        self.samples = self.rejected = 0
        self.error = 'Waiting for IMU' if port else 'IMU not configured'

    def ingest(self, raw, now=None):
        now = time.monotonic() if now is None else now
        try:
            sample = parse_imu(raw)
        except (ValueError, UnicodeError):
            with self.lock:
                self.rejected += 1
            return False
        if sample is None:
            self.calibration.diagnostic(raw)
            with self.lock:
                self.diagnostic = raw.decode('ascii').strip()
                if self.diagnostic.startswith('#ERR,'):
                    self.error = self.diagnostic[5:]
            return False
        self.calibration.observe(sample, now)
        with self.lock:
            if now-self.last > 1:
                self.times.clear()
            self.sample, self.last = sample, now
            self.times.append(now)
            self.samples += 1
            self.error = ''
        return True

    def disconnected(self, message):
        self.calibration.disconnect(str(message))
        with self.lock:
            self.error = str(message)
            self.times.clear()

    def snapshot(self, now=None):
        now = time.monotonic() if now is None else now
        with self.lock:
            live = bool(self.sample and now-self.last < 1 and not self.error)
            rate = (len(self.times)-1)/(self.times[-1]-self.times[0]) if len(self.times)>1 and self.times[-1]>self.times[0] else None
            result = dict(status='live' if live else 'offline' if self.port else 'disabled',
                          port=self.port, baud=self.baud, error=self.error, diagnostic=self.diagnostic, samples=self.samples,
                          rejected=self.rejected, hz=rate if live else None,
                          age_ms=round((now-self.last)*1000) if self.last else None,
                          accel_range=self.accel_range, gyro_range=self.gyro_range,
                          scales_verified=bool(live and self.sample.get('format') == 'v1'), sample=None)
            if live:
                s = dict(self.sample)
                a = s.get('accel_g', [v/self.accel_scale for v in s['accel_raw']])
                s['accel_g'] = a
                s['gyro_dps'] = s.get('gyro_dps', [v/self.gyro_scale for v in s['gyro_raw']])
                if s['format'] == 'v1':
                    result['accel_range'], result['gyro_range'] = 2, 250
                s['temperature_c'] = s['temp_raw']/340 + 36.53 if s['temp_raw'] is not None else None
                norm = math.sqrt(sum(v*v for v in a))
                s['accel_norm_g'] = norm
                # Gravity-based tilt is meaningful only near 1 g and without translation.
                s['roll_deg'] = math.degrees(math.atan2(a[1], a[2])) if .8 <= norm <= 1.2 and math.hypot(a[1],a[2]) > .05 else None
                s['pitch_deg'] = math.degrees(math.atan2(-a[0], math.hypot(a[1], a[2]))) if .8 <= norm <= 1.2 else None
                result['sample'] = s
            return result


def read_imu(state, baud, stop):
    rates = [baud] if baud else [115200, 9600]
    while not stop.is_set():
        for rate in rates:
            if stop.is_set():
                return
            try:
                port = serial.Serial(port=None, baudrate=rate, timeout=.1, exclusive=True, write_timeout=0.5)
                port.dtr = port.rts = False
                port.port = state.port
                with port:
                    with state.lock:
                        state.baud = rate
                    buffer = bytearray()
                    last = time.monotonic()
                    while not stop.is_set():
                        state.calibration.write_pending(port)
                        buffer.extend(port.read(128))
                        while b'\n' in buffer:
                            line, _, rest = buffer.partition(b'\n')
                            buffer[:] = rest
                            valid = state.ingest(bytes(line))
                            # Keep a responsive board connected while it retries sensor setup.
                            if valid or line.startswith((b'#BOOT,', b'#STATUS,IMU1,', b'#ERR,IMU_', b'#COEFF,')):
                                last = time.monotonic()
                        if len(buffer) > 4096:
                            buffer.clear()
                        if time.monotonic()-last > 3:
                            raise RuntimeError('No valid IMU samples. Checking port and baud rate.')
            except (serial.SerialException, OSError, RuntimeError) as exc:
                state.disconnected(exc)
        stop.wait(1)
