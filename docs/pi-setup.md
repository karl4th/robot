# Pi deployment

The service files in `deploy/` target a checkout at
`/home/robot/Documents/robot`. Install `pyserial==3.5` in that checkout's
virtual environment before starting the services.

The verified USB port map uses physical hub paths. If the hub topology changes,
recheck `/dev/serial/by-path/` and update the dashboard service. Drive ports
are selected and verified on the web setup page.

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
