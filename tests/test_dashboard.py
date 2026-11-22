import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from robot.dashboard import ScanState, SensorHub


class ScanStateTests(unittest.TestCase):
    def test_stale_returns_are_removed(self):
        state = ScanState()
        now = time.monotonic()
        state.last = now
        state.error = ''
        state.samples.extend([(now-1, 90, 1000, 80), (now, 0, 2000, 90)])
        self.assertEqual(state.snapshot()['points'], [(0, 2000, 90)])
        state.last = now-2
        self.assertFalse(state.snapshot()['live'])
        self.assertEqual(state.snapshot()['points'], [])

    def test_error_hides_recent_points(self):
        state = ScanState()
        state.last = time.monotonic()
        state.samples.append((state.last, 0, 1000, 90))
        state.error = 'Disconnected'
        self.assertEqual(state.snapshot()['points'], [])
        self.assertFalse(state.snapshot()['live'])


class SensorHubTests(unittest.TestCase):
    def test_duplicate_or_motor_port_is_rejected_before_restarting_readers(self):
        args = SimpleNamespace(no_lidar=True, port=None, gps_port=None, imu_port=None,
                               mag_port=None, imu_accel_range=2, imu_gyro_range=250,
                               mag_range=8, gps_baud=9600, imu_baud=None, mag_baud=None)
        hub = SensorHub(args)
        ports = [SimpleNamespace(device='/dev/lidar', description='Lidar'),
                 SimpleNamespace(device='/dev/motor', description='Motor')]
        with patch('robot.dashboard.list_ports.comports', return_value=ports):
            with self.assertRaisesRegex(ValueError, 'different port'):
                hub.configure({'lidar': '/dev/lidar', 'gps': '/dev/lidar',
                               'imu': None, 'mag': None}, ())
            with self.assertRaisesRegex(ValueError, 'motor board'):
                hub.configure({'lidar': '/dev/motor', 'gps': None,
                               'imu': None, 'mag': None}, ('/dev/motor', None))
        self.assertEqual(hub.ports, {'lidar': None, 'gps': None, 'imu': None, 'mag': None})
        hub.close()


class AutoPortsTests(unittest.TestCase):
    def hub(self):
        args = SimpleNamespace(no_lidar=False, port=None, gps_port='/dev/old-gps', imu_port=None,
                               mag_port=None, imu_accel_range=2, imu_gyro_range=250,
                               mag_range=8, gps_baud=9600, imu_baud=None, mag_baud=None,
                               auto_ports=True, discovered={'/dev/motor': 'left'})
        with patch('robot.dashboard.read_sensor'), patch('robot.dashboard.read_gps'), \
                patch('robot.dashboard.read_imu'), patch('robot.dashboard.read_mag'):
            hub = SensorHub(args)
        hub.motor_ports = lambda: ['/dev/motor2']
        return hub

    def test_replugged_sensors_are_found_under_new_names_and_missing_ones_started(self):
        hub = self.hub()
        report = {'roles': {'gps': '/dev/ttyUSB7', 'imu': '/dev/ttyUSB5', 'lidar': '/dev/ttyUSB6'},
                  'ports': {'/dev/ttyUSB7': {'role': 'gps'}, '/dev/ttyUSB5': {'role': 'imu'},
                            '/dev/ttyUSB6': {'role': 'lidar'}}, 'conflicts': {}}
        with patch('robot.dashboard.discover', return_value=report) as found, \
                patch('robot.dashboard.read_imu'):
            roles = hub.rediscover()
        self.assertEqual(roles, report['roles'])
        self.assertEqual(hub.gps.port, '/dev/ttyUSB7')
        self.assertEqual(hub.imu.port, '/dev/ttyUSB5')
        self.assertEqual(hub.scan.hint, '/dev/ttyUSB6')
        self.assertEqual(hub.ports['gps'], '/dev/ttyUSB7')
        # motor boards, known or connected, are never probed
        self.assertCountEqual(found.call_args.kwargs['skip'], ['/dev/motor', '/dev/motor2'])
        hub.close()

    def test_manual_setup_ends_auto_mode(self):
        hub = self.hub()
        ports = [SimpleNamespace(device='/dev/x', description='x')]
        with patch('robot.dashboard.list_ports.comports', return_value=ports), \
                patch('robot.dashboard.read_gps'), patch('robot.dashboard.read_sensor'):
            hub.configure({'lidar': None, 'gps': '/dev/x', 'imu': None, 'mag': None}, ())
        self.assertFalse(hub.auto)
        with patch('robot.dashboard.discover') as found:
            self.assertEqual(hub.rediscover(), {})
        found.assert_not_called()
        hub.close()
