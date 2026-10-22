import http.client
import json
import threading
import unittest
from unittest.mock import patch

from http.server import ThreadingHTTPServer
from pathlib import Path

from robot.drive import ConnectionCheckError, DriveController, make_handler, mix


class FakePort:
    def __init__(self, name, baud, timeout, write_timeout, reply=None):
        self.name = name
        self.writes = []
        self.closed = False
        self.reply = reply if reply is not None else (b'LSTAT,OK\n' if name == '/dev/left' else b'RSTAT,OK\n')
        self.pending = []

    def write(self, data):
        if self.closed:
            raise OSError("Port closed")
        self.writes.append(data.decode())
        if data == b'STATUS\n' and self.reply:
            self.pending.append(self.reply)
        return len(data)

    def readline(self):
        return self.pending.pop(0) if self.pending else b''

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

    def test_straight_corridor_keeps_both_sides_identical(self):
        self.controller.max_rpm = 50
        session = self.connect()
        for sequence, x in enumerate((-0.15, -0.05, 0, 0.05, 0.15), 1):
            self.assertEqual(self.controller.command(session, x, 1, sequence), [50, 50])
        self.assertEqual(self.controller.command(session, 0.1, -1, 6), [-50, -50])
        self.assertEqual(self.controller.command(session, 0.05, 0.05, 7), [0, 0])
        left, right = self.controller.command(session, 0.4, 1, 8)
        self.assertGreater(left, right)
        self.assertEqual(self.controller.command(session, 1, 0, 9), [50, -50])

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

    def test_sensor_reserved_port_never_opens_as_motor(self):
        self.controller.reserved_ports = {'/dev/left'}
        with self.assertRaisesRegex(ValueError, 'assigned to a sensor'):
            self.connect()
        self.assertEqual(self.opened, [])

    def test_swapped_boards_block_drive_and_show_both_replies(self):
        with self.assertRaises(ConnectionCheckError) as caught:
            self.controller.configure('/dev/right', '/dev/left')
        checks = caught.exception.checks
        self.assertEqual(checks['left']['response'], 'RSTAT,OK')
        self.assertEqual(checks['right']['response'], 'LSTAT,OK')
        self.assertFalse(self.controller.snapshot()['connected'])
        self.assertTrue(all(port.closed for port in self.opened))

    def test_silent_board_blocks_drive(self):
        self.controller.status_timeout = 0.02
        original_factory = self.controller.serial_factory

        def silent_right(*args, **kwargs):
            port = original_factory(*args, **kwargs)
            if port.name == '/dev/right':
                port.reply = b''
            return port

        self.controller.serial_factory = silent_right
        with self.assertRaises(ConnectionCheckError) as caught:
            self.connect()
        self.assertTrue(caught.exception.checks['left']['matched'])
        self.assertEqual(caught.exception.checks['right']['response'], 'No STATUS response')
        self.assertFalse(self.controller.snapshot()['connected'])

    def test_attached_legacy_replies_identify_sides_but_block_drive(self):
        original_factory = self.controller.serial_factory

        def legacy(*args, **kwargs):
            port = original_factory(*args, **kwargs)
            port.reply = b'L OK\n' if port.name == '/dev/left' else b'R OK\n'
            return port

        self.controller.serial_factory = legacy
        with self.assertRaises(ConnectionCheckError) as caught:
            self.connect()
        self.assertEqual(caught.exception.checks['left']['response'], 'L OK')
        self.assertEqual(caught.exception.checks['right']['response'], 'R OK')
        self.assertTrue(caught.exception.checks['left']['role_matched'])
        self.assertFalse(caught.exception.checks['left']['matched'])
        self.assertFalse(self.controller.snapshot()['connected'])

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
            self.assertIn(b'Board replies', page.read())
            conn.close()
            conn = http.client.HTTPConnection('127.0.0.1', server.server_port)
            conn.request('GET', '/drive')
            page = conn.getresponse()
            self.assertEqual(page.status, 200)
            self.assertIn(b'Drive', page.read())
            conn.close()
            status, _ = post('/api/connect', {'left': '/dev/left', 'right': '/dev/right', 'code': '123456'}, False)
            self.assertEqual(status, 403)
            status, _ = post('/api/connect', {'left': '/dev/left', 'right': '/dev/right', 'code': 'wrong'})
            self.assertEqual(status, 403)
            status, body = post('/api/connect', {'left': '/dev/right', 'right': '/dev/left', 'code': '123456'})
            self.assertEqual(status, 409)
            self.assertEqual(body['checks']['left']['response'], 'RSTAT,OK')
            self.assertEqual(body['checks']['right']['response'], 'LSTAT,OK')
            status, _ = post('/api/drive', {'session': 'none', 'x': 0, 'y': 1, 'sequence': 1})
            self.assertEqual(status, 400)
            status, body = post('/api/connect', {'left': '/dev/left', 'right': '/dev/right', 'code': '123456'})
            self.assertEqual(status, 200)
            session = body['session']
            self.assertEqual(body['checks']['left']['response'], 'LSTAT,OK')
            self.assertEqual(body['checks']['right']['response'], 'RSTAT,OK')
            status, body = post('/api/session', {'session': session})
            self.assertEqual(status, 200)
            self.assertEqual(body['left'], '/dev/left')
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
