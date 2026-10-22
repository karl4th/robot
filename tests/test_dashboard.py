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
