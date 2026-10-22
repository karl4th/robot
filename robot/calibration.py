"""Acknowledged calibration workflow; serial writes stay in the owning reader."""
import secrets
import threading
import time

FACES = ('+X', '-X', '+Y', '-Y', '+Z', '-Z')


class Calibration:
    def __init__(self, sensor):
        self.sensor = sensor
        self.lock = threading.Lock()
        self.phase = 'idle'
        self.step = 0
        self.message = 'Ready to calibrate'
        self.last_frame = 0
        self.supported = False
        self.device_busy = False
        self.pending = None
        self.outbox = None
        self.started = 0
        self.deadline = 0
        self.session = secrets.token_hex(8)

    def observe(self, sample, now):
        with self.lock:
            self.supported = sample.get('format') == 'v1'
            self.last_frame = now
            self.device_busy = bool(sample.get('flags', 0) & 8)

    def disconnect(self, reason='Connection lost; calibration state is uncertain'):
        with self.lock:
            self.supported = False
            self.outbox = self.pending = None
            if self.phase not in ('idle', 'saved'):
                self.phase, self.message = 'error', reason

    def _tick(self, now):
        if self.pending and now > self.deadline:
            self.pending = self.outbox = None
            self.phase = 'error'
            self.message = 'No acknowledgement from the board. Cancel before retrying.'

    def snapshot(self):
        with self.lock:
            now = time.monotonic()
            self._tick(now)
            available = self.supported and now-self.last_frame < 1
            duration = 6 if self.sensor == 'imu' else 60
            return dict(session=self.session, phase=self.phase, step=self.step,
                        available=available, device_busy=self.device_busy,
                        message=self.message, elapsed=max(0, now-self.started) if self.phase=='running' else 0,
                        duration=duration, pending=self.pending is not None)

    def request(self, action, session):
        with self.lock:
            now = time.monotonic()
            self._tick(now)
            if session != self.session:
                raise ValueError('Page is out of date. Refresh it.')
            if not self.supported or now-self.last_frame >= 1:
                raise ValueError('Upload the calibration sketch and wait for live versioned data.')
            if action == 'abort':
                command = 'ABORT'
            else:
                if self.pending or self.device_busy:
                    raise ValueError('A capture is already running. Wait or cancel.')
                if action == 'begin' and self.phase in ('idle', 'saved', 'error'):
                    self.step = 0
                    command = 'CAL ACCEL RESET' if self.sensor == 'imu' else 'CAL START'
                elif action == 'capture' and self.sensor == 'imu' and self.phase == 'ready' and self.step < 7:
                    command = 'CAL GYRO' if self.step == 0 else 'CAL ACCEL ' + FACES[self.step-1]
                elif action == 'save' and self.phase == 'accepted':
                    command = 'SAVE'
                else:
                    raise ValueError('Action is not allowed at this step.')
            self.pending = command
            self.outbox = command
            self.phase = 'sending'
            self.message = 'Waiting for board acknowledgement'
            self.deadline = now + 3

    def write_pending(self, port):
        # Called only by the serial owner, never by an HTTP request thread.
        with self.lock:
            self._tick(time.monotonic())
            if self.outbox:
                command = self.outbox
                self.outbox = None
                data = (command + '\n').encode('ascii')
                if port.write(data) != len(data):
                    raise OSError('Incomplete calibration command write')

    def diagnostic(self, raw):
        try:
            line = raw.decode('ascii').strip()
        except UnicodeError:
            return
        if not line.startswith('#'):
            return
        with self.lock:
            now = time.monotonic()
            if line.startswith('#BOOT'):
                self.outbox = self.pending = None
                self.phase = 'idle'
                self.step = 0
                self.message = 'Board restarted. Start a new calibration.'
                self.session = secrets.token_hex(8)
                return
            if line.startswith('#ERR'):
                if self.pending or self.phase in ('ready', 'accepted'):
                    recoverable = self.sensor == 'imu' and self.pending and (
                        self.pending == 'CAL GYRO' or self.pending.startswith('CAL ACCEL ')
                    ) and line[5:].split(',')[0] in {
                        'CAL_MOVEMENT_OR_NOISE', 'CAL_ACCEL_NOISE', 'CAL_GYRO_NOISE',
                        'CAL_GYRO_BIAS', 'CAL_GRAVITY_RANGE', 'FACE_ORIENTATION',
                        'CAL_TIMEOUT', 'IMU_SATURATION',
                    }
                    self.phase = 'ready' if recoverable else 'error'
                    self.message = line[5:].replace('_', ' ')
                    if recoverable:
                        self.message += '. Retry this step; previous faces are retained.'
                    self.outbox = self.pending = None
                return
            command = self.pending
            if command == 'ABORT' and line == '#CAL,ABORTED':
                self.phase, self.message = 'idle', 'Capture cancelled. Accepted RAM corrections remain; nothing was saved.'
                self.step = 0
            elif command == 'CAL ACCEL RESET' and line == '#CAL,FACES_CLEARED':
                self.phase, self.message = 'ready', 'Place the sensor still on a stable surface.'
            elif command and command.startswith('CAL ') and (line.startswith('#CAL,SETTLE_2S') or line.startswith('#CAL,ROTATE_ALL_AXES')):
                self.phase = 'running'
                self.started = now
                self.deadline = now + (12 if self.sensor == 'imu' else 70)
                self.message = 'Keep completely still' if self.sensor == 'imu' else 'Rotate slowly around all three axes'
                return
            elif command == 'CAL GYRO' and line.startswith('#CAL,GYRO_ACCEPTED_RAM'):
                self.step = 1
                self.phase, self.message = 'ready', 'Gyroscope accepted. Position the first accelerometer face.'
            elif command and command.startswith('CAL ACCEL ') and line.startswith('#CAL,FACE_ACCEPTED,MASK='):
                try:
                    mask = int(line.split('=')[-1])
                except ValueError:
                    return
                expected = (1 << self.step) - 1
                if mask != expected:
                    self.phase, self.message = 'error', 'Unexpected face mask. Restart calibration.'
                elif self.step == 6:
                    # The final face is not success until the fit itself is accepted.
                    self.deadline = now + 3
                    return
                else:
                    self.step += 1
                    self.phase, self.message = 'ready', 'Face accepted. Reposition the sensor for the next face.'
            elif command == 'CAL ACCEL -Z' and line.startswith('#CAL,ACCEL_ACCEPTED_RAM'):
                self.step = 7
                self.phase, self.message = 'accepted', 'All captures accepted. Save to keep corrections after restart.'
            elif command == 'CAL START' and line.startswith('#CAL,MAG_ACCEPTED_RAM'):
                self.phase, self.message = 'accepted', 'Magnetic fit accepted. Save to keep corrections after restart.'
            elif command == 'SAVE' and line == '#OK,SAVED':
                self.phase, self.message = 'saved', 'Board confirmed: calibration saved to EEPROM. Live operation continues.'
            else:
                return
            self.outbox = self.pending = None
