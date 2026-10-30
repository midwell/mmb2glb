import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
from .binary import FormatError
from .formats import read_mmb, read_cameldata, read_editordata, read_anim
from .export import build, csv_bytes


def atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            name = stream.name
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)


def parser():
    p = argparse.ArgumentParser(description='Convert TFBW 2D MMB + CAMEL v3 models to GLB and texture CSV.',
        epilog='ANIM packed transforms/keyframes are unresolved. Strict mode refuses incomplete animation; '
               'visibility mode explicitly exports only constant pose selectors.')
    p.add_argument('model', type=Path, help='source .mmb file')
    p.add_argument('-o', '--output', type=Path, help='destination .glb (default: beside input)')
    p.add_argument('--cameldata', type=Path, help='default: model basename + .cameldata')
    p.add_argument('--editordata', type=Path, help='default: model basename + .editordata')
    p.add_argument('--anim', action='append', default=[], type=Path, help='ANIM v14 file; repeat for multiple clips')
    p.add_argument('--animation-mode', choices=['strict', 'visibility'], default='strict',
                   help='strict rejects unresolved tracks; visibility exports constant selectors only')
    p.add_argument('--pose', type=int, help='set initial visibility from this zero-based --anim index')
    p.add_argument('--textures', type=Path, help='extracted texture directory (PNG/JPEG or DDS with Pillow)')
    p.add_argument('--mask-channel', choices=['none', 'luminance'], default='none',
                   help='optionally multiply diffuse alpha by TransparentColor luminance; shader semantics unverified')
    p.add_argument('--csv', type=Path, help='default: output basename + .textures.csv')
    p.add_argument('--report', type=Path, help='default: output basename + .report.json')
    p.add_argument('--force', action='store_true', help='replace existing output files')
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        model = args.model.resolve()
        camel = (args.cameldata or model.with_suffix('.cameldata')).resolve()
        editor = (args.editordata or model.with_suffix('.editordata')).resolve()
        output = (args.output or model.with_suffix('.glb')).resolve()
        if output.suffix.lower() != '.glb':
            raise FormatError('output must have a .glb extension')
        csv_path = (args.csv or output.with_suffix('.textures.csv')).resolve()
        report_path = (args.report or output.with_suffix('.report.json')).resolve()
        destinations = [output, csv_path, report_path]
        inputs = {model, camel, editor, *(p.resolve() for p in args.anim)}
        if len(set(destinations)) != 3 or any(p in inputs for p in destinations):
            raise FormatError('output paths must be distinct and must not overwrite source files')
        if not args.force and any(p.exists() for p in destinations):
            raise FormatError('an output already exists; use --force to replace it')
        bones, parts = read_mmb(model)
        camel_info = read_cameldata(camel, parts)
        materials = read_editordata(editor, len(parts))
        animations = [read_anim(p) for p in args.anim]
        data, rows, warnings = build(bones, parts, materials, animations, args.textures,
                                     args.animation_mode, args.pose, args.mask_channel)
        warnings = list(dict.fromkeys([
            'Packed vertex attributes and UV overrides are preserved in the report but are not decoded; '
            'UV projection and material tints are approximate.',
            'Rig uses one rigid attachment per part; per-vertex deforming weights are not decoded.',
            'Game animation-state logic (.manimsys), IK, constraints and shader behavior are not exported.',
            *warnings]))
        missing = sorted({row['texture_path'] for row in rows if not row['resolved_path']})
        if missing:
            warnings.append(f'{len(missing)} distinct texture paths are unresolved; see texture CSV.')
        report = dict(model=str(model), output=str(output), skeleton_nodes=len(bones), parts=len(parts),
                      vertices=sum(len(p.vertices) for p in parts),
                      triangles=sum(len(p.indices) // 3 for p in parts), materials=len(materials),
                      texture_links=len(rows), unresolved_textures=missing, camel=camel_info,
                      animations=[dict(name=a.name, duration=a.duration, fps=a.fps, frames=a.frames,
                                       partial=bool(a.issues), omitted=a.issues) for a in animations],
                      warnings=warnings)
        # Complete parsing/serialization before creating any output file.
        report_data = (json.dumps(report, indent=2, allow_nan=False) + '\n').encode('utf-8')
        for path, content in [(output, data), (csv_path, csv_bytes(rows)), (report_path, report_data)]:
            atomic_write(path, content)
        print(f'Wrote {output}\nWrote {csv_path}\nWrote {report_path}')
        print(f'{len(parts)} parts, {len(bones)} skeleton nodes, {report["vertices"]} vertices, '
              f'{report["triangles"]} triangles')
        for warning in warnings:
            print('WARNING: ' + warning, file=sys.stderr)
        return 0
    except (FormatError, OSError, ValueError, OverflowError) as exc:
        print(f'mmb2glb: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
