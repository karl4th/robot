import http.client
import json
import threading
import unittest
from unittest.mock import patch

from http.server import ThreadingHTTPServer
from pathlib import Path

from robot.drive import DriveController, make_handler, mix


class FakePort:
    def __init__(self, name, baud, timeout, write_timeout):
        self.name = name
        self.writes = []
        self.closed = False

    def write(self, data):
        if self.closed:
            raise OSError("Port closed")
        self.writes.append(data.decode())
        return len(data)

    def close(self):
        self.closed = True


class DriveTests(unittest.TestCase):
    def setUp(self):
        self.now = 10.0
        self.opened = []

        def open_port(*args, **kwargs):
            port = FakePort(*args, **kwargs)
            self.opened.append(port)
            return port

        self.controller = DriveController(200, serial_factory=open_port, clock=lambda: self.now)
        self.port_patch = patch.object(self.controller, 'available_ports', return_value=[
            {'device': '/dev/left', 'description': 'Left board'},
            {'device': '/dev/right', 'description': 'Right board'}])
        self.port_patch.start()

    def tearDown(self):
        self.controller.close()
        self.port_patch.stop()

    def connect(self):
        return self.controller.configure('/dev/left', '/dev/right')

    def test_mix_and_sequence_prevent_late_motion(self):
        session = self.connect()
        self.assertEqual(mix(0, 1), (1, 1))
        self.assertEqual(mix(1, 0), (1, -1))
        self.assertEqual(self.controller.command(session, 0, 1, 1), [200, 200])
        self.controller.halt(session, 3)
        self.assertEqual(self.controller.command(session, 0, 1, 2), [0, 0])
        self.assertEqual(self.opened[0].writes[-1], '0,0\n')
        self.assertEqual(self.opened[1].writes[-1], '0,0\n')

    def test_watchdog_and_disconnect(self):
        session = self.connect()
        self.controller.command(session, 0, -1, 1)
        self.now += 0.31
        self.controller.tick()
        self.assertEqual(self.controller.snapshot()['target'], [0, 0])
        self.assertEqual(self.opened[0].writes[-1], '0,0\n')
        self.controller.close()
        self.assertTrue(all(port.closed for port in self.opened))

    def test_invalid_or_duplicate_ports_never_open(self):
        for left, right in [('/dev/left', '/dev/left'), ('/dev/other', '/dev/right')]:
            with self.assertRaises(ValueError):
                self.controller.configure(left, right)
        self.assertEqual(self.opened, [])

    def test_http_pairing_and_drive(self):
        root = Path(__file__).resolve().parent.parent / 'web'
        server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(self.controller, '123456', root))
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        host = f'127.0.0.1:{server.server_port}'

        def post(path, body, origin=True):
            conn = http.client.HTTPConnection('127.0.0.1', server.server_port)
            headers = {'Content-Type': 'application/json'}
            if origin:
                headers['Origin'] = f'http://{host}'
            conn.request('POST', path, json.dumps(body), headers)
            response = conn.getresponse()
            result = response.status, json.loads(response.read())
            conn.close()
            return result

        try:
            conn = http.client.HTTPConnection('127.0.0.1', server.server_port)
            conn.request('GET', '/')
            page = conn.getresponse()
            self.assertEqual(page.status, 200)
            self.assertIn(b'Drive', page.read())
            conn.close()
            status, _ = post('/api/connect', {'left': '/dev/left', 'right': '/dev/right', 'code': '123456'}, False)
            self.assertEqual(status, 403)
            status, _ = post('/api/connect', {'left': '/dev/left', 'right': '/dev/right', 'code': 'wrong'})
            self.assertEqual(status, 403)
            status, body = post('/api/connect', {'left': '/dev/left', 'right': '/dev/right', 'code': '123456'})
            self.assertEqual(status, 200)
            session = body['session']
            status, body = post('/api/drive', {'session': session, 'x': 0, 'y': 1, 'sequence': 1})
            self.assertEqual((status, body['target']), (200, [200, 200]))
            status, body = post('/api/stop', {'session': session, 'sequence': 2})
            self.assertEqual((status, body['target']), (200, [0, 0]))
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=1)


if __name__ == '__main__':
    unittest.main()
