# Mac USB setup

On the inspected Mac, the following USB serial adapters were identified and
their data streams checked. Port names can change after reconnecting the hub.

| Role | Observed port | Live result |
| --- | --- | --- |
| Left motor board | `/dev/cu.usbserial-112130` | `LSTAT,OK`; zero RPM accepted |
| Right motor board | `/dev/cu.usbserial-112140` | `RSTAT,OK`; zero RPM accepted |
| Lidar | `/dev/cu.usbserial-0001` | Valid packets at 230400 baud |
| GPS | `/dev/cu.usbserial-11240` | NMEA at 9600 baud |
| IMU | `/dev/cu.usbserial-11220` | `IMU1` at 115200 baud |
| Compass | `/dev/cu.usbserial-112120` | `MAG1` at 115200 baud |

Run the control center from the project directory:

```sh
.venv/bin/python -m robot.dashboard --port /dev/cu.usbserial-0001 \
  --gps-port /dev/cu.usbserial-11240 \
  --imu-port /dev/cu.usbserial-11220 \
  --mag-port /dev/cu.usbserial-112120 \
  --max-rpm 50
```

Open `http://127.0.0.1:8765`. The server prints a new six-digit pairing code
at startup. Choose the two motor ports in Drive controls. Sensor ports can be
changed on the same page; applying them stops and restarts their readers.

The browser map uses online map tiles and shows a local track when tiles are
unavailable. A weak GPS fix can drift while the receiver is stationary. Camera
preview requires browser permission on localhost or HTTPS. The inspected Mac
did not enumerate the external USB camera; only its built-in and phone cameras
were available to the browser. No wheel movement test has been performed.
