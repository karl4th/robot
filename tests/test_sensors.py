import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import urlopen

from robot.gps import GPSState
from robot.imu import IMUState
from robot.sensors import PAGE, make_handler


class ReadingsPageTests(unittest.TestCase):
    def setUp(self):
        self.gps = GPSState("/dev/ttyAMA5")
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(None, self.gps, IMUState("/dev/i2c-1@0x68")))
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def test_page_and_readings_are_served_read_only(self):
        with urlopen(self.base + "/") as response:
            self.assertEqual(response.read(), PAGE.read_bytes())
        with urlopen(self.base + "/api/readings") as response:
            data = json.loads(response.read())
        self.assertIsNone(data["lidar"])
        self.assertEqual(data["gps"]["port"], "/dev/ttyAMA5")
        self.assertEqual(data["imu"]["status"], "offline")
        with self.assertRaises(HTTPError) as error:
            urlopen(self.base + "/api/drive", data=b"{}")
        self.assertIn(error.exception.code, (404, 501))


if __name__ == "__main__":
    unittest.main()
