# Pi deployment

The service files in `deploy/` target a checkout at
`/home/robot/Documents/robot`. Install `pyserial==3.5` in that checkout's
virtual environment before starting the services.

Ports are not configured by name. The service starts with `--auto-ports`: at
start it identifies each USB serial device by what it sends (lidar packets at
230400 baud, NMEA at 9600, `IMU1,`/`MAG1,` frames, `LSTAT,OK`/`RSTAT,OK` replies
to `STATUS` for the left and right motor boards) and then re-checks every 10 s
any sensor that is down, so a re-plugged or renumbered device is found again
without a restart. Healthy sensors and motor boards are never re-probed. A role
claimed by two ports is left unassigned and reported. Explicit `--port`,
`--gps-port`, `--imu-port` and `--mag-port` still override discovery, and
choosing ports in the Sensor connections panel switches auto mode off.

Check the current map without the dashboard (stop the service first, it holds
the ports): `.venv/bin/python -m robot.ports`.

The table is the map observed once on the bench; names and hub paths will change.

| Device | Observed port | Hub path suffix | Result |
| --- | --- | --- | --- |
| Left motor board | `/dev/ttyUSB1` | `1.3.1.3` | `LSTAT,OK` |
| Right motor board | `/dev/ttyUSB3` | `1.3.1.4` | `RSTAT,OK` |
| Lidar | `/dev/ttyUSB4` | `1.3.3` | Valid packets at 230400 baud |
| GPS | `/dev/ttyUSB2` | `1.3.4` | NMEA sentences at 9600 baud |
| IMU board | `/dev/ttyUSB0` | `1.3.2` | USB I/O error while opening |

The USB camera enumerates as `/dev/video0` but has not returned a frame in
either tested capture format. The control center service includes the verified
lidar and GPS, and runs motor controls in the same web server. It has a 50 RPM
ceiling and prints a new pairing code to its journal on every start. Browser
camera preview requires localhost or HTTPS and uses a camera attached to the
browser's computer.

After copying the service files to `/etc/systemd/system/`, run:

```sh
sudo systemctl daemon-reload
sudo systemctl disable --now robot-drive.service
sudo systemctl enable --now robot-dashboard.service
systemctl status robot-dashboard.service
journalctl -u robot-dashboard.service -b -n 20 --no-pager
```

Open `http://<pi-ip>:8765` for the unified controls and sensors. Use the pairing
code from the dashboard journal. Map tiles need internet. If a device stops
responding, inspect the service journal and `journalctl -k -b` for USB errors.
