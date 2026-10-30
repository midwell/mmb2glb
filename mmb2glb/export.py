"""GLB serialization, rigid 2D skinning and explicit partial ANIM export."""
import csv
import io
import json
from pathlib import Path
import struct
from .binary import FormatError
from .math3d import IDENTITY, decompose, inverse, multiply


class GLB:
    def __init__(self):
        self.data = bytearray()
        self.doc = dict(asset=dict(version='2.0', generator='mmb2glb 0.1.0'),
                        scene=0, scenes=[dict(nodes=[])], nodes=[], meshes=[],
                        skins=[], materials=[], buffers=[], bufferViews=[], accessors=[],
                        extensionsUsed=['KHR_materials_unlit'])

    def view(self, data, target=None):
        self.data.extend(bytes((-len(self.data)) % 4))
        v = dict(buffer=0, byteOffset=len(self.data), byteLength=len(data))
        if target:
            v['target'] = target
        self.data.extend(data)
        self.doc['bufferViews'].append(v)
        return len(self.doc['bufferViews']) - 1

    def accessor(self, rows, kind, component=5126, target=None, bounds=False):
        if not rows:
            raise FormatError('cannot export an empty accessor')
        width = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4, 'MAT4': 16}[kind]
        fmt = {5126: 'f', 5123: 'H', 5125: 'I'}[component]
        flat = [x for row in rows for x in row]
        if len(flat) != width * len(rows):
            raise FormatError('accessor dimensions disagree')
        data = struct.pack('<' + str(len(flat)) + fmt, *flat)
        acc = dict(bufferView=self.view(data, target), componentType=component,
                   count=len(rows), type=kind)
        if bounds:
            acc['min'] = [min(row[i] for row in rows) for i in range(width)]
            acc['max'] = [max(row[i] for row in rows) for i in range(width)]
        self.doc['accessors'].append(acc)
        return len(self.doc['accessors']) - 1

    def serialize(self):
        self.doc['buffers'] = [dict(byteLength=len(self.data))]
        js = json.dumps(self.doc, ensure_ascii=False, allow_nan=False,
                        separators=(',', ':')).encode('utf-8')
        js += b' ' * ((-len(js)) % 4)
        binary = bytes(self.data) + bytes((-len(self.data)) % 4)
        length = 12 + 8 + len(js) + 8 + len(binary)
        return (struct.pack('<4sII', b'glTF', 2, length) +
                struct.pack('<I4s', len(js), b'JSON') + js +
                struct.pack('<I4s', len(binary), b'BIN\0') + binary)


class Textures:
    def __init__(self, root):
        self.root = Path(root).resolve() if root else None
        self.index = {}
        if self.root:
            if not self.root.is_dir():
                raise FormatError(f'texture directory does not exist: {self.root}')
            for p in sorted(self.root.rglob('*')):
                if p.is_file() and p.suffix.lower() in ['.png', '.jpg', '.jpeg', '.dds']:
                    self.index.setdefault(p.name.casefold(), []).append(p)

    def find(self, source):
        if not self.root:
            return None
        # Match extracted paths with either slash convention. Never follow an
        # absolute game path or traversal outside the user-selected directory.
        rel = source.replace('\\', '/')
        clean = Path(rel)
        if clean.is_absolute() or '..' in clean.parts:
            raise FormatError(f'unsafe texture path: {source}')
        names = [clean.with_suffix(ext) for ext in ['.png', '.jpg', '.jpeg', '.dds']]
        for name in names:
            p = (self.root / name).resolve()
            if p.is_relative_to(self.root) and p.is_file():
                return p
        for name in names:
            candidates = self.index.get(name.name.casefold(), [])
            if len(candidates) > 1:
                raise FormatError(f'ambiguous texture basename {name.name}; preserve game folders')
            if candidates:
                p = candidates[0].resolve()
                if not p.is_relative_to(self.root):
                    raise FormatError('texture symlink escapes texture directory')
                return p
        return None


