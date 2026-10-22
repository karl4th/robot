# Local motor drive

The setup page identifies two serial motor boards before the separate drive
page accepts movement commands. Both pages are available from a phone or
computer on the same local network.

## Start on the Pi 4

From the directory containing `pyproject.toml`, install Python 3.10+ and the
single runtime dependency, then run:

```sh
cd ~/Documents/manifestro/robot
python3 -m venv .venv
.venv/bin/python -m pip install pyserial==3.5
.venv/bin/python -m robot.drive --max-rpm 50
```

Adjust the `cd` path if the project was copied elsewhere. If `venv` is missing,
install the system's `python3-venv` package first. Find the Pi's local IP
address with `hostname -I`. Open `http://<pi-ip>:8766` on a phone or computer
on the same network. The terminal prints a six-digit pairing code. Enter it on
the setup page, choose the left and right USB serial ports, then press **Check
and connect**. The page shows the reply from each selected port and only
enables **Open drive controls** when the left port returns `LSTAT,OK` and the
right port returns `RSTAT,OK`. A silent, swapped, or incorrectly programmed
board remains disconnected. Refresh the port list after plugging in a board.
Stable `/dev/serial/by-id/...` names are preferred when available.

Both motor boards must run their matching firmware from `firmware/motors_left`
and `firmware/motors_right`. This server sends their `rpm,0` protocol at 115200
baud. The right firmware already reverses its motor command. Use the side
reversal checkboxes only if the physical wheel direction needs correction.

The default speed ceiling is 200 RPM. The command above starts with a lower
50 RPM limit. Check the actual wheel direction with the robot raised and the
drive clear of people. Hold the joystick to move and release it to stop. The
large **STOP** button also sends zero speed. The server sends zero speed after
300 ms without a fresh joystick command; the firmware has its own 200 ms
command timeout. These are software safeguards, not a physical emergency stop.

Only one browser session controls the selected ports at a time. Connecting
again replaces that session and sends zero speed first. Closing the server
also sends zero speed. Use this HTTP server only on a trusted local network;
the pairing code is shown in the Pi terminal and HTTP traffic is unencrypted.
Motor power, the CAN interface, serial access permissions, and the physical
emergency stop must be set up separately. Real motor behavior has not been
validated by this project's automated tests.
