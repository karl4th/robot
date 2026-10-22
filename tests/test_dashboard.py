import time
import unittest
from robot.dashboard import ScanState


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
