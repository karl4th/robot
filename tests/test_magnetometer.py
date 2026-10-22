import unittest
from robot.magnetometer import MagState, parse_mag


class MagnetometerTests(unittest.TestCase):
    def test_formats_and_signed_values(self):
        self.assertEqual(parse_mag(b'MAG,100,-200,300\r\n')['raw'], [100,-200,300])
        self.assertEqual(parse_mag(b'X: 1065 \tY: 1996 \tZ: 1348')['raw'], [1065,1996,1348])
        self.assertIsNone(parse_mag(b'# MAG ready'))

    def test_bad_input(self):
        state=MagState('test')
        for raw in (b'MAG,1,2',b'MAG,1,2,3,4',b'MAG,1,nan,2',b'MAG,32768,0,0',b'\xff'):
            self.assertFalse(state.ingest(raw,now=10))
        self.assertEqual(state.rejected,5)
        self.assertIsNone(state.snapshot(now=10)['sample'])

    def test_conversion_and_quadrants(self):
        for values,angle in (('3000,0,0',0),('0,3000,0',90),('-3000,0,0',180),('0,-3000,0',270)):
            state=MagState('test')
            state.ingest(('MAG,'+values).encode(),now=10)
            sample=state.snapshot(now=10)['sample']
            self.assertEqual(sample['angle_deg'],angle)
            self.assertEqual(sample['norm_ut'],100)
        state=MagState('test',2)
        state.ingest(b'MAG,12000,0,0',now=10)
        self.assertEqual(state.snapshot(now=10)['sample']['field_ut'],[100,0,0])

    def test_degenerate_and_clipped_fields(self):
        for raw in (b'MAG,0,0,0',b'MAG,0,0,100',b'MAG,32767,100,10'):
            state=MagState('test')
            state.ingest(raw,now=10)
            self.assertIsNone(state.snapshot(now=10)['sample']['angle_deg'])

    def test_staleness_and_disconnect(self):
        state=MagState('test')
        state.ingest(b'MAG,10,20,30',now=10)
        self.assertEqual(state.snapshot(now=10)['status'],'live')
        self.assertIsNone(state.snapshot(now=12)['sample'])
        state.disconnected('Disconnected')
        self.assertIsNone(state.snapshot(now=10.1)['sample'])

    def test_repeated_values_do_not_imply_new_measurements(self):
        state=MagState('test')
        for t in (10,10.1,10.2,10.3):
            state.ingest(b'MAG,10,20,30',now=t)
        self.assertAlmostEqual(state.snapshot(now=10.3)['hz'],10)
        self.assertAlmostEqual(state.snapshot(now=10.3)['sample']['unchanged_s'],.3)
        state.ingest(b'MAG,11,20,30',now=10.4)
        self.assertEqual(state.snapshot(now=10.4)['sample']['unchanged_s'],0)

    def test_init_diagnostics_are_visible_but_not_measurements(self):
        state=MagState('test')
        self.assertFalse(state.ingest(b'#ERR,MAG_INIT',now=10))
        snapshot=state.snapshot(now=10)
        self.assertEqual(snapshot['status'],'offline')
        self.assertEqual(snapshot['error'],'MAG_INIT')
        self.assertEqual(snapshot['diagnostic'],'#ERR,MAG_INIT')
        self.assertEqual(snapshot['samples'],0)

    def test_reader_keeps_port_open_during_init_errors(self):
        import threading
        from unittest.mock import patch
        from robot.magnetometer import read_mag
        state=MagState('fake');stop=threading.Event();clock=[100.0]
        class Port:
            def __init__(self):self.reads=0
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,n):
                self.reads+=1;clock[0]+=2
                if self.reads==5:stop.set()
                return b'#ERR,MAG_INIT\n'
        port=Port()
        with patch('robot.magnetometer.serial.Serial',return_value=port) as constructor, patch('robot.magnetometer.time.monotonic',side_effect=lambda:clock[0]):
            read_mag(state,115200,stop)
        self.assertEqual(constructor.call_count,1)
        self.assertEqual(state.samples,0)
        self.assertEqual(state.error,'MAG_INIT')
