import math
import unittest

from mmd_cli import mathutil


def rotate(q, v):
    """q * v * q^-1 by the plain Hamilton product (independent of the code under test)."""
    def mul(a, b):
        ax, ay, az, aw = a
        bx, by, bz, bw = b
        return (aw * bx + ax * bw + ay * bz - az * by,
                aw * by - ax * bz + ay * bw + az * bx,
                aw * bz + ax * by - ay * bx + az * bw,
                aw * bw - ax * bx - ay * by - az * bz)
    x, y, z, w = q
    r = mul(mul(q, (v[0], v[1], v[2], 0.0)), (-x, -y, -z, w))
    return r[:3]


def axis_rotation(axis, deg, v):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    x, y, z = v
    if axis == "x":
        return (x, c * y - s * z, s * y + c * z)
    if axis == "y":
        return (c * x + s * z, y, -s * x + c * z)
    return (c * x - s * y, s * x + c * y, z)


class EulerToQuatTest(unittest.TestCase):
    def assert_close(self, got, want, places=6):
        self.assertEqual(len(got), len(want))
        for g, w in zip(got, want):
            self.assertAlmostEqual(g, w, places=places, msg="%r != %r" % (got, want))

    def test_zero_is_identity(self):
        self.assert_close(mathutil.euler_to_quat(0, 0, 0), (0, 0, 0, 1))

    def test_single_axis_rotations(self):
        h = math.sin(math.radians(45))
        self.assert_close(mathutil.euler_to_quat(90, 0, 0), (h, 0, 0, h))
        self.assert_close(mathutil.euler_to_quat(0, 90, 0), (0, h, 0, h))
        self.assert_close(mathutil.euler_to_quat(0, 0, 90), (0, 0, h, h))

    def test_axes_are_applied_in_z_x_y_order(self):
        x, y, z = 30.0, 40.0, 50.0
        q = mathutil.euler_to_quat(x, y, z)
        for v in ((1, 0, 0), (0, 1, 0), (0, 0, 1), (0.3, -0.5, 0.8)):
            want = axis_rotation("y", y, axis_rotation("x", x, axis_rotation("z", z, v)))
            self.assert_close(rotate(q, v), want)

    def test_result_is_unit_length(self):
        q = mathutil.euler_to_quat(12, -77, 143)
        self.assertAlmostEqual(sum(c * c for c in q), 1.0, places=9)


class QuatToEulerTest(unittest.TestCase):
    def test_roundtrip(self):
        for e in ((0, 0, 0), (10, 20, 30), (-45, 170, -120), (89, 0, 0), (0, -179, 0), (33.5, -12.25, 71.125)):
            got = mathutil.quat_to_euler(mathutil.euler_to_quat(*e))
            for g, w in zip(got, e):
                self.assertAlmostEqual(g, w, places=4, msg="%r -> %r" % (e, got))

    def test_non_unit_quaternion_is_normalised(self):
        q = mathutil.euler_to_quat(10, 20, 30)
        got = mathutil.quat_to_euler(tuple(2.0 * c for c in q))
        for g, w in zip(got, (10, 20, 30)):
            self.assertAlmostEqual(g, w, places=4)

    def test_gimbal_lock_keeps_the_same_rotation(self):
        q = mathutil.euler_to_quat(90, 25, 40)
        back = mathutil.euler_to_quat(*mathutil.quat_to_euler(q))
        for v in ((1, 0, 0), (0, 1, 0), (0, 0, 1)):
            for g, w in zip(rotate(back, v), rotate(q, v)):
                self.assertAlmostEqual(g, w, places=4)


if __name__ == "__main__":
    unittest.main()