def image_bytes(path, mask_path=None):
    """Embed native PNG/JPEG; optional Pillow handles DDS and separate masks."""
    if mask_path is None and path.suffix.lower() in ['.png', '.jpg', '.jpeg']:
        data = path.read_bytes()
        if data.startswith(b'\x89PNG\r\n\x1a\n'):
            return data, 'image/png'
        if data.startswith(b'\xff\xd8\xff'):
            return data, 'image/jpeg'
        raise FormatError(f'texture signature does not match PNG/JPEG: {path}')
    try:
        from PIL import Image, ImageChops
    except ImportError as exc:
        raise FormatError('DDS conversion and alpha masks require Pillow: pip install ".[textures]"') from exc
    try:
        with Image.open(path) as source:
            color = source.convert('RGBA')
        if mask_path:
            with Image.open(mask_path) as source:
                mask = source.convert('L')
            if mask.size != color.size:
                mask = mask.resize(color.size, Image.Resampling.BILINEAR)
            color.putalpha(ImageChops.multiply(color.getchannel('A'), mask))
        stream = io.BytesIO()
        color.save(stream, format='PNG')
        return stream.getvalue(), 'image/png'
    except (OSError, ValueError) as exc:
        raise FormatError(f'cannot decode texture {path}: {exc}') from exc


