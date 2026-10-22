"""Read-only NMEA receiver with independent transport and fix freshness."""
from collections import deque
import math
import threading
import time

import serial


def number(value):
    if not value:
        return None
    result = float(value)
    if not math.isfinite(result):
        raise ValueError('Nonfinite value')
    return result


def coordinate(value, hemisphere, latitude):
    raw = number(value)
    allowed = ('N', 'S') if latitude else ('E', 'W')
    if raw is None or raw < 0 or hemisphere not in allowed:
        raise ValueError('Invalid coordinate')
    degrees = int(raw // 100)
    minutes = raw - degrees * 100
    result = degrees + minutes / 60
    if minutes >= 60 or result > (90 if latitude else 180):
        raise ValueError('Coordinate out of range')
    return -result if hemisphere in ('S', 'W') else result


def parse_nmea(raw):
    text = raw.decode('ascii').strip()
    if not text.startswith('$') or '*' not in text:
        raise ValueError('Missing frame or checksum')
    body, check = text[1:].split('*')
    checksum = 0
    for char in body:
        checksum ^= ord(char)
    if len(check) != 2 or checksum != int(check, 16):
        raise ValueError('Checksum mismatch')
    fields = body.split(',')
    if len(fields[0]) != 5:
        raise ValueError('Invalid sentence identifier')
    kind = fields[0][-3:]
    if kind == 'GGA':
        quality = int(fields[6])
        valid = quality in (1, 2, 4, 5)
        return dict(kind=kind, valid=valid, quality=quality,
                    utc=fields[1], satellites=int(fields[7] or 0), hdop=number(fields[8]),
                    altitude_m=number(fields[9]) if fields[10] == 'M' else None,
                    latitude=coordinate(fields[2], fields[3], True) if valid else None,
                    longitude=coordinate(fields[4], fields[5], False) if valid else None)
    if kind == 'RMC':
        valid = fields[2] == 'A' and (len(fields) <= 12 or fields[12] not in ('N', 'E', 'S'))
        speed = number(fields[7]) if valid else None
        course = number(fields[8]) if valid else None
        if speed is not None and speed < 0 or course is not None and not 0 <= course <= 360:
            raise ValueError('Invalid motion data')
        return dict(kind=kind, valid=valid, speed_kmh=speed * 1.852 if speed is not None else None,
                    course_deg=course)
    return dict(kind=kind)


class GPSState:
    def __init__(self, port=None):
        self.lock = threading.Lock()
        self.port = port
        self.error = 'Waiting for GPS' if port else 'GPS not configured'
        self.last_message = self.last_fix = self.last_gga = self.last_rmc = 0
        self.gga = {}
        self.rmc = {}
        self.messages = self.rejected = 0
        self.track = deque(maxlen=900)
        self.segment = 0
        self.last_track_time = 0

    def ingest(self, raw, now=None):
        now = time.monotonic() if now is None else now
        try:
            message = parse_nmea(raw)
        except (ValueError, IndexError, UnicodeError):
            with self.lock:
                self.rejected += 1
            return False
        with self.lock:
            self.messages += 1
            self.last_message = now
            self.error = ''
            if message['kind'] == 'GGA':
                self.gga = message
                self.last_gga = now
                if message['valid']:
                    self.last_fix = now
                    if now - self.last_track_time >= 0.8:
                        if now - self.last_track_time > 3:
                            self.segment += 1
                        self.track.append([message['latitude'], message['longitude'], self.segment])
                        self.last_track_time = now
                else:
                    self.segment += 1
            elif message['kind'] == 'RMC':
                self.rmc = message
                self.last_rmc = now
        return True

    def disconnected(self, error):
        with self.lock:
            self.error = str(error)
            self.gga = {}
            self.rmc = {}
            self.segment += 1

    def snapshot(self, now=None):
        now = time.monotonic() if now is None else now
        with self.lock:
            connected = bool(self.last_message and now-self.last_message < 3 and not self.error)
            gga_fresh = connected and now-self.last_gga < 3
            rmc_fresh = connected and now-self.last_rmc < 3
            fix = bool(gga_fresh and self.gga.get('valid') and
                       not (rmc_fresh and not self.rmc.get('valid')))
            status = 'live' if fix else 'no_fix' if connected else 'offline' if self.port else 'disabled'
            g = self.gga
            return dict(status=status, port=self.port, error=self.error,
                        latitude=g.get('latitude') if fix else None,
                        longitude=g.get('longitude') if fix else None,
                        satellites=g.get('satellites') if gga_fresh else None,
                        hdop=g.get('hdop') if gga_fresh else None,
                        altitude_m=g.get('altitude_m') if fix else None,
                        quality=g.get('quality') if gga_fresh else None,
                        utc=g.get('utc') if gga_fresh else None,
                        speed_kmh=self.rmc.get('speed_kmh') if fix and rmc_fresh else None,
                        course_deg=self.rmc.get('course_deg') if fix and rmc_fresh else None,
                        age_ms=round((now-self.last_fix)*1000) if self.last_fix else None,
                        messages=self.messages, rejected=self.rejected, track=list(self.track))


def read_gps(state, baud, stop):
    while not stop.is_set():
        try:
            port = serial.Serial(port=None, baudrate=baud, timeout=0.2, exclusive=True)
            port.dtr = port.rts = False
            port.port = state.port
            with port:
                buffer = bytearray()
                last = time.monotonic()
                while not stop.is_set():
                    buffer.extend(port.read(256))
                    while b'\n' in buffer:
                        line, _, rest = buffer.partition(b'\n')
                        buffer[:] = rest
                        if state.ingest(bytes(line)):
                            last = time.monotonic()
                    if len(buffer) > 4096:
                        buffer.clear()
                    if time.monotonic()-last > 5:
                        raise RuntimeError('No valid NMEA messages. Check GPS power, port and baud rate.')
        except (serial.SerialException, OSError, RuntimeError) as exc:
            state.disconnected(exc)
            stop.wait(2)
