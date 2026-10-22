# Firmware and calibration

## Sensor sketches

Two independent sensor sketches for classic Nano / Uno boards with ATmega328P. Each
board owns one sensor. Keep each `.ino` together with its local
`SensorSupport.h`; the two support headers are intentionally identical so either
folder opens independently in the IDE. No third-party sensor library is needed.
Required built-in libraries: Wire (with timeout functions) and EEPROM.

## Open and upload

1. Open `mpu6050_calibration/mpu6050_calibration.ino` for the IMU board or
   `qmc5883l_calibration/qmc5883l_calibration.ino` for the magnetic sensor board.
2. Select the actual Nano or Uno board and its ATmega328P processor. Some Nano
   boards need the old bootloader upload option; select it only for that board.
3. Stop the local dashboard with Ctrl+C before opening Serial Monitor or
   uploading. One serial port must have only one owner. Uploading can reset a
   board. No upload is performed by the desktop reader.
4. Select the matching port. Previously observed: IMU `/dev/cu.usbserial-112120`,
   magnetic sensor `/dev/cu.usbserial-112140`. Port names can change; verify them
   in the IDE before uploading. Do not select the GPS or lidar port.
5. Upload only after confirming board and port. Open Serial Monitor at **115200**
   baud, with **Newline** or **Both NL & CR** line endings.
6. Send `STATUS`. Check configuration success and absence of repeated `#ERR`
   messages. A board reset retains only calibration explicitly saved to EEPROM.

Both boards use SDA=A4 and SCL=A5 with a common ground. The expected I2C addresses
are 0x68 for MPU6050 (AD0 low; edit `ADDRESS` for 0x69) and 0x0D for QMC5883L.
Use the supply and I2C voltage limits of the actual breakout. Bare sensors are
not 5 V parts; the presence of a regulator does not imply I2C level shifting.
This firmware does not target HMC5883L, QMC5883P, or other similarly named chips.
The ID checks reject unexpected values but do not authenticate a chip.

## Calibrate from the web panel (recommended)

After uploading the sketches, close Serial Monitor and start the dashboard with
both sensor ports. Click **Calibrate** on the MPU6050 or QMC5883L card.

- MPU6050: Start calibration, capture the still gyro, then follow the six sensor
  face prompts one at a time. Each face advances only after board acceptance.
- QMC5883L: Start calibration, rotate around all three axes for the capture,
  and wait for the board to accept the fit.
- Click **Save & continue** when offered. Success is shown only after `#OK,SAVED`.
  Telemetry stays active; no dashboard restart or Serial Monitor is needed.
- **Cancel capture** sends `ABORT`. It stops capture and retains any previously
  accepted RAM corrections, without writing EEPROM. It is not a rollback.
- A failed capture can be restarted. A page refresh preserves progress while
  the server remains running. Server restart/disconnection does not replay
  commands. Close this dialog to view live measurements at any time.

The browser offers controls only with fresh versioned sensor data. Legacy
firmware cannot be calibrated through this workflow. Progress time is estimated;
completion is based on device replies, not the timer. Actual calibration still
requires physically holding or rotating the sensors as instructed. Commands run
through the existing serial owner, so no second connection or port switch occurs.

The Serial Monitor instructions below remain an optional manual alternative.

## Command behavior

Commands are case-sensitive. Diagnostic lines start with `#`; measurement lines
start with `IMU1` or `MAG1`. Measurement streaming continues during calibration,
with an active-calibration flag and the previously accepted corrections.
Serial Monitor may be easier to read with autoscroll disabled while entering a
command. Do not interpret streaming numeric lines as acceptance messages.

| Command | Behavior |
| --- | --- |
| `HELP` | List commands supported by that sketch. |
| `STATUS` | Print configuration, calibration flags, progress and coefficients. |
| `ABORT` | Cancel capture; retain previously accepted coefficients. IMU also clears unfinished faces. |
| `SAVE` | Explicitly persist accepted RAM coefficients with version, sensor-specific magic and CRC16. |
| `RESET` | Restore identity corrections in RAM. Send `SAVE` separately to persist the reset. |

`SAVE` is rejected during capture. A failed capture never replaces the previous
calibration. An interrupted EEPROM write invalidates the record; next boot uses
identity corrections and reports `#BOOT,DEFAULT_CAL`. The single record occupies
EEPROM from address zero. It does not preserve another sketch's EEPROM contents.
Do not repeatedly issue `SAVE` in a loop. It is not needed after every reboot.

## MPU6050: gyro bias and six-face accelerometer calibration

