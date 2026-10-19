import unittest
from gps import GPSState, coordinate, parse_nmea


def sentence(body):
    checksum = 0
    for char in body:
        checksum ^= ord(char)
    return f'${body}*{checksum:02X}\r\n'.encode()


GGA = 'GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,'
RMC = 'GPRMC,123519,A,4807.038,N,01131.000,E,10.0,84.4,230394,,,A'


class GPSTests(unittest.TestCase):
    def test_reference_checksum_and_coordinates(self):
        value = parse_nmea(b'$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47')
        self.assertAlmostEqual(value['latitude'], 48.1173)
        self.assertAlmostEqual(value['longitude'], 11.5166666667)
        self.assertEqual(value['satellites'], 8)
        self.assertEqual(value['altitude_m'], 545.4)
        self.assertAlmostEqual(coordinate('4807.038', 'S', True), -48.1173)
        self.assertLess(coordinate('01131.000', 'W', False), 0)

    def test_corruption_does_not_refresh_fix(self):
        state = GPSState('test')
        self.assertFalse(state.ingest(sentence(GGA).replace(b'545.4', b'545.5'), now=10))
        self.assertEqual(state.snapshot(now=10)['status'], 'offline')
        self.assertEqual(state.rejected, 1)

    def test_motion_units_and_invalid_fix(self):
        state = GPSState('test')
        state.ingest(sentence(GGA), now=10)
        state.ingest(sentence(RMC), now=10)
        self.assertAlmostEqual(state.snapshot(now=11)['speed_kmh'], 18.52)
        state.ingest(sentence(RMC.replace(',A,', ',V,', 1)), now=11)
        self.assertEqual(state.snapshot(now=11)['status'], 'no_fix')
        self.assertIsNone(state.snapshot(now=11)['latitude'])

    def test_transport_does_not_keep_position_fresh(self):
        state = GPSState('test')
        state.ingest(sentence(GGA), now=10)
        state.ingest(sentence('GPGSV,1,1,00'), now=14)
        result = state.snapshot(now=14)
        self.assertEqual(result['status'], 'no_fix')
        self.assertIsNone(result['latitude'])
        self.assertEqual(len(result['track']), 1)
        self.assertEqual(state.snapshot(now=18)['status'], 'offline')

    def test_no_fix_and_reconnection_gap(self):
        state = GPSState('test')
        state.ingest(sentence(GGA), now=10)
        state.ingest(sentence('GPGGA,123520,,,,,0,00,99.99,,,,,,'), now=11)
        self.assertEqual(state.snapshot(now=11)['status'], 'no_fix')
        self.assertEqual(len(state.track), 1)
        state.disconnected('Unplugged')
        self.assertEqual(state.snapshot(now=11)['status'], 'offline')
        state.ingest(sentence(GGA), now=20)
        self.assertNotEqual(state.track[0][2], state.track[1][2])

    def test_bad_fields_and_bounded_track(self):
        state = GPSState('test')
        for value in ('nan', '4860.000', '9100.000'):
            self.assertFalse(state.ingest(sentence(GGA.replace('4807.038', value)), now=10))
        for i in range(1000):
            state.ingest(sentence(GGA), now=20+i)
        self.assertEqual(len(state.track), 900)

    def test_stale_motion_is_not_reused(self):
        state = GPSState('test')
        state.ingest(sentence(RMC), now=10)
        state.ingest(sentence(GGA), now=14)
        self.assertIsNone(state.snapshot(now=14)['speed_kmh'])
        self.assertEqual(state.snapshot(now=14)['status'], 'live')
