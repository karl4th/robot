# Sensor serial protocol v1

Transport: 115200 baud, 8N1, no flow control. One ASCII frame per line. Receivers
accept CRLF or LF. All numeric fields are base-10 integers. Maximum frame length
is 240 bytes excluding the line ending. CRC is mandatory for versioned frames.

```text
IMU1,seq,ms,flags,ax,ay,az,temp,gx,gy,gz,ax_mg,ay_mg,az_mg,gx_mdps,gy_mdps,gz_mdps*HHHH
MAG1,seq,ms,flags,mx,my,mz,mx_nT,my_nT,mz_nT*HHHH
```

- CRC-16/CCITT-FALSE: polynomial 0x1021, init 0xFFFF, no reflection, xorout 0.
  Calculate over ASCII bytes from the first tag character up to but excluding
  `*`. Four hexadecimal digits follow it. Check vector `123456789` -> `29B1`.
- `seq`: unsigned 32-bit emitted-sample counter. Starts at zero on boot, wraps.
- `ms`: unsigned 32-bit board milliseconds captured during the successful read
  cycle. Wraps after about 49.7 days; it is not UTC or a synchronized sensor clock.
- Raw fields: signed 16-bit acquisition counts. Endpoint clipping is rejected
  in firmware. Raw MPU order is accel XYZ, temperature, gyro XYZ. Raw magnetic
  order is XYZ. The scalar values are textual, independent of sensor endianness.
- IMU corrected acceleration: milli-g, including gravity. Corrected angular rate:
  milli-degrees/second. Gyro bias is subtracted; accel bias and gain applied.
- Temperature: raw sensor value, degrees C = raw / 340 + 36.53.
- MAG corrected field: nanotesla; bias and diagonal gain are applied in counts
  before multiplying by 100000/3000 for the fixed +/-8 gauss configuration.
- Corrected values may exceed signed 16-bit range. The PC validates them as
  bounded integers and converts to g, degrees/s and microtesla without applying
  calibration a second time.

## Flags

| Bit value | IMU1 | MAG1 |
| --- | --- | --- |
| 1 | Configuration written/read back: +/-2 g, +/-250 deg/s, 50 Hz | Configuration written/read back: +/-8 G, 50 Hz |
| 2 | Gyro bias correction applied | Magnetic offset and diagonal gain applied |
| 4 | Accelerometer bias/gain correction applied | Reserved, must be zero |
| 8 | Calibration capture active; previous accepted correction remains active | Same |
| 16 | Reserved, must be zero | Sensor reports data-overrun; intervening conversions lost |

Configuration bit 1 must be set. Reserved bits are rejected by the PC. Calibration
bits describe **accepted RAM coefficients**, not whether they were saved or
whether navigation-level accuracy has been independently validated. `STATUS`
reports coefficients; `#OK,SAVED` confirms explicit EEPROM persistence.

Diagnostics start with `#BOOT`, `#STATUS`, `#COEFF`, `#CAL`, `#OK`, `#HELP` or
`#ERR`. They have no CRC and never count as measurement freshness. Calibration
commands are newline-terminated input from either Serial Monitor or the web
calibration wizard through the owning serial reader. The old `IMU,...`, `MAG,...` and human-readable formats remain
supported but lack these integrity, acquisition and calibration guarantees.

Sequence and device time are exposed for inspection. The dashboard currently
uses host receive time for freshness, not clock synchronization or dead reckoning.
Firmware errors stop sample output; the desktop marks data stale after one
second. This does not provide authentication, hard real-time guarantees or
protection against a sender deliberately replaying CRC-valid frames.
