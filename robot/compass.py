"""Quasi-static magnetic heading in the robot frame: X forward, Y left, Z up."""
import math


def dot(a, b):
    return sum(x*y for x, y in zip(a, b))


def cross(a, b):
    return [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]]


def norm(v):
    return math.sqrt(dot(v, v))


def heading(imu, mag):
    result = dict(valid=False, heading_deg=None, reason='', reference='magnetic',
                  mounting='Both sensors: +X forward, +Y left, +Z up')
    def reject(reason):
        result['reason'] = reason
        return result
    if imu.get('status') != 'live' or mag.get('status') != 'live':
        return reject('Waiting for both sensors')
    ages = [imu.get('age_ms'), mag.get('age_ms')]
    if any(x is None or x > 250 for x in ages) or abs(ages[0]-ages[1]) > 150:
        return reject('Sensor samples are stale or too far apart')
    a, m = imu['sample'], mag['sample']
    if a.get('format') != 'v1' or m.get('format') != 'v1':
        return reject('Verified sensor firmware required')
    if (a.get('flags', 0) & 7) != 7 or (m.get('flags', 0) & 3) != 3:
        return reject('Calibrate both sensors first')
    if a['flags'] & 8 or m['flags'] & 8:
        return reject('Calibration in progress')
    accel, field, gyro = a['accel_g'], m['field_ut'], a['gyro_dps']
    if not all(math.isfinite(x) for v in (accel, field, gyro) for x in v):
        return reject('Invalid sensor values')
    g, strength = norm(accel), norm(field)
    if not .9 <= g <= 1.1 or norm(gyro) > 30:
        return reject('Motion detected; hold steady for heading')
    if not 10 <= strength <= 100:
        return reject('Magnetic field outside expected range')
    up = [v/g for v in accel]
    north = [field[i]-dot(field, up)*up[i] for i in range(3)]
    horizontal = norm(north)
    if horizontal < 5:
        return reject('Horizontal magnetic field is too weak')
    north = [v/horizontal for v in north]
    east = cross(north, up)
    # Projection of robot forward (+X) onto the horizontal plane.
    if math.hypot(north[0], east[0]) < .2:
        return reject('Robot forward axis is nearly vertical')
    result.update(valid=True, heading_deg=math.degrees(math.atan2(east[0], north[0])) % 360,
                  reason='Tilt compensated · magnetic north', field_ut=strength)
    return result
