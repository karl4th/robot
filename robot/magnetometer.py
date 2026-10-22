"""QMC5883L telemetry and acknowledged calibration commands."""
from collections import deque
import math
import re
import threading
import time

import serial
from .sensor_protocol import decode_frame
from .calibration import Calibration

LEGACY = re.compile(r'X:\s*(-?\d+)\s+Y:\s*(-?\d+)\s+Z:\s*(-?\d+)')


def parse_mag(raw):
    text = raw.decode('ascii').strip()
    if text.startswith('#'):
        return None
    if text.startswith('MAG1,'):
        values = decode_frame(text, 'MAG1', 10, 27)
        seq, timestamp, flags = values[:3]
        raw, corrected = values[3:6], values[6:9]
        if any(not -32767 <= v <= 32766 for v in raw) or any(abs(v) > 4000000 for v in corrected):
            raise ValueError('Clipped or invalid magnetic field')
        return dict(raw=raw, format='v1', sequence=seq, device_ms=timestamp,
                    flags=flags, field_ut=[v/1000 for v in corrected])
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
        self.calibration = Calibration('mag')
        self.port, self.baud = port, None
        self.field_range = field_range
        self.scale = {2: 12000, 8: 3000}[field_range]
        self.sample = None
        self.diagnostic = ''
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
                self.changed = now
            if self.sample is None or sample['raw'] != self.sample['raw']:
                self.changed = now
            self.sample, self.last = sample, now
            self.times.append(now)
            self.samples += 1
            self.error = ''
        return True

    def disconnected(self, error):
        self.calibration.disconnect(str(error))
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
                          scale_verified=bool(live and self.sample.get('format') == 'v1'),
                          calibrated=bool(live and self.sample.get('flags', 0) & 2), error=self.error, diagnostic=self.diagnostic,
                          samples=self.samples, rejected=self.rejected, hz=rate if live else None,
                          age_ms=round((now-self.last)*1000) if self.last else None, sample=None)
            if live:
                s = dict(self.sample)
                x,y,z = s['raw']
                s['field_ut'] = s.get('field_ut', [v*100/self.scale for v in (x,y,z)])
                if s['format'] == 'v1':
                    result['field_range'] = 8
                s['norm_ut'] = math.sqrt(sum(v*v for v in s['field_ut']))
                s['unchanged_s'] = now-self.changed
                s['clipped'] = any(v in (-32768,32767) for v in (x,y,z))
                fx, fy, _ = s['field_ut']
                s['angle_deg'] = math.degrees(math.atan2(fy,fx)) % 360 if (fx or fy) and not s['clipped'] else None
                result['sample'] = s
            return result


def read_mag(state, baud, stop):
    while not stop.is_set():
        for rate in ([baud] if baud else [115200,9600]):
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
                            # Firmware diagnostics prove the baud and serial link are alive.
                            # Keep the port open while the board retries sensor initialization.
                            # This does not make missing measurements fresh or valid.
                            if valid or line.startswith((b'#BOOT,', b'#STATUS,MAG1,', b'#ERR,MAG_', b'#COEFF,')):
                                last = time.monotonic()
                        if len(buffer)>4096:
                            buffer.clear()
                        if time.monotonic()-last>3:
                            raise RuntimeError('No valid magnetic samples. Checking port and baud rate.')
            except (serial.SerialException, OSError, RuntimeError) as exc:
                state.disconnected(exc)
        stop.wait(1)
