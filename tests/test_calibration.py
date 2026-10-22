import time
import unittest
from unittest.mock import patch
from robot.calibration import Calibration, FACES
from robot.imu import IMUState, read_imu
from robot.magnetometer import MagState, read_mag
from tests.test_sensor_protocol import frame, IMU, MAG


class Port:
    def __init__(self): self.written=[]
    def write(self, data): self.written.append(data); return len(data)


class CalibrationTests(unittest.TestCase):
    def controller(self, sensor='imu'):
        c=Calibration(sensor)
        c.observe({'format':'v1','flags':1},time.monotonic())
        return c

    def send(self,c,action):
        c.observe({'format':'v1','flags':1},time.monotonic())
        c.request(action,c.session)
        port=Port();c.write_pending(port)
        return port.written

    def test_complete_imu_sequence_requires_save_ack(self):
        c=self.controller()
        self.assertEqual(self.send(c,'begin'),[b'CAL ACCEL RESET\n'])
        c.diagnostic(b'#CAL,FACES_CLEARED')
        self.assertEqual(self.send(c,'capture'),[b'CAL GYRO\n'])
        c.diagnostic(b'#CAL,SETTLE_2S_THEN_HOLD_STILL_4S')
        self.assertEqual(c.snapshot()['phase'],'running')
        c.diagnostic(b'#CAL,GYRO_ACCEPTED_RAM,SAVE_REQUIRED')
        for i,face in enumerate(FACES):
            self.assertEqual(self.send(c,'capture'),[('CAL ACCEL '+face+'\n').encode()])
            c.diagnostic(b'#CAL,SETTLE_2S_THEN_HOLD_STILL_4S')
            c.diagnostic(f'#CAL,FACE_ACCEPTED,MASK={(1<<(i+1))-1}'.encode())
        self.assertNotEqual(c.snapshot()['phase'],'accepted')
        c.diagnostic(b'#CAL,ACCEL_ACCEPTED_RAM,SAVE_REQUIRED')
        self.assertEqual(c.snapshot()['phase'],'accepted')
        self.assertEqual(self.send(c,'save'),[b'SAVE\n'])
        self.assertNotEqual(c.snapshot()['phase'],'saved')
        c.diagnostic(b'#OK,SAVED')
        self.assertEqual(c.snapshot()['phase'],'saved')

    def test_magnetic_success_error_and_abort(self):
        c=self.controller('mag');self.send(c,'begin')
        c.diagnostic(b'#CAL,ROTATE_ALL_AXES_60S,MINIMUM_30S')
        c.diagnostic(b'#ERR,CAL_COVERAGE_OR_RESIDUAL')
        self.assertEqual(c.snapshot()['phase'],'error')
        self.send(c,'begin');c.diagnostic(b'#CAL,ROTATE_ALL_AXES_60S,MINIMUM_30S')
        c.diagnostic(b'#CAL,MAG_ACCEPTED_RAM,RMS=0.03,SAVE_REQUIRED')
        self.assertEqual(c.snapshot()['phase'],'accepted')
        self.send(c,'abort');c.diagnostic(b'#CAL,ABORTED')
        self.assertEqual(c.snapshot()['phase'],'idle')

    def test_legacy_stale_and_wrong_session_block_commands(self):
        c=Calibration('imu')
        for sample in ({'format':'legacy'},{'format':'v1','flags':1}):
            c.observe(sample,time.monotonic()-3)
            with self.assertRaises(ValueError):c.request('begin',c.session)
        c=self.controller()
        with self.assertRaises(ValueError):c.request('begin','stale')
        with self.assertRaises(ValueError):c.request('SAVE\nRESET',c.session)
        with self.assertRaises(ValueError):c.request('save',c.session)

    def test_duplicate_abort_and_disconnect_never_replay(self):
        c=self.controller();c.request('begin',c.session)
        with self.assertRaises(ValueError):c.request('begin',c.session)
        c.request('abort',c.session)
        p=Port();c.write_pending(p);self.assertEqual(p.written,[b'ABORT\n'])
        c.disconnect();c.write_pending(p)
        self.assertEqual(len(p.written),1)
        self.assertFalse(c.snapshot()['available'])

    def test_timeout_and_restart(self):
        c=self.controller();c.request('begin',c.session)
        c.deadline=time.monotonic()-1
        p=Port();c.write_pending(p)
        self.assertEqual(p.written,[])
        self.assertEqual(c.snapshot()['phase'],'error')
        session=c.session;c.diagnostic(b'#BOOT,IMU1,50HZ')
        self.assertNotEqual(c.session,session)
        self.assertEqual(c.snapshot()['phase'],'idle')

    def test_final_fit_failure_is_not_success(self):
        c=self.controller();c.phase='ready';c.step=6
        self.send(c,'capture');c.diagnostic(b'#CAL,FACE_ACCEPTED,MASK=63')
        c.diagnostic(b'#ERR,ACCEL_FIT_RANGE')
        self.assertEqual(c.snapshot()['phase'],'error')
        with self.assertRaises(ValueError):c.request('save',c.session)

    def test_actual_reader_dispatches_and_ingests_ack(self):
        # Exercise the real serial-owner loops, with a simulated board transport.
        for state,reader,module,data in ((IMUState('fake'),read_imu,'imu',frame(IMU)),(MagState('fake'),read_mag,'magnetometer',frame(MAG))):
            state.ingest(data)
            c=state.calibration;c.request('begin',c.session)
            import threading
            stop=threading.Event()
            class SimulatedPort(Port):
                def __init__(self,**kwargs):super().__init__();self.calls=0
                def __enter__(self):return self
                def __exit__(self,*args):pass
                def read(self,n):
                    self.calls+=1
                    if self.calls>1:stop.set()
                    ack=b'#CAL,FACES_CLEARED' if module=='imu' else b'#CAL,ROTATE_ALL_AXES_60S,MINIMUM_30S'
                    return ack+b'\n'+data+b'\n'
            port=SimulatedPort()
            with patch('robot.'+module+'.serial.Serial',return_value=port):reader(state,115200,stop)
            self.assertEqual(len(port.written),1)
            self.assertIn(c.snapshot()['phase'],('ready','running'))

    def test_rejected_face_retries_without_resetting_prior_faces(self):
        for reason in ('CAL_MOVEMENT_OR_NOISE', 'FACE_ORIENTATION',
                       'CAL_ACCEL_NOISE,AXIS=X,VALUE=200,LIMIT=180',
                       'IMU_SATURATION,CAPTURE_ABORTED'):
            c=self.controller();c.phase='ready';c.step=3
            self.send(c,'capture')
            c.diagnostic(('#ERR,'+reason).encode())
            self.assertEqual(c.phase,'ready')
            self.assertEqual(c.step,3)
            self.assertEqual(self.send(c,'capture'),[b'CAL ACCEL +Y\n'])
            c.diagnostic(b'#CAL,FACE_ACCEPTED,MASK=7')
            self.assertEqual(c.step,4)

    def test_hardware_fault_still_requires_restart(self):
        c=self.controller();c.phase='ready';c.step=3
        self.send(c,'capture');c.diagnostic(b'#ERR,IMU_STATUS_READ_FAILED,CAL_ABORTED')
        self.assertEqual(c.phase,'error')
