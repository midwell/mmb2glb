"""Readers for the 2D MMB CB / CAMEL v3 and ANIM v14 sample formats.

Offsets and unresolved fields are documented in docs/FORMAT.md. No scanning for
plausible floating point geometry is used: all arrays follow counted records.
"""
from dataclasses import dataclass, field
import math
import struct
from .binary import Reader, FormatError


@dataclass
class Bone:
    name: str
    parent: int
    matrix: tuple


@dataclass
class Part:
    name: str
    bounds: tuple
    indices: tuple
    vertices: list = field(default_factory=list)
    uv: list = field(default_factory=list)
    material: int = 0
    metadata: dict = field(default_factory=dict)


@dataclass
class Material:
    name: str
    shader: str
    textures: list
    color: tuple = (1.0, 1.0, 1.0)
    parameters: tuple = ()


def read_mmb(path):
    r = Reader(path)
    if r.take(4) != b'MMB\xcb':
        r.fail('expected 2D MMB CB header')
    if r.u32() != len(r.data):
        r.fail('declared file size does not match input')
    bones = []
    for i in range(r.count(68)):
        name, matrix, parent = r.string(), r.unpack('16f'), r.unpack('h')[0]
        if not name or not -1 <= parent < i:
            r.fail('invalid parent (parents must precede children) or empty name')
        if any(abs(matrix[j] - expected) > 1e-5
               for j, expected in [(3, 0), (7, 0), (11, 0), (15, 1)]):
            r.fail('non-affine skeleton matrix')
        bones.append(Bone(name, parent, matrix))
    if len({b.name for b in bones}) != len(bones):
        r.fail('duplicate bone names; attachment would be ambiguous')
    if not bones:
        r.fail('empty skeleton')
    parts, ranges = [], []
    for _ in range(r.count(146)):
        name = r.string()
        h = r.take(144)
        bounds = struct.unpack_from('<6f', h)
        if not all(math.isfinite(x) for x in bounds):
            r.fail('non-finite mesh bounds')
        # These constants identify the demonstrated 2D triangle-list layout.
        if struct.unpack_from('<3H2IB', h, 48) != (0, 1, 39, 1, 1, 240):
            r.fail('unsupported mesh vertex declaration')
        count = struct.unpack_from('<I', h, 63)[0]
        offset, size = struct.unpack_from('<2I', h, 91)
        if not count or count % 3 or size != count * 2:
            r.fail('invalid triangle index count or byte size')
        if (struct.unpack_from('<I', h, 75)[0] != count or
                struct.unpack_from('<I', h, 87)[0] != size or
                struct.unpack_from('<I', h, 124)[0] != 2 or
                struct.unpack_from('<3I', h, 132) != (count, 0, size)):
            r.fail('inconsistent mesh index metadata')
        if offset + size > len(r.data):
            r.fail('triangle index range is outside the file')
        indices = struct.unpack_from('<' + str(count) + 'H', r.data, offset)
        if abs(bounds[2] - bounds[5]) > 1e-5:
            r.fail('non-planar part in a 2D MMB')
        parts.append(Part(name, bounds, indices))
        ranges.append((offset, size))
    for offset, size in ranges:
        if offset != r.pos:
            r.fail('index blocks are not contiguous after the mesh table')
        r.take(size)
    r.end()
    if not parts:
        r.fail('empty model')
    return bones, parts


