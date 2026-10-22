# Telemetry reference

Requires Python 3.10+ and uv. Dependencies are pinned in uv.lock.

```sh
uv sync
uv run python -m robot.lidar
```

The reader probes USB serial ports for valid measurement packets and selects a
port only when exactly one responds. Probing opens each USB serial port briefly;
use an explicit port to skip probing when other serial equipment is connected.

```sh
uv run python -m robot.lidar --list-ports
uv run python -m robot.lidar --port /dev/cu.usbserial-0001
uv run python -m robot.lidar --port /dev/cu.usbserial-0001 --seconds 10 --output capture.jsonl
```

Stop with Ctrl+C. The script reads at 230400 baud, 8N1, without flow control or
serial commands. It does not control motor speed. Output files must not already
exist. The console reports cumulative packet/point counts, rotation frequency,
CRC errors, and the nearest nonzero return in each reporting interval.
This nearest return is unfiltered telemetry, not an obstacle safety decision.

Each JSONL record contains host receive time (`received_unix_ns`), sensor packet
`timestamp_ms` (wraps on the device; not wall-clock time), `speed_deg_s`, and
12 points. Each point contains clockwise `angle_deg`, `distance_mm`, and raw
`intensity` (0-255). Zero-distance returns are preserved in the file. Angles are
interpolated between packet endpoints. Records are packets, not complete scans.

`Parser.feed(bytes)` can also be imported into another Python program. It handles
partial reads, verifies CRC-8, discards corrupt packets, and resynchronizes.
No valid packets for three seconds causes an error. If reading fails, check the
selected port, power, wiring, and whether another program holds the serial port.

```sh
uv run python -m unittest discover -s tests -t . -v
```

## Live dashboard

```sh
uv run python -m robot.dashboard --port /dev/cu.usbserial-0001
```

Open http://127.0.0.1:8765 in a browser. Stop another reader before starting the
 dashboard: the serial port is opened exclusively. Stop the server with Ctrl+C.
The server listens only on loopback. No cloud service is required.

The dashboard shows recent returns from a 250 ms rolling window. It supports
zoom, a flattened perspective view, freeze/resume, and sensor heading adjustment.
Zero degrees faces up; angles increase clockwise. Adjust heading to match the
sensor mounting orientation. The yellow robot is an illustration, not a measured
footprint. Perspective changes the display projection; the sensor remains 2D.

This is a robot-relative live scan, not SLAM or a persistent world map. Returns
are not motion-compensated or filtered for obstacle decisions. No wheel odometry,
robot control, battery state, or localization is implied. On data loss, live
points are cleared; a deliberately frozen view remains labeled. The reader
retries connection after errors. Use --http-port to change the local HTTP port.

## GPS position and session track

```sh
uv run python -m robot.dashboard --port /dev/cu.usbserial-0001 --gps-port /dev/cu.usbserial-112110
```

GPS uses 9600 baud by default; override with `--gps-baud`. Both ports must be
specified and different when GPS is enabled. Omitting `--gps-port` keeps the
lidar dashboard available with GPS marked as not configured.

The GPS panel shows latitude/longitude, satellites used, HDOP, altitude above
mean sea level, speed in km/h, course over ground, and fix age. GGA and RMC
sentences are checksum-validated. The receiver is read only; no configuration
commands are sent. Transport freshness, position validity, and motion freshness
are checked separately. A fix older than three seconds is not shown as live.

The north-up track uses a local approximate projection and retains up to 900
fixes in server memory, about 15 minutes at 1 Hz. Restarting clears it. Connection
gaps break the line. It does not load map tiles or send coordinates externally.
Historical tracks remain visible during GPS loss. Lidar freeze does not freeze
GPS. Raw stationary drift is visible; this is not a filtered route or SLAM, and
HDOP is dimensionless, not a meter accuracy estimate. Course is travel direction,
not robot orientation. The GPS and lidar coordinates are not fused.

## IMU telemetry

```sh
uv run python -m robot.dashboard --port /dev/cu.usbserial-0001 --gps-port /dev/cu.usbserial-112110 --imu-port /dev/cu.usbserial-112120
```

The reader tries 115200 and 9600 baud on the explicitly selected IMU port.
Use `--imu-baud 115200` or `--imu-baud 9600` to select one rate. A disconnected
receiver is retried. Serial writes occur only for explicit web calibration actions; firmware uploads are not performed.

Supported newline-terminated formats:

