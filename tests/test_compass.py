import math
import unittest
from robot.compass import heading


def states(accel=(0,0,1),field=(25,0,-40)):
    return (dict(status='live',age_ms=10,sample=dict(format='v1',flags=7,accel_g=list(accel),gyro_dps=[0,0,0])),
            dict(status='live',age_ms=15,sample=dict(format='v1',flags=3,field_ut=list(field))))


class CompassTests(unittest.TestCase):
    def test_cardinal_directions(self):
        for field,expected in [((25,0,-40),0),((0,25,-40),90),((-25,0,-40),180),((0,-25,-40),270)]:
            self.assertAlmostEqual(heading(*states(field=field))['heading_deg'],expected)

    def test_tilt_and_wrap(self):
        # World frame N/W/up. Compose body-to-world Rz(-heading) Ry(pitch) Rx(roll).
        def rx(v,a):
            x,y,z=v;c,s=math.cos(a),math.sin(a);return [x,c*y-s*z,s*y+c*z]
        def ry(v,a):
            x,y,z=v;c,s=math.cos(a),math.sin(a);return [c*x+s*z,y,-s*x+c*z]
        def rz(v,a):
            x,y,z=v;c,s=math.cos(a),math.sin(a);return [c*x-s*y,s*x+c*y,z]
        for h in [0,1,45,90,179,270,359]:
            for roll in [-40,0,35]:
                for pitch in [-30,0,25]:
                    def body(v):return rx(ry(rz(v,math.radians(h)),-math.radians(pitch)),-math.radians(roll))
                    result=heading(*states(body([0,0,1]),body([25,0,-40])))
                    self.assertTrue(result['valid'])
                    self.assertAlmostEqual((result['heading_deg']-h+180)%360-180,0)

    def test_quality_gates(self):
        for key,value in [('status','offline'),('age_ms',300)]:
            a,m=states();a[key]=value;self.assertFalse(heading(a,m)['valid'])
        for key,value in [('flags',3),('flags',15),('gyro_dps',[31,0,0]),('accel_g',[0,0,1.2]),('accel_g',[0,0,float('nan')])]:
            a,m=states();a['sample'][key]=value;self.assertFalse(heading(a,m)['valid'])
        for field in [(0,0,40),(200,0,0)]:self.assertFalse(heading(*states(field=field))['valid'])
        a,m=states();m['age_ms']=200;self.assertFalse(heading(a,m)['valid'])
        a,m=states();m['sample']['flags']=1;self.assertFalse(heading(a,m)['valid'])
        self.assertFalse(heading(*states(accel=(1,0,0),field=(40,25,0)))['valid'])