Configuration: +/-2 g, +/-250 degrees/s, PLL X gyro clock, DLPF setting 3
(approximately 44 Hz acceleration / 42 Hz gyro), 50 Hz device sampling and
reporting. Registers are written and read back; a periodic check detects changes.
Acquisition requires data-ready and a successful 14-byte burst. Endpoint-clipped
samples, I2C failures and missing fresh data abort a capture. These gates are not
a substitute for physically keeping the sensor still.

Let the sensor reach a stable temperature before calibration. Calibrate in its
final mounting whenever practical. Keep motors off and avoid vibration.

### Gyroscope

1. Put the board on a stable surface. Any fixed orientation is acceptable.
2. Send `CAL GYRO`.
3. After `#CAL,SETTLE_2S_THEN_HOLD_STILL_4S`, do not move it for at least six seconds.
4. Wait for `#CAL,GYRO_ACCEPTED_RAM,SAVE_REQUIRED`. A motion/noise error means
   repeat the capture, not proceed to saving.
5. Send `STATUS`. Gyro calibration sets flag bit 1 (numeric value 2).

The routine averages 200 fresh samples after a two-second settling period. It
rejects excessive sample variation, mean angular rate, and implausible gravity.
A constant slow rotation can evade a variance check: stillness is a physical
requirement. Bias is temperature-dependent; this is not temperature compensation.

### Accelerometer

1. Send `CAL ACCEL RESET` to clear unfinished face captures.
2. Put the indicated **sensor axis pointing upward**, then send the corresponding
   command. Positive-axis-up means positive acceleration near +1 g on that axis.
3. Keep still for six seconds per face. Wait for `#CAL,FACE_ACCEPTED,MASK=...`
   before repositioning. Read the sensor/module axis markings, not robot axes.

```text
CAL ACCEL +X
CAL ACCEL -X
CAL ACCEL +Y
CAL ACCEL -Y
CAL ACCEL +Z
CAL ACCEL -Z
```

These are six separate captures, not a block to paste at once. A face must have
its dominant signed axis within 0.8-1.2 g and other axes within +/-0.15 g.
After all six faces pass, expect `#CAL,ACCEL_ACCEPTED_RAM,SAVE_REQUIRED`.
The routine fits per-axis bias and gain, without cross-axis or mounting rotation
correction. Failed faces can be retried. Bus failures or `ABORT` clear unfinished
faces; previously accepted coefficients remain active.

Send `STATUS`, then `SAVE`; expect `#OK,SAVED`. Flags value 6 means both gyro and
accelerometer corrections are present. After reboot, `#BOOT,EEPROM_CAL_LOADED`
and `STATUS` should show the same coefficients. Check all six positions again:
one acceleration axis should be near +/-1 g, others near zero, total norm near
1 g; gyro should be near zero at rest. Choose acceptance tolerances for the
robot's actual requirements instead of assuming factory accuracy.

## QMC5883L: magnetic offset and diagonal scale calibration

Configuration: +/-8 gauss, OSR 512, continuous 50 Hz, set/reset period 0x01.
The sketch reads data-ready and overflow status before reading XYZ. Overflow
and I2C faults abort capture. Data-overrun is reported in the frame flags: the
newest sample is usable but intervening conversions were not read.

1. Keep the installed sensor away from temporary magnets, tools and the laptop.
   Use the final mounting and a repeatable electrical environment. Moving metal
   or changing motor currents can invalidate the result later.
2. Send `CAL START`.
3. For 60 seconds, rotate slowly through complete turns around **all three axes**.
   Include inverted positions. A flat circle on the table is insufficient.
4. The routine stops automatically after 60 seconds. Early `CAL STOP` is rejected
   as incomplete. `ABORT` retains the previous calibration.
5. Accept only `#CAL,MAG_ACCEPTED_RAM,RMS=...,SAVE_REQUIRED`, then send `STATUS`
   and `SAVE`. Failed coverage/distortion/residual checks require a new capture.

This is a bounded-memory min/max hard-iron offset plus **diagonal** scale fit.
It checks sample count, three-axis span, all eight centered octants, gain limits
and normalized radius RMS <=0.15 over 96 time bins spanning the full minute.
Each 625 ms bin retains its first sample; later samples cannot evict early ones.
All bins must contain data. Extrema still use every acquired sample.
`CAL_COVERAGE` and `CAL_RESIDUAL` separately report the octant count/mask and
measured RMS alongside the unchanged 0.15 limit. Continue rotating throughout.
The fit does not estimate a full 3x3 soft-iron matrix. Coverage checks reduce bad
fits but do not establish absolute heading or field-strength accuracy.

After reboot, verify coefficients persist, rotate through another independent
set of orientations, and check that corrected field magnitude stays reasonably
consistent. Compare direction against an independent reference at several
headings, with the sensor level. The panel displays `atan2(Y, X)` in sensor axes;
mounting alignment, tilt compensation and magnetic declination remain separate
steps. Do not use the displayed angle as robot yaw or true north yet.