```text
IMU,ax,ay,az,temp,gx,gy,gz
Acc: X=948 Y=-16140 Z=1952 | Gyr: X=3 Y=-201 Z=-14
```

CSV fields are signed 16-bit decimal integers in the order shown. Lines beginning
with `#` are ignored. The legacy stream has no temperature field. Neither format
has a checksum, device timestamp, sequence number, or I2C health flag; a valid
line proves transport and format, not successful hardware acquisition.

Conversion assumes the reset ranges of +/-2 g (16384 counts/g) and +/-250 deg/s
(131 counts per deg/s). Legacy firmware does not verify these registers, so its scales are labeled
as assumed. The calibration sketch explicitly configures ranges and publishes
corrected units in CRC-protected IMU1 frames. If legacy firmware uses other ranges,
set `--imu-accel-range` (2, 4, 8, 16) and `--imu-gyro-range` (250, 500, 1000, 2000).
Chip temperature uses `raw / 340 + 36.53`; it is not ambient temperature.

The panel displays raw values, acceleration including gravity, angular rates,
host-observed sample frequency, temperature when transmitted, and gravity-based
roll/pitch in sensor axes. Tilt is hidden outside 0.8-1.2 g, but that gate does
not guarantee absence of translation. Mounting rotation is not calibrated; no
yaw, velocity integration, stationarity inference, or GPS drift suppression is
implemented. Samples older than one second are cleared. IMU stays live when the
lidar display is frozen. Restarting the dashboard clears the in-memory GPS track.

## Magnetic sensor

```sh
uv run python -m robot.dashboard --port /dev/cu.usbserial-0001 --gps-port /dev/cu.usbserial-112110 --imu-port /dev/cu.usbserial-112120 --mag-port /dev/cu.usbserial-112140
```

The supplied compass sketch targets QMC5883L at I2C address 0x0D. The desktop
reader supports `MAG,x,y,z` at 115200 baud and legacy `X: ... Y: ... Z: ...`
lines at 9600 baud, with automatic probing on the explicitly selected port.
Use `--mag-baud` to select one of these rates. No firmware is uploaded.

The calibration sketch explicitly configures 50 Hz, +/-8 gauss and OSR 512,
checks sensor registers and acquisition status, and emits CRC-protected MAG1
frames with raw and corrected readings. Legacy streams retain assumed scales;
use `--mag-range 2` only for legacy firmware configured to +/-2 gauss.

The robot compass combines calibrated magnetic readings with accelerometer
orientation. Calibration corrects offsets and diagonal scale only. Successful
EEPROM saving does not validate heading accuracy. The field-strength gate cannot
detect every disturbance. GPS, lidar and compass are not fused.

## Calibration firmware

See [firmware setup and calibration](../firmware/README.md) for the two ATmega328P
sketches, upload steps, gyro/six-face acceleration calibration, magnetic offset
and diagonal scale calibration, and explicit EEPROM saving. The versioned
`IMU1` / `MAG1` frames carry CRC16, raw readings and corrected units. The dashboard
recognizes them while retaining legacy support. No automatic upload or physical
calibration is performed by the dashboard.

## Web calibration

Click **Calibrate** on either sensor card after uploading the calibration sketch.
The wizard guides the still gyro capture, six acceleration faces, or magnetic
rotation capture, then offers **Save & continue**. The board must acknowledge
acceptance and EEPROM saving. Capture errors, cancellation, connection loss and
legacy firmware are handled explicitly. Keep Serial Monitor closed. Live
telemetry continues during the workflow. See [the guide](../firmware/README.md).

### Robot compass

Mount both calibrated sensors rigidly with +X forward, +Y left and +Z up.
Confirm this mounting in the compass card to enable the robot heading. The
north-up dial shows robot forward direction clockwise from magnetic north.
Accelerometer gravity removes magnetic-field tilt; both calibrated streams must
be fresh. Rapid rotation, acceleration and near-vertical forward orientation
suppress the heading. Separate USB reception times are only a freshness check,
not hardware synchronization; use this compass for slow, gravity-dominated motion.

True north is optional and requires a manually entered local magnetic declination
in degrees, east positive. Reference and mounting preferences stay in this browser.
Moving the magnetometer onto a different mount or near steel, motors or power
wiring can require recalibration in its final installation. Field-strength checks
cannot detect every magnetic disturbance. This does not align the lidar map or
provide position localization.
