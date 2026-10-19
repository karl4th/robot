"""Read-only QMC5883L serial telemetry; scale and acquisition are not verified."""
from collections import deque
import math
import re
import threading
import time

import serial

LEGACY = re.compile(r'X:\s*(-?\d+)\s+Y:\s*(-?\d+)\s+Z:\s*(-?\d+)')


def parse_mag(raw):
    text = raw.decode('ascii').strip()
    if text.startswith('#'):
        return None
    if text.startswith('MAG,'):
        fields = text.split(',')
        if len(fields) != 4 or not all(re.fullmatch(r'-?\d+', x) for x in fields[1:]):
            raise ValueError('Expected MAG and three signed integers')
        values, kind = list(map(int, fields[1:])), 'csv'
    else:
        match = LEGACY.fullmatch(text)
        if not match:
            raise ValueError('Unrecognized magnetic frame')
        values, kind = list(map(int, match.groups())), 'legacy'
    if any(not -32768 <= x <= 32767 for x in values):
        raise ValueError('Value outside signed 16-bit range')
    return dict(raw=values, format=kind)


class MagState:
    def __init__(self, port=None, field_range=8):
        self.lock = threading.Lock()
        self.port, self.baud = port, None
        self.field_range = field_range
        self.scale = {2: 12000, 8: 3000}[field_range]
        self.sample = None
        self.last = self.changed = 0
        self.samples = self.rejected = 0
        self.times = deque(maxlen=30)
        self.error = 'Waiting for magnetometer' if port else 'Magnetometer not configured'

    def ingest(self, raw, now=None):
        now = time.monotonic() if now is None else now
        try:
            sample = parse_mag(raw)
        except (ValueError, UnicodeError):
            with self.lock:
                self.rejected += 1
            return False
        if sample is None:
            return False
        with self.lock:
            if now-self.last > 1:
                self.times.clear()
                self.changed = now
            if self.sample is None or sample['raw'] != self.sample['raw']:
                self.changed = now
            self.sample, self.last = sample, now
            self.times.append(now)
            self.samples += 1
            self.error = ''
        return True

    def disconnected(self, error):
        with self.lock:
            self.error = str(error)
            self.times.clear()

    def snapshot(self, now=None):
        now = time.monotonic() if now is None else now
        with self.lock:
            live = bool(self.sample and now-self.last < 1 and not self.error)
            rate = (len(self.times)-1)/(self.times[-1]-self.times[0]) if len(self.times)>1 and self.times[-1]>self.times[0] else None
            result = dict(status='live' if live else 'offline' if self.port else 'disabled',
                          port=self.port, baud=self.baud, field_range=self.field_range,
                          scale_verified=False, calibrated=False, error=self.error,
                          samples=self.samples, rejected=self.rejected, hz=rate if live else None,
                          age_ms=round((now-self.last)*1000) if self.last else None, sample=None)
            if live:
                s = dict(self.sample)
                x,y,z = s['raw']
                s['field_ut'] = [v*100/self.scale for v in (x,y,z)]
                s['norm_ut'] = math.sqrt(sum(v*v for v in s['field_ut']))
                s['unchanged_s'] = now-self.changed
                s['clipped'] = any(v in (-32768,32767) for v in (x,y,z))
                s['angle_deg'] = math.degrees(math.atan2(y,x)) % 360 if (x or y) and not s['clipped'] else None
                result['sample'] = s
            return result


def read_mag(state, baud, stop):
    while not stop.is_set():
        for rate in ([baud] if baud else [115200,9600]):
            if stop.is_set():
                return
            try:
                port = serial.Serial(port=None, baudrate=rate, timeout=.1, exclusive=True)
                port.dtr = port.rts = False
                port.port = state.port
                with port:
                    with state.lock:
                        state.baud = rate
                    buffer = bytearray()
                    last = time.monotonic()
                    while not stop.is_set():
                        buffer.extend(port.read(128))
                        while b'\n' in buffer:
                            line, _, rest = buffer.partition(b'\n')
                            buffer[:] = rest
                            if state.ingest(bytes(line)):
                                last = time.monotonic()
                        if len(buffer)>4096:
                            buffer.clear()
                        if time.monotonic()-last>3:
                            raise RuntimeError('No valid magnetic samples. Checking port and baud rate.')
            except (serial.SerialException, OSError, RuntimeError) as exc:
                state.disconnected(exc)
        stop.wait(1)
