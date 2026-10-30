import contextlib
import csv
import io
import json
import math
from pathlib import Path
import struct
import tempfile
import unittest

from mmb2glb.binary import FormatError
from mmb2glb.cli import main
from mmb2glb.export import build, csv_bytes, image_bytes, Textures
from mmb2glb.formats import Bone, Part, Material, read_mmb, read_cameldata, read_editordata, read_anim
from mmb2glb.math3d import IDENTITY, inverse, multiply, decompose

ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / 'chr_cartman.mmb'
CAMEL = ROOT / 'chr_cartman.cameldata'
EDITOR = ROOT / 'chr_cartman.editordata'
ANIM = ROOT / 'anm_cartman_base_idle_front.anim'


def decode_glb(blob):
    magic, version, length = struct.unpack_from('<4sII', blob)
    assert (magic, version, length) == (b'glTF', 2, len(blob))
    n, kind = struct.unpack_from('<I4s', blob, 12)
    assert kind == b'JSON' and n % 4 == 0
    doc = json.loads(blob[20:20 + n])
    offset = 20 + n
    size, kind = struct.unpack_from('<I4s', blob, offset)
    assert kind == b'BIN\0' and size % 4 == 0
    binary = blob[offset + 8:]
    assert len(binary) == size
    return doc, binary


def accessor(doc, binary, index):
    a = doc['accessors'][index]
    v = doc['bufferViews'][a['bufferView']]
    width = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4, 'MAT4': 16}[a['type']]
    fmt = {5126: 'f', 5123: 'H', 5125: 'I'}[a['componentType']]
    offset = v.get('byteOffset', 0) + a.get('byteOffset', 0)
    return list(struct.iter_unpack('<' + str(width) + fmt,
                binary[offset:offset + a['count'] * width * struct.calcsize(fmt)]))


