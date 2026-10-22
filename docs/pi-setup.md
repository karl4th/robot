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
either tested capture format. The dashboard service therefore includes the
verified lidar and GPS only. The drive service has a 50 RPM ceiling and prints
a new pairing code to its journal on every start.

After copying the service files to `/etc/systemd/system/`, run:

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now robot-dashboard.service robot-drive.service
systemctl status robot-dashboard.service robot-drive.service
journalctl -u robot-drive.service -b -n 20 --no-pager
```

Open `http://<pi-ip>:8765` for sensors and `http://<pi-ip>:8766` for drive
controls. Use the pairing code from the drive journal. If a device stops
responding, inspect the service journal and `journalctl -k -b` for USB errors.