## Protocol and dashboard

Both sketches use a project-specific, versioned ASCII protocol documented in
[PROTOCOL.md](PROTOCOL.md). It is not a claim of compliance with an industry
navigation standard. Each sample carries sequence, device milliseconds, status,
raw counts, corrected fixed-point values and CRC16. Only a successful fresh
acquisition produces a sample; errors produce diagnostic lines instead.
Configuration flags are firmware-reported, not independently measured by the PC.

Close Serial Monitor before restarting the dashboard:

```sh
uv run python -m robot.dashboard --port /dev/cu.usbserial-0001 --gps-port /dev/cu.usbserial-112110 --imu-port /dev/cu.usbserial-112120 --imu-baud 115200 --mag-port /dev/cu.usbserial-112140 --mag-baud 115200
```

Do not force 115200 until both boards have the new sketches. Without explicit
baud options the readers still support the existing legacy firmware. Old frames
remain labeled as assumed/uncalibrated. New frames use firmware-corrected units
and display which correction flags are set. Calibration does not automatically
suppress GPS drift or fuse clocks, position, compass and IMU measurements.

## Local checks and evidence limits

```sh
uv run python -m unittest discover -s tests -t . -v
arduino-cli compile --fqbn arduino:avr:uno firmware/mpu6050_calibration
arduino-cli compile --fqbn arduino:avr:uno firmware/qmc5883l_calibration
arduino-cli compile --fqbn arduino:avr:nano:cpu=atmega328 firmware/mpu6050_calibration
arduino-cli compile --fqbn arduino:avr:nano:cpu=atmega328 firmware/qmc5883l_calibration
c++ -std=c++11 -D__AVR_ATmega328P__ -Ifirmware/tests/stubs firmware/tests/imu_calibration.cpp -o /tmp/imu-cal-test
/tmp/imu-cal-test
c++ -std=c++11 -D__AVR_ATmega328P__ -Ifirmware/tests/stubs firmware/tests/mag_calibration.cpp -o /tmp/mag-cal-test
/tmp/mag-cal-test
```

The native harness tests the sketch calibration functions with synthetic data,
EEPROM corruption and failed I2C stubs. It does not simulate physical sensors,
AVR timing or EEPROM power failures. Firmware compilation and parser tests do
not prove upload, physical calibration, heading accuracy or stable operation on
the boards. Those require the hands-on captures and independent checks above.

### MPU6050 acquisition diagnostics

Fast repositioning can saturate the configured gyro range. Saturated samples
between captures are discarded without resetting the sensor or accepted faces.
Saturation during capture reports `IMU_SATURATION,CAPTURE_ABORTED`; repeat the
current capture with the sensor stationary. It is not reported as a bus timeout.
Actual failures report `IMU_CONFIG_CHECK_FAILED`, `IMU_STATUS_READ_FAILED`,
`IMU_SAMPLE_READ_FAILED`, or `IMU_DATA_READY_TIMEOUT`. These still abort the
session and trigger sensor reinitialization. Upload the updated sketch to apply
this behavior; changing the Python server alone does not update the board.

Rejected MPU6050 captures can be retried at the same wizard step without
clearing previously accepted faces. Hardware faults and board restarts still
require a new session. Noise rejection reports the axis, measured raw-count
standard deviation and limit (`CAL_ACCEL_NOISE` or `CAL_GYRO_NOISE`).
`CAL_GYRO_BIAS` reports the absolute raw mean instead. Limits remain unchanged;
the wizard never treats a rejected capture as accepted.

## Motor sketches

The supplied motor sketches are stored separately for each side:

- [Left motors](motors_left/motors_left.ino)
- [Right motors](motors_right/motors_right.ino)

Open the matching `.ino` in its own folder. Both require SPI and an installed
`mcp_can.h` library compatible with the supplied API. They select CS pin 10,
500 kbit/s CAN and an 8 MHz controller oscillator. Board and library compatibility
has not been validated by compilation or hardware testing.

Serial runs at 115200 baud. Commands are newline-terminated `rpm,brake` or
`STATUS`. Status responses are `LSTAT,OK` and `RSTAT,OK`; feedback is
`LFB,rpm1,rpm2,byte0,byte1,voltage` or the corresponding `RFB` line.
The right sketch negates the requested RPM before transmission.

Both sketches use extended command ID `0x1801E600` and feedback ID `0x1801E001`;
these IDs do not distinguish left from right on a shared bus. Commands transmit
every 50 ms. After 200 ms without a parsed RPM command, the original logic sets
RPM to zero and clears the brake flag. This is preserved source behavior, not
a verified physical braking guarantee. Motor control is not connected to the
Python dashboard.
