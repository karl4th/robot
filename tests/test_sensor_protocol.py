import binascii
import unittest
from robot.imu import IMUState, parse_imu
from robot.magnetometer import MagState, parse_mag
from robot.sensor_protocol import decode_frame


def frame(body):
    return f'{body}*{binascii.crc_hqx(body.encode(), 0xFFFF):04X}'.encode()


IMU = 'IMU1,1,20,7,100,200,16000,340,131,262,-131,0,0,1000,0,0,0'
MAG = 'MAG1,1,20,3,3000,0,0,0,100000,0'


class VersionedProtocolTests(unittest.TestCase):
    def test_crc_reference(self):
        self.assertEqual(binascii.crc_hqx(b'123456789', 0xFFFF), 0x29B1)

    def test_corrected_imu_units_are_not_rescaled(self):
        state = IMUState('test', 16, 2000)
        self.assertTrue(state.ingest(frame(IMU), now=10))
        result = state.snapshot(now=10)
        self.assertTrue(result['scales_verified'])
        self.assertEqual(result['accel_range'], 2)
        self.assertEqual(result['sample']['accel_raw'], [100,200,16000])
        self.assertEqual(result['sample']['accel_g'], [0,0,1])
        self.assertEqual(result['sample']['gyro_dps'], [0,0,0])
        self.assertEqual(result['sample']['sequence'], 1)
        self.assertAlmostEqual(result['sample']['temperature_c'], 37.53)

    def test_mag_uses_corrected_vector_for_angle(self):
        state = MagState('test', 2)
        self.assertTrue(state.ingest(frame(MAG), now=10))
        result = state.snapshot(now=10)
        self.assertEqual(result['field_range'], 8)
        self.assertTrue(result['calibrated'])
        self.assertEqual(result['sample']['angle_deg'], 90)
        self.assertEqual(result['sample']['raw'], [3000,0,0])
        self.assertEqual(result['sample']['field_ut'], [0,100,0])

    def test_corruption_and_missing_crc(self):
        for raw in (frame(IMU).replace(b'16000', b'16001'), IMU.encode(), frame(IMU)+b'0'):
            with self.assertRaises(ValueError): parse_imu(raw)

    def test_flags_bounds_and_clipping(self):
        for body in (IMU.replace(',20,7,', ',20,0,'), IMU.replace(',20,7,', ',20,32,'),
                     IMU.replace(',16000,', ',32767,'), IMU.replace(',0,0,1000,', ',0,0,99999999,'),
                     IMU.replace(',1,20,', ',-1,20,')):
            with self.assertRaises(ValueError): parse_imu(frame(body))
        with self.assertRaises(ValueError): parse_mag(frame(MAG.replace(',20,3,', ',20,4,')))

    def test_counter_rollover_and_calibration_flags(self):
        sample = parse_mag(frame('MAG1,4294967295,4294967295,27,1,2,3,33,67,100'))
        self.assertEqual(sample['flags'], 27)
        self.assertEqual(sample['device_ms'], 4294967295)

    def test_legacy_does_not_inherit_verification(self):
        state = MagState('test')
        state.ingest(frame(MAG), now=10)
        state.ingest(b'MAG,1,2,3', now=10.1)
        self.assertFalse(state.snapshot(now=10.1)['scale_verified'])
        self.assertFalse(state.snapshot(now=10.1)['calibrated'])

    def test_stale_frame_is_not_live(self):
        state = IMUState('test')
        state.ingest(frame(IMU), now=10)
        self.assertIsNone(state.snapshot(now=12)['sample'])
        self.assertFalse(state.snapshot(now=12)['scales_verified'])
