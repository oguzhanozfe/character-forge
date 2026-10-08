"""Minimal vector, quaternion and 4x4 matrix math (column-vector convention, M @ v)."""
from __future__ import annotations

import math
from typing import Sequence

Vec = tuple  # (x, y, z)
Quat = tuple  # (w, x, y, z)
Mat = list  # 4x4 nested list, row-major storage, column-vector convention


def add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def mul(a, s):
    return (a[0] * s, a[1] * s, a[2] * s)


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def length(a):
    return math.sqrt(dot(a, a))


def normalize(a):
    n = length(a)
    if n < 1e-12:
        raise ValueError("Cannot normalize a zero-length vector")
    return (a[0] / n, a[1] / n, a[2] / n)


def lerp(a, b, t):
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t)


def distance(a, b):
    return length(sub(a, b))


def point_segment_distance(p, a, b):
    ab = sub(b, a)
    denominator = dot(ab, ab)
    t = 0.0 if denominator < 1e-18 else max(0.0, min(1.0, dot(sub(p, a), ab) / denominator))
    return distance(p, add(a, mul(ab, t))), t


# ---------------------------------------------------------------- quaternions

def quat_identity():
    return (1.0, 0.0, 0.0, 0.0)


def quat_axis_angle(axis, degrees):
    axis = normalize(axis)
    half = math.radians(degrees) / 2
    s = math.sin(half)
    return (math.cos(half), axis[0] * s, axis[1] * s, axis[2] * s)


def quat_mul(a, b):
    aw, ax, ay, az = a
    bw, bx, by, bz = b
    return (aw * bw - ax * bx - ay * by - az * bz,
            aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw)


def quat_conj(q):
    return (q[0], -q[1], -q[2], -q[3])


def quat_normalize(q):
    n = math.sqrt(sum(c * c for c in q))
    if n < 1e-12:
        return quat_identity()
    return tuple(c / n for c in q)


def quat_rotate(q, v):
    p = (0.0, v[0], v[1], v[2])
    r = quat_mul(quat_mul(q, p), quat_conj(q))
    return (r[1], r[2], r[3])


def quat_slerp(a, b, t):
    d = sum(x * y for x, y in zip(a, b))
    if d < 0:
        b = tuple(-c for c in b)
        d = -d
    if d > 0.9995:
        return quat_normalize(tuple(x + (y - x) * t for x, y in zip(a, b)))
    theta = math.acos(max(-1.0, min(1.0, d)))
    s = math.sin(theta)
    wa = math.sin((1 - t) * theta) / s
    wb = math.sin(t * theta) / s
    return tuple(wa * x + wb * y for x, y in zip(a, b))


def quat_angle_degrees(a, b):
    d = abs(sum(x * y for x, y in zip(quat_normalize(a), quat_normalize(b))))
    return math.degrees(2 * math.acos(min(1.0, d)))


def rotation_between(u, v):
    """Shortest-arc rotation taking direction u to direction v."""
    u, v = normalize(u), normalize(v)
    d = dot(u, v)
    if d > 1 - 1e-9:
        return quat_identity()
    if d < -1 + 1e-9:
        axis = cross(u, (1.0, 0.0, 0.0))
        if length(axis) < 1e-6:
            axis = cross(u, (0.0, 1.0, 0.0))
        return quat_axis_angle(axis, 180.0)
    axis = cross(u, v)
    return quat_normalize((1 + d, axis[0], axis[1], axis[2]))


def quat_to_mat3(q):
    w, x, y, z = quat_normalize(q)
    return [[1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
            [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
            [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)]]


def mat3_to_quat(m):
    trace = m[0][0] + m[1][1] + m[2][2]
    if trace > 0:
        s = math.sqrt(trace + 1.0) * 2
        q = (0.25 * s, (m[2][1] - m[1][2]) / s, (m[0][2] - m[2][0]) / s, (m[1][0] - m[0][1]) / s)
    elif m[0][0] > m[1][1] and m[0][0] > m[2][2]:
        s = math.sqrt(1.0 + m[0][0] - m[1][1] - m[2][2]) * 2
        q = ((m[2][1] - m[1][2]) / s, 0.25 * s, (m[0][1] + m[1][0]) / s, (m[0][2] + m[2][0]) / s)
    elif m[1][1] > m[2][2]:
        s = math.sqrt(1.0 + m[1][1] - m[0][0] - m[2][2]) * 2
        q = ((m[0][2] - m[2][0]) / s, (m[0][1] + m[1][0]) / s, 0.25 * s, (m[1][2] + m[2][1]) / s)
    else:
        s = math.sqrt(1.0 + m[2][2] - m[0][0] - m[1][1]) * 2
        q = ((m[1][0] - m[0][1]) / s, (m[0][2] + m[2][0]) / s, (m[1][2] + m[2][1]) / s, 0.25 * s)
    q = quat_normalize(q)
    return q if q[0] >= 0 else tuple(-c for c in q)


# ---------------------------------------------------------------- 4x4 matrices

def mat_identity():
    return [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0], [0.0, 0.0, 0.0, 1.0]]


def mat_mul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]


def mat_apply(m, v):
    return (m[0][0] * v[0] + m[0][1] * v[1] + m[0][2] * v[2] + m[0][3],
            m[1][0] * v[0] + m[1][1] * v[1] + m[1][2] * v[2] + m[1][3],
            m[2][0] * v[0] + m[2][1] * v[1] + m[2][2] * v[2] + m[2][3])


def mat_from_rot_trans(r3, t):
    return [[r3[0][0], r3[0][1], r3[0][2], t[0]],
            [r3[1][0], r3[1][1], r3[1][2], t[1]],
            [r3[2][0], r3[2][1], r3[2][2], t[2]],
            [0.0, 0.0, 0.0, 1.0]]


def mat_rot3(m):
    return [row[:3] for row in m[:3]]


def mat_translation(m):
    return (m[0][3], m[1][3], m[2][3])


def mat_rigid_inverse(m):
    """Inverse of an orthonormal rotation + translation matrix."""
    r = mat_rot3(m)
    rt = [[r[j][i] for j in range(3)] for i in range(3)]
    t = mat_translation(m)
    nt = tuple(-sum(rt[i][k] * t[k] for k in range(3)) for i in range(3))
    return mat_from_rot_trans(rt, nt)


def mat3_mul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def mat3_transpose(a):
    return [[a[j][i] for j in range(3)] for i in range(3)]


def mat3_apply(m, v):
    return (m[0][0] * v[0] + m[0][1] * v[1] + m[0][2] * v[2],
            m[1][0] * v[0] + m[1][1] * v[1] + m[1][2] * v[2],
            m[2][0] * v[0] + m[2][1] * v[1] + m[2][2] * v[2])


def bone_matrix(head, tail, z_hint):
    """Blender-style bone rest matrix: Y along head->tail, Z as close to z_hint as possible."""
    y = normalize(sub(tail, head))
    x = cross(y, z_hint)
    if length(x) < 1e-6:
        x = cross(y, (0.0, 0.0, 1.0) if abs(y[2]) < 0.9 else (0.0, -1.0, 0.0))
    x = normalize(x)
    z = cross(x, y)
    r3 = [[x[0], y[0], z[0]], [x[1], y[1], z[1]], [x[2], y[2], z[2]]]
    return mat_from_rot_trans(r3, head)


def is_finite_seq(values: Sequence[float]) -> bool:
    return all(math.isfinite(v) for v in values)
