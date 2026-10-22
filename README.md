# Robot sensor dashboard

Local telemetry for a D500 lidar, NEO-6M GPS, MPU6050 IMU and QMC5883L
magnetometer. A browser dashboard displays scans, GPS tracks, sensor readings
and acknowledged calibration controls. Requires Python 3.10+ and pyserial.

## Start

With `uv` installed:

```sh
uv sync --locked
uv run python -m robot.lidar --list-ports
uv run python -m robot.dashboard --port /dev/cu.usbserial-0001
```

On a Pi without `uv`, from the project directory:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install pyserial==3.5
.venv/bin/python -m robot.dashboard --host 0.0.0.0 --no-lidar
```

The last command serves the sensor page at `http://<pi-ip>:8765` without
probing motor ports. Add explicit sensor port options only after identifying
their devices. Start the separate motor control page with
`.venv/bin/python -m robot.drive --max-rpm 50` and open
`http://<pi-ip>:8766`. The two pages link to each other.

Open http://127.0.0.1:8765 for a local-only run. Select actual device ports; USB port names can change.
Optional devices use `--gps-port`, `--imu-port` and `--mag-port`. Run
`uv run python -m robot.dashboard --help` for baud rates and other options.
Stop with Ctrl+C. Close the dashboard before uploading firmware or opening a
serial monitor on the same port.

The lidar-only command can also record packets:

```sh
uv run python -m robot.lidar --port /dev/cu.usbserial-0001 --seconds 10 --output data/capture.jsonl
```

Recordings must use a new filename. Local recordings and screenshots are ignored
by Git. Calibration coefficients live in board EEPROM after an explicit save;
reorganizing project files does not change them.

## Layout

```text
robot/                 Python package: readers, calibration and HTTP server
web/                   Dashboard HTML, JavaScript and styles
firmware/              Independent Arduino sketch folders and protocol guide
  tests/               Native firmware tests and hardware stubs
tests/                 Python regression tests
docs/                  Detailed telemetry reference
artifacts/screenshots/ Local dashboard previews
data/                  Local sensor recordings
pyproject.toml         Python requirements
uv.lock                Locked dependencies
```

## Guides

- [Telemetry and command options](docs/telemetry.md)
- [Local joystick motor drive](docs/drive.md)
- [Pi service setup and verified port map](docs/pi-setup.md)
- [Firmware upload and calibration](firmware/README.md)
- [Serial protocol](firmware/PROTOCOL.md)

The scan is robot-relative, not SLAM. GPS course describes travel direction.
Compass calibration acceptance does not establish heading accuracy. Sensor
fusion and autonomous navigation are not implemented. Manual motor control is
available through the separate local drive server.

## Checks

```sh
uv run python -m unittest discover -s tests -t . -v
```

Firmware compile and native test commands are in the firmware guide. These checks
do not open physical serial ports.