def build(bones, parts, materials, animations=(), texture_root=None,
          animation_mode='strict', pose=None, mask_channel='none'):
    if animation_mode not in ['strict', 'visibility']:
        raise FormatError('animation mode must be strict or visibility')
    if mask_channel not in ['none', 'luminance']:
        raise FormatError('mask channel must be none or luminance')
    issues = []
    for animation in animations:
        if animation.issues and animation_mode == 'strict':
            raise FormatError(f'{animation.name}: ' + '; '.join(animation.issues) +
                              '. Use --animation-mode visibility for explicit partial export.')
        issues.extend(f'{animation.name}: {issue}' for issue in animation.issues)
        if any(animation.sections[j][1] for j in [5, 9, 13]):
            raise FormatError('visibility export only supports constant ANIM tables; keyed streams are unsupported')
        if (animation.sections[0][1] != bytes([5]) * len(animation.names) or
                any(animation.sections[j][1] or animation.sections[j + 1][1] != b'\0\0'
                    for j in [6, 10, 14])):
            raise FormatError('unverified ANIM track type or key table encoding')
        for kind, table in animation.indices.items():
            if any(v < 0x8000 or (kind != 'scale' and v == 0xfffe) for v in table):
                raise FormatError(f'unverified ANIM {kind} reference encoding')
    lookup = {bone.name: i for i, bone in enumerate(bones)}
    for animation in animations:
        missing = [name for name in animation.names if name not in lookup and name != 'anm_state']
        if missing:
            raise FormatError(f'{animation.name}: animation bones missing from model: {missing}')
    g = GLB()
    trs, world = [], []
    for bone in bones:
        t, q, s = decompose(bone.matrix)
        trs.append((t, q, s))
        g.doc['nodes'].append(dict(name=bone.name, translation=t, rotation=q, scale=s))
        world.append(multiply(world[bone.parent], bone.matrix) if bone.parent >= 0 else bone.matrix)
    root = len(bones)
    g.doc['nodes'].append(dict(name='MMB_Root', children=[]))
    g.doc['scenes'][0]['nodes'] = [root]
    for i, bone in enumerate(bones):
        parent = bone.parent if bone.parent >= 0 else root
        g.doc['nodes'][parent].setdefault('children', []).append(i)
    inverse_bind = g.accessor([inverse(m) for m in world], 'MAT4')
    g.doc['skins'].append(dict(name='MMB rigid part skeleton', joints=list(range(len(bones))),
                               skeleton=root, inverseBindMatrices=inverse_bind))
    resolver, resolved = Textures(texture_root), {}
    texture_cache = {}
    for i, material in enumerate(materials):
        maps = dict(material.textures)
        for slot, source in material.textures:
            resolved[i, slot, source] = resolver.find(source)
        pbr = dict(baseColorFactor=list(material.color) + [1.], metallicFactor=0., roughnessFactor=1.)
        m = dict(name=material.name, pbrMetallicRoughness=pbr, doubleSided=True,
                 alphaMode='BLEND' if 'Trans' in material.shader else 'OPAQUE',
                 extensions={'KHR_materials_unlit': {}},
                 extras=dict(sourceShader=material.shader, textureLinks=maps,
                             sourceParameters=list(material.parameters)))
        diffuse_source = maps.get('DiffuseColor')
        diffuse = resolved.get((i, 'DiffuseColor', diffuse_source))
        mask_source = maps.get('TransparentColor')
        mask = resolved.get((i, 'TransparentColor', mask_source)) if mask_channel == 'luminance' else None
        if diffuse:
            key = (diffuse, mask)
            if key not in texture_cache:
                data, mime = image_bytes(diffuse, mask)
                view = g.view(data)
                images = g.doc.setdefault('images', [])
                images.append(dict(name=diffuse.name, bufferView=view, mimeType=mime))
                textures = g.doc.setdefault('textures', [])
                textures.append(dict(source=len(images) - 1, sampler=0))
                texture_cache[key] = len(textures) - 1
            pbr['baseColorTexture'] = dict(index=texture_cache[key])
            # A PNG may carry alpha even under the opaque source shader.
            m['alphaMode'] = 'BLEND'
        g.doc['materials'].append(m)
    if texture_cache:
        g.doc['samplers'] = [dict(magFilter=9729, minFilter=9729, wrapS=10497, wrapT=10497)]
    rows = []
    for i, part in enumerate(parts):
        joint_name = part.name.rsplit('|', 1)[0]
        if joint_name not in lookup:
            raise FormatError(f'no skeleton node for part {part.name}')
        joint = lookup[joint_name]
        count = len(part.vertices)
        attributes = dict(POSITION=g.accessor(part.vertices, 'VEC3', target=34962, bounds=True),
                          TEXCOORD_0=g.accessor(part.uv, 'VEC2', target=34962),
                          JOINTS_0=g.accessor([(joint, 0, 0, 0)] * count, 'VEC4', 5123, 34962),
                          WEIGHTS_0=g.accessor([(1., 0., 0., 0.)] * count, 'VEC4', target=34962))
        index = g.accessor([(v,) for v in part.indices], 'SCALAR', 5123, 34963)
        g.doc['meshes'].append(dict(name=part.name, primitives=[dict(attributes=attributes,
                                  indices=index, material=part.material, mode=4)], extras=part.metadata))
        mesh_node = len(g.doc['nodes'])
        g.doc['nodes'].append(dict(name=part.name, mesh=i, skin=0,
                                  extras=dict(sourcePart=i, attachedTo=joint_name)))
        # glTF skin matrices already bring vertices into scene coordinates;
        # keep skinned mesh nodes at scene roots to avoid inherited transforms.
        g.doc['scenes'][0]['nodes'].append(mesh_node)
        material = materials[part.material]
        for slot, source in material.textures:
            found = resolved[part.material, slot, source]
            rows.append(dict(part_index=i, part_name=part.name, bone=joint_name,
                             gltf_node=mesh_node, gltf_mesh=i, material_index=part.material,
                             material_name=material.name, shader=material.shader,
                             texture_slot=slot, texture_path=source,
                             resolved_path=str(found) if found else '',
                             embedded_as_base_color=bool(found and slot == 'DiffuseColor'),
                             depth=part.vertices[0][2]))
    if pose is not None:
        if not 0 <= pose < len(animations):
            raise FormatError('pose index must refer to one of the supplied animations')
        for name, visible in animations[pose].visibility().items():
            if name in lookup and not visible:
                g.doc['nodes'][lookup[name]]['scale'] = [0., 0., 0.]
    for animation in animations:
        # Static selectors are represented as STEP scale channels over the real
        # source duration. No invented idle motion is added.
        times = [(0.,)] if animation.duration == 0 else [(0.,), (animation.duration,)]
        time_acc = g.accessor(times, 'SCALAR', bounds=True)
        visibility = animation.visibility()
        samplers, channels = [], []
        for joint, bone in enumerate(bones):
            scale = trs[joint][2] if visibility.get(bone.name, True) else [0., 0., 0.]
            out = g.accessor([scale] * len(times), 'VEC3')
            samplers.append(dict(input=time_acc, output=out, interpolation='STEP'))
            channels.append(dict(sampler=len(samplers) - 1, target=dict(node=joint, path='scale')))
        g.doc.setdefault('animations', []).append(dict(name=animation.name, samplers=samplers,
            channels=channels, extras=dict(partial=bool(animation.issues), omitted=animation.issues,
                sourceFps=animation.fps, sourceFrames=animation.frames,
                packedSections=[dict(tag=tag, hex=data.hex()) for tag, data in animation.sections
                                if tag in ['DTRA', 'DROT', 'DSCA']])))
    g.doc['extras'] = dict(format='South Park TFBW 2D MMB',
                          conversionWarnings=issues,
                          rigMode='Rigid part attachments; no decoded per-vertex deforming weights',
                          uvMode='Analytic projection; packed UV overrides are not decoded')
    return g.serialize(), rows, issues


def csv_bytes(rows):
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]) if rows else [])
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode('utf-8-sig')