def read_cameldata(path, parts):
    r = Reader(path)
    if r.u32() != 3:
        r.fail('only CAMEL version 3 is supported')
    if r.u32() != len(parts):
        r.fail('part count differs from MMB')
    words = r.take(r.count(4) * 4)
    records = [r.take(152) for _ in parts]
    vertices = [r.unpack('2f') for _ in range(r.count(8))]
    if r.u32() != len(parts):
        r.fail('depth count differs from part count')
    depths = [r.unpack('f')[0] for _ in parts]
    packed_uv = r.take(r.count(4) * 4)
    auxiliary = r.take(r.count(4) * 4)
    r.end()
    expected_vertex = 0
    for i, (part, record, depth) in enumerate(zip(parts, records, depths)):
        v = struct.unpack('<12f7I2H16f2f', record)
        if any(isinstance(x, float) and not math.isfinite(x) for x in v):
            r.fail('non-finite CAMEL record')
        origin, offset = v[:2], v[2:4]
        row_u, row_v = v[4:8], v[8:12]
        a, an, b, bn, first, material, extra = v[12:19]
        flags = v[19:21]
        matrix, axes = v[21:37], v[37:39]
        if flags not in [(0, 1), (5, 1)]:
            r.fail(f'unsupported CAMEL flags {flags} for {part.name}')
        n = max(part.indices) + 1
        if first != expected_vertex or first + n > len(vertices):
            r.fail(f'vertex range mismatch for {part.name}')
        expected_vertex += n
        if a + an > len(words) // 4 or b + bn > len(words) // 4:
            r.fail('packed attribute range exceeds word table')
        if material >= len(parts) or extra > len(packed_uv) // 4:
            r.fail('invalid material or auxiliary UV offset')
        if abs(depth - part.bounds[2]) > 1e-5:
            r.fail(f'depth disagrees with MMB bounds for {part.name}')
        xy = vertices[first:first + n]
        actual = (min(p[0] for p in xy), min(p[1] for p in xy), depth,
                  max(p[0] for p in xy), max(p[1] for p in xy), depth)
        if any(abs(x - y) > 2e-5 for x, y in zip(actual, part.bounds)):
            r.fail(f'vertex bounds disagree with MMB for {part.name}')
        part.vertices = [(x, y, depth) for x, y in xy]
        # Analytic UV projection: axis reflection, origin, 2D row directions,
        # reciprocal dimensions and offsets. UV overrides remain unresolved.
        part.uv = []
        for x, y in xy:
            dx, dy = x * axes[0] - origin[0], y * axes[1] - origin[1]
            part.uv.append(((dx * row_u[0] + dy * row_u[1]) * row_u[3] + offset[0],
                            (dx * row_v[0] + dy * row_v[1]) * row_v[3] + offset[1]))
        part.material = material
        part.metadata = dict(camelFlags=list(flags), uvOverrideOffset=extra,
                             sourceMatrix=list(matrix), uvProjection=list(v[:12]),
                             uvAxes=list(axes), packedAttributeRanges=[a, an, b, bn])
    if expected_vertex != len(vertices):
        r.fail('unreferenced vertices in CAMEL table')
    return dict(version=3, vertices=len(vertices), packedAttributeBytes=len(words),
                uvOverrideBytes=len(packed_uv), auxiliaryBytes=len(auxiliary),
                packedAttributesHex=words.hex(), uvOverridesHex=packed_uv.hex(),
                auxiliaryHex=auxiliary.hex())


def read_editordata(path, part_count):
    r = Reader(path)
    if r.u32() != part_count:
        r.fail('material count differs from MMB')
    materials = []
    for _ in range(part_count):
        if r.u32() != 1:
            r.fail('unsupported material record version')
        name, shader = r.string(), r.string()
        textures = [(r.string(), r.string()) for _ in range(r.count(4))]
        materials.append(Material(name, shader, textures))
    # The supplied revision has 14 bytes per material of zero flags, a global
    # revision and 108-byte shader parameter records. Refuse to guess variants.
    if r.take(14 * part_count) != bytes(14 * part_count) or r.u32() != 3:
        r.fail('unsupported editor shader parameter layout')
    for material in materials:
        enabled, *params = r.unpack('I26f')
        if enabled != 1:
            r.fail('unsupported disabled shader parameters')
        if any(not 0 <= c <= 1 for c in params[:3]):
            r.fail('diffuse tint is outside 0..1')
        material.color = tuple(params[:3])
        material.parameters = tuple(params)
    r.end()
    return materials


ANIM_TAGS = [b'TYPE', b'DTRA', b'DROT', b'DSCA', b'TRAI', b'TRAD', b'CHAK', b'CAKS',
             b'ROTI', b'ROTD', b'CHAK', b'CAKS', b'SCAI', b'SCAD', b'CHAK', b'CAKS',
             b'NAME', b'PART', b'IKEF', b'IKEA']


@dataclass
class Animation:
    name: str
    fps: float
    duration: float
    frames: int
    names: list
    indices: dict
    sections: list
    issues: list

    def visibility(self):
        return {name: value != 0xfffe
                for name, value in zip(self.names, self.indices['scale'])}


