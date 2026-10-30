"""Small column-major affine matrix helpers (no runtime dependencies)."""
import math
from .binary import FormatError

IDENTITY = (1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1.)


def multiply(a, b):
    return tuple(sum(a[k * 4 + row] * b[col * 4 + k] for k in range(4))
                 for col in range(4) for row in range(4))


def inverse(m):
    rows = [[m[col * 4 + row] for col in range(4)] +
            [float(row == col) for col in range(4)] for row in range(4)]
    for col in range(4):
        pivot = max(range(col, 4), key=lambda row: abs(rows[row][col]))
        if abs(rows[pivot][col]) < 1e-12:
            raise FormatError('singular bind matrix')
        rows[col], rows[pivot] = rows[pivot], rows[col]
        divisor = rows[col][col]
        rows[col] = [v / divisor for v in rows[col]]
        for row in range(4):
            if row != col:
                factor = rows[row][col]
                rows[row] = [a - factor * b for a, b in zip(rows[row], rows[col])]
    return tuple(rows[row][col + 4] for col in range(4) for row in range(4))


def decompose(m):
    scale = [math.sqrt(sum(m[col * 4 + row] ** 2 for row in range(3))) for col in range(3)]
    if min(scale) < 1e-12:
        raise FormatError('zero scale in bind matrix')
    det = (m[0] * (m[5] * m[10] - m[9] * m[6]) -
           m[4] * (m[1] * m[10] - m[9] * m[2]) +
           m[8] * (m[1] * m[6] - m[5] * m[2]))
    if det < 0:
        scale[0] *= -1
    r = [[m[col * 4 + row] / scale[col] for col in range(3)] for row in range(3)]
    if any(abs(sum(r[k][a] * r[k][b] for k in range(3))) > 1e-4
           for a, b in [(0, 1), (0, 2), (1, 2)]):
        raise FormatError('sheared bind transforms cannot be animated with glTF TRS')
    trace = sum(r[i][i] for i in range(3))
    if trace > 0:
        s = math.sqrt(trace + 1) * 2
        q = [(r[2][1] - r[1][2]) / s, (r[0][2] - r[2][0]) / s,
             (r[1][0] - r[0][1]) / s, s / 4]
    else:
        i = max(range(3), key=lambda j: r[j][j])
        j, k = (i + 1) % 3, (i + 2) % 3
        s = math.sqrt(1 + r[i][i] - r[j][j] - r[k][k]) * 2
        q = [0., 0., 0., 0.]
        q[i], q[j], q[k] = s / 4, (r[j][i] + r[i][j]) / s, (r[k][i] + r[i][k]) / s
        q[3] = (r[k][j] - r[j][k]) / s
    length = math.sqrt(sum(x * x for x in q))
    return list(m[12:15]), [x / length for x in q], scale
