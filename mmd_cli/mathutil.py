"""Quaternion <-> Euler angle conversion in the order MMD uses.

MMD composes a bone rotation as yaw (Y), pitch (X), roll (Z): the Z rotation is applied
first, then X, then Y.  Angles are in degrees, quaternions are (x, y, z, w).
"""
import math

_GIMBAL_LIMIT = 0.9999995


def euler_to_quat(x_deg, y_deg, z_deg):
    hx = math.radians(x_deg) / 2.0
    hy = math.radians(y_deg) / 2.0
    hz = math.radians(z_deg) / 2.0
    sx, cx = math.sin(hx), math.cos(hx)
    sy, cy = math.sin(hy), math.cos(hy)
    sz, cz = math.sin(hz), math.cos(hz)
    return (sx * cy * cz + cx * sy * sz,
            cx * sy * cz - sx * cy * sz,
            cx * cy * sz - sx * sy * cz,
            cx * cy * cz + sx * sy * sz)


def quat_to_euler(quat):
    x, y, z, w = quat
    norm = math.sqrt(x * x + y * y + z * z + w * w)
    if norm == 0.0:
        return (0.0, 0.0, 0.0)
    x, y, z, w = x / norm, y / norm, z / norm, w / norm
    sin_x = 2.0 * (w * x - y * z)
    if abs(sin_x) > _GIMBAL_LIMIT:
        # X is +-90 degrees: only the sum/difference of Y and Z is defined, so Z is put to zero
        r00 = 1.0 - 2.0 * (y * y + z * z)
        r01 = 2.0 * (x * y - w * z)
        sign = 1.0 if sin_x > 0 else -1.0
        return (sign * 90.0, math.degrees(math.atan2(sign * r01, r00)), 0.0)
    return (math.degrees(math.asin(sin_x)),
            math.degrees(math.atan2(2.0 * (x * z + w * y), 1.0 - 2.0 * (x * x + y * y))),
            math.degrees(math.atan2(2.0 * (x * y + w * z), 1.0 - 2.0 * (x * x + z * z))))