@unittest.skipUnless(MODEL.exists(), 'sample assets are not installed')
class SampleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bones, cls.parts = read_mmb(MODEL)
        cls.camel = read_cameldata(CAMEL, cls.parts)
        cls.materials = read_editordata(EDITOR, len(cls.parts))
        cls.animation = read_anim(ANIM)
        cls.blob, cls.rows, cls.issues = build(cls.bones, cls.parts, cls.materials,
            [cls.animation], animation_mode='visibility', pose=0)
        cls.doc, cls.binary = decode_glb(cls.blob)

    def test_known_sample_counts(self):
        self.assertEqual((len(self.bones), len(self.parts), len(self.materials)), (626, 322, 322))
        self.assertEqual(sum(len(p.vertices) for p in self.parts), 36196)
        self.assertEqual(sum(len(p.indices) // 3 for p in self.parts), 40203)
        self.assertEqual(self.camel['packedAttributeBytes'], 46568)

    def test_every_mesh_matches_source_indices_positions_and_attachment(self):
        names = {b.name: i for i, b in enumerate(self.bones)}
        for part, mesh in zip(self.parts, self.doc['meshes']):
            p = mesh['primitives'][0]
            points = accessor(self.doc, self.binary, p['attributes']['POSITION'])
            indices = accessor(self.doc, self.binary, p['indices'])
            joints = accessor(self.doc, self.binary, p['attributes']['JOINTS_0'])
            weights = accessor(self.doc, self.binary, p['attributes']['WEIGHTS_0'])
            self.assertEqual(points, part.vertices)
            self.assertEqual([x[0] for x in indices], list(part.indices))
            self.assertLess(max(part.indices), len(points))
            self.assertEqual({x[0] for x in joints}, {names[part.name.rsplit('|', 1)[0]]})
            self.assertTrue(all(x == (1., 0., 0., 0.) for x in weights))

    def test_buffer_views_are_aligned_and_inside_buffer(self):
        for view in self.doc['bufferViews']:
            self.assertEqual(view['byteOffset'] % 4, 0)
            self.assertLessEqual(view['byteOffset'] + view['byteLength'], len(self.binary))
        for i, node in enumerate(self.doc['nodes']):
            if 'skin' in node:
                self.assertIn(i, self.doc['scenes'][0]['nodes'])

    def test_inverse_bind_cancels_bind_pose(self):
        matrices = accessor(self.doc, self.binary, self.doc['skins'][0]['inverseBindMatrices'])
        world = []
        for bone, inv in zip(self.bones, matrices):
            m = multiply(world[bone.parent], bone.matrix) if bone.parent >= 0 else bone.matrix
            world.append(m)
            for actual, expected in zip(multiply(m, inv), IDENTITY):
                self.assertAlmostEqual(actual, expected, places=5)

    def test_visibility_animation_and_duration(self):
        anim = self.doc['animations'][0]
        self.assertTrue(anim['extras']['partial'])
        self.assertEqual(len(self.animation.names), 124)
        self.assertEqual(sum(not v for v in self.animation.visibility().values()), 95)
        self.assertEqual(self.animation.frames, 92)
        self.assertEqual(self.animation.fps, 24.)
        self.assertAlmostEqual(self.animation.duration, 91 / 24, places=5)
        hidden = [n for n in self.doc['nodes'][:626] if n['scale'] == [0., 0., 0.]]
        self.assertEqual(len(hidden), 95)
        for sampler in anim['samplers']:
            times = accessor(self.doc, self.binary, sampler['input'])
            values = accessor(self.doc, self.binary, sampler['output'])
            self.assertEqual(times, [(0.,), (self.animation.duration,)])
            self.assertEqual(values[0], values[1])

    def test_strict_mode_rejects_undecoded_transforms(self):
        with self.assertRaisesRegex(FormatError, 'not yet decoded'):
            build(self.bones, self.parts, self.materials, [self.animation])

    def test_csv_contains_actual_material_links(self):
        rows = list(csv.DictReader(io.StringIO(csv_bytes(self.rows).decode('utf-8-sig'))))
        self.assertEqual(len(rows), 1610)
        self.assertEqual(len({r['texture_path'] for r in rows}), 80)
        self.assertEqual(rows[0]['part_name'], 'headParts|spPlanar89')
        self.assertEqual(rows[0]['texture_slot'], 'DiffuseColor')
        self.assertIn('tex_skintone_', rows[0]['texture_path'])
        for row in rows:
            part = self.parts[int(row['part_index'])]
            self.assertEqual(row['material_name'], self.materials[part.material].name)

    def test_invalid_and_truncated_files(self):
        for source, reader in [(MODEL, read_mmb),
                               (CAMEL, lambda p: read_cameldata(p, self.parts)),
                               (EDITOR, lambda p: read_editordata(p, 322)), (ANIM, read_anim)]:
            with self.subTest(source=source.name), tempfile.TemporaryDirectory() as temp:
                path = Path(temp) / source.name
                for size in [0, 4, 11, len(source.read_bytes()) - 1]:
                    path.write_bytes(source.read_bytes()[:size])
                    with self.assertRaises(FormatError):
                        reader(path)

    def test_cycle_and_out_of_range_index_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / 'bad.mmb'
            data = bytearray(MODEL.read_bytes())
            # Root's parent follows its length-prefixed name and 64-byte matrix.
            struct.pack_into('<h', data, 12 + 2 + len('cartman') + 64, 0)
            p.write_bytes(data)
            with self.assertRaisesRegex(FormatError, 'invalid parent'):
                read_mmb(p)
            data = bytearray(MODEL.read_bytes())
            struct.pack_into('<H', data, 102386, 65535)
            p.write_bytes(data)
            bones, parts = read_mmb(p)
            with self.assertRaisesRegex(FormatError, 'vertex range mismatch'):
                read_cameldata(CAMEL, parts)

    def test_cli_writes_outputs_and_protects_sources(self):
        with tempfile.TemporaryDirectory() as temp, contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            output = Path(temp) / 'model.glb'
            self.assertEqual(main([str(MODEL), '-o', str(output)]), 0)
            self.assertTrue(output.is_file())
            self.assertTrue(output.with_suffix('.textures.csv').is_file())
            self.assertEqual(main([str(MODEL), '-o', str(output)]), 2)
            self.assertEqual(main([str(MODEL), '-o', str(output), '--force', '--csv', str(CAMEL)]), 2)

    def test_cli_rejected_animation_leaves_no_output(self):
        with tempfile.TemporaryDirectory() as temp, contextlib.redirect_stderr(io.StringIO()):
            output = Path(temp) / 'bad.glb'
            self.assertEqual(main([str(MODEL), '-o', str(output), '--anim', str(ANIM)]), 2)
            self.assertEqual(list(Path(temp).iterdir()), [])

    def test_keyed_stream_is_rejected_in_visibility_mode(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'keyed.anim'
            data = ANIM.read_bytes().replace(b'TRADCHAK', b'TRAD\x01\x02\x03\x04CHAK', 1)
            path.write_bytes(data)
            anim = read_anim(path)
            with self.assertRaisesRegex(FormatError, 'keyed streams'):
                build(self.bones, self.parts, self.materials, [anim], animation_mode='visibility')


class MathTests(unittest.TestCase):
    def test_rotation_reflection_and_translation(self):
        m = (0., 2., 0., 0., -3., 0., 0., 0., 0., 0., 4., 0., 5., 6., 7., 1.)
        t, q, s = decompose(m)
        self.assertEqual(t, [5., 6., 7.])
        self.assertEqual(s, [2., 3., 4.])
        self.assertAlmostEqual(q[2], math.sqrt(.5))
        self.assertAlmostEqual(q[3], math.sqrt(.5))
        self.assertEqual(multiply(m, inverse(m)), IDENTITY)
        with self.assertRaisesRegex(FormatError, 'singular'):
            inverse((0.,) * 16)


class TextureTests(unittest.TestCase):
    def test_resolution_ambiguity_and_traversal(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'a').mkdir()
            (root / 'b').mkdir()
            (root / 'a/x.png').touch()
            resolver = Textures(root)
            self.assertEqual(resolver.find('camel\\x.dds'), (root / 'a/x.png').resolve())
            with self.assertRaisesRegex(FormatError, 'unsafe'):
                resolver.find('../x.dds')
            (root / 'b/x.png').touch()
            with self.assertRaisesRegex(FormatError, 'ambiguous'):
                Textures(root).find('x.dds')

    def test_embedded_texture_and_mask(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest('optional Pillow unavailable')
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / 'color.png'
            m = Path(temp) / 'mask.png'
            Image.new('RGBA', (2, 2), (255, 0, 0, 128)).save(p)
            Image.new('L', (2, 2), 128).save(m)
            data, mime = image_bytes(p, m)
            self.assertEqual(mime, 'image/png')
            result = Image.open(io.BytesIO(data))
            self.assertEqual(result.getpixel((0, 0)), (255, 0, 0, 64))
            self.assertEqual(image_bytes(p)[0], p.read_bytes())

    def test_texture_is_embedded_in_glb(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest('optional Pillow unavailable')
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / 'diffuse.png'
            Image.new('RGBA', (2, 2), (255, 128, 64, 255)).save(p)
            bone = Bone('root', -1, IDENTITY)
            part = Part('root|triangle', (0., 0., 0., 1., 1., 0.), (0, 1, 2),
                        [(0., 0., 0.), (1., 0., 0.), (0., 1., 0.)],
                        [(0., 0.), (1., 0.), (0., 1.)])
            material = Material('test', 'CamelDefaultShader', [('DiffuseColor', 'diffuse.dds')])
            blob, rows, issues = build([bone], [part], [material], texture_root=temp)
            doc, binary = decode_glb(blob)
            image = doc['images'][0]
            view = doc['bufferViews'][image['bufferView']]
            self.assertEqual(binary[view['byteOffset']:view['byteOffset'] + view['byteLength']], p.read_bytes())
            self.assertEqual(doc['materials'][0]['pbrMetallicRoughness']['baseColorTexture']['index'], 0)
            self.assertTrue(rows[0]['embedded_as_base_color'])


if __name__ == '__main__':
    unittest.main()
