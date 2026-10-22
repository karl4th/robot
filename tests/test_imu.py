import unittest
from robot.imu import IMUState, parse_imu


class IMUTests(unittest.TestCase):
    def test_csv_order_and_temperature(self):
        state = IMUState('test')
        self.assertTrue(state.ingest(b'IMU,0,0,16384,340,131,-262,0\r\n', now=10))
        sample = state.snapshot(now=10)['sample']
        self.assertEqual(sample['accel_g'], [0, 0, 1])
        self.assertEqual(sample['gyro_dps'], [1, -2, 0])
        self.assertAlmostEqual(sample['temperature_c'], 37.53)
        self.assertEqual(sample['roll_deg'], 0)
        self.assertEqual(sample['pitch_deg'], 0)

    def test_legacy_has_no_temperature(self):
        sample = parse_imu(b'Acc: X=948 Y=-16140 Z=1952 | Gyr: X=3 Y=-201 Z=-14')
        self.assertEqual(sample['accel_raw'], [948, -16140, 1952])
        self.assertEqual(sample['gyro_raw'], [3, -201, -14])
        self.assertIsNone(sample['temp_raw'])
        self.assertEqual(sample['format'], 'legacy')

    def test_invalid_frames(self):
        for raw in (b'IMU,1,2,3', b'IMU,1,2,3,4,5,6,32768', b'IMU,1,2,3,nan,0,0,0',
                    b'IMU,0,0,0,0,0,0,0', b'IMU,-1,-1,-1,-1,-1,-1,-1', b'\xff'):
            state = IMUState('test')
            self.assertFalse(state.ingest(raw, now=10))
            self.assertIsNone(state.snapshot(now=10)['sample'])
        self.assertIsNone(parse_imu(b'# IMU ready'))

    def test_stale_and_disconnected(self):
        state = IMUState('test')
        state.ingest(b'IMU,0,0,16384,0,0,0,0', now=10)
        self.assertEqual(state.snapshot(now=10)['status'], 'live')
        self.assertIsNone(state.snapshot(now=11.1)['sample'])
        state.disconnected('Cable disconnected')
        self.assertIsNone(state.snapshot(now=10.1)['sample'])

    def test_rate_and_gap(self):
        state = IMUState('test')
        for t in (10, 10.1, 10.2):
            state.ingest(b'IMU,0,0,16384,0,0,0,0', now=t)
        self.assertAlmostEqual(state.snapshot(now=10.3)['hz'], 10)
        state.ingest(b'IMU,0,0,16384,0,0,0,0', now=15)
        self.assertIsNone(state.snapshot(now=15)['hz'])

    def test_tilt_and_dynamic_gate(self):
        state = IMUState('test')
        state.ingest(b'IMU,0,-16384,0,0,0,0,0', now=10)
        self.assertEqual(state.snapshot(now=10)['sample']['roll_deg'], -90)
        state.ingest(b'IMU,0,0,30000,0,0,0,0', now=11)
        self.assertIsNone(state.snapshot(now=11)['sample']['roll_deg'])

    def test_explicit_scale_override(self):
        state = IMUState('test', accel_range=4, gyro_range=500)
        state.ingest(b'IMU,0,0,8192,-340,131,0,0', now=10)
        sample = state.snapshot(now=10)['sample']
        self.assertEqual(sample['accel_g'], [0, 0, 1])
        self.assertEqual(sample['gyro_dps'], [2, 0, 0])
        self.assertAlmostEqual(sample['temperature_c'], 35.53)

    def test_reader_keeps_port_open_during_init_errors(self):
        import threading
        from unittest.mock import patch
        from robot.imu import read_imu
        state=IMUState('fake');stop=threading.Event();clock=[100.0]
        class Port:
            def __init__(self):self.reads=0
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,n):
                self.reads+=1;clock[0]+=2
                if self.reads==5:stop.set()
                return b'#ERR,IMU_INIT\n'
        port=Port()
        with patch('robot.imu.serial.Serial',return_value=port) as constructor, patch('robot.imu.time.monotonic',side_effect=lambda:clock[0]):
            read_imu(state,115200,stop)
        self.assertEqual(constructor.call_count,1)
        self.assertEqual(state.samples,0)
        self.assertEqual(state.error,'IMU_INIT')