def read_anim(path):
    r = Reader(path)
    if r.take(4) != b'ANIM' or r.unpack('H')[0] != 14:
        r.fail('only ANIM version 14 is supported')
    flags = r.unpack('H')[0]
    fps, duration = r.unpack('2f')
    frames = r.u32()
    r.u32()  # runtime workspace size, not a file offset
    r.take(12)
    count = r.u32()
    if not 0 < fps <= 1000 or not 0 < duration <= 86400 or not 0 < count <= 65534:
        r.fail('invalid animation rate, duration, or track count')
    if frames < 1 or abs(duration - (frames - 1) / fps) > 1e-4:
        r.fail('frame count and duration disagree')
    if flags != 3:
        r.fail(f'unsupported ANIM flags {flags}')
    r.take(41)  # v14 fixed header ends at byte 81
    sections, start = [], r.pos
    # Repeated CHAK/CAKS tags make a global dictionary incorrect. Find tags in
    # their required sequence and validate fixed-size tables below. Keyed data
    # is rejected rather than interpreting tag-like bytes as working animation.
    for index, tag in enumerate(ANIM_TAGS):
        if r.data[start:start + 4] != tag:
            r.pos = start
            r.fail(f'expected animation section {tag.decode()}')
        begin = start + 4
        if index + 1 < len(ANIM_TAGS):
            nxt = ANIM_TAGS[index + 1]
            if tag == b'TYPE':
                end = begin + count
            elif tag in [b'TRAI', b'ROTI', b'SCAI']:
                end = begin + count * 2
            else:
                end = r.data.find(nxt, begin)
            if end < begin or r.data[end:end + 4] != nxt:
                r.pos = begin
                r.fail(f'missing or misplaced {nxt.decode()} section')
        else:
            end = len(r.data)
        sections.append((tag.decode(), r.data[begin:end]))
        start = end
    names = sections[16][1].split(b'\0')
    if not names or names[-1] != b'':
        r.fail('bone name table is not NUL terminated')
    try:
        names = [n.decode('utf-8') for n in names[:-1]]
    except UnicodeDecodeError:
        r.fail('invalid UTF-8 in animation names')
    if len(names) != count or len(set(names)) != count or any(not n for n in names):
        r.fail('animation name count mismatch, empty or duplicate names')
    if sections[17][1] != bytes(4) or sections[18][1] != bytes(4):
        r.fail('nonempty PART/IKEF metadata is unsupported')
    # The v14 footer has a counted source path, a byte flag, counted uint32
    # metadata, track count and a counted runtime block. Validate every range;
    # otherwise truncating the footer could falsely look like a valid clip.
    footer = sections[19][1]
    if len(footer) < 8 or struct.unpack_from('<I', footer)[0] != 0:
        r.fail('invalid IKEA footer')
    path_size = struct.unpack_from('<I', footer, 4)[0]
    p = 8 + path_size
    if not path_size or p + 5 > len(footer) or footer[p - 1] != 0 or footer[p] != 0:
        r.fail('truncated or unsupported animation source path')
    n = struct.unpack_from('<I', footer, p + 1)[0]
    p += 5 + n * 4
    if p + 8 > len(footer):
        r.fail('truncated animation footer metadata')
    track_count, runtime_size = struct.unpack_from('<2I', footer, p)
    if track_count != count or p + 8 + runtime_size != len(footer):
        r.fail('animation footer count or size mismatch')
    indices = {kind: list(struct.unpack('<' + str(count) + 'H', sections[j][1]))
               for kind, j in [('translation', 4), ('rotation', 8), ('scale', 12)]}
    issues = []
    if sections[0][1] != bytes([5]) * count:
        issues.append('unverified TYPE track encoding')
    for kind, table in indices.items():
        if any(v not in [0xffff, 0xfffe] for v in table):
            issues.append(f'packed {kind} values are not yet decoded')
        if kind != 'scale' and 0xfffe in table:
            issues.append(f'zero sentinel in {kind} table is unverified')
    if any(sections[j][1] for j in [5, 9, 13]):
        issues.append('changing keyframe streams are not yet decoded')
    for j in [6, 10, 14]:
        if sections[j][1] or sections[j + 1][1] != b'\0\0':
            issues.append('nonempty CHAK/CAKS key tables are not yet decoded')
    return Animation(r.path.stem, fps, duration, frames, names, indices, sections, issues)
