# mmb2glb — experimental TFBW 2D converter

Python converter for **South Park: The Fractured But Whole** MMB CB / CAMEL v3 assets, developed against a Cartman sample. Exports GLB, a texture-to-part CSV, and a JSON conversion report. Python 3.10+; no dependencies for geometry export.

**This is a working model/rig prototype, not a complete ANIM converter.** Packed ANIM transforms and changing keyframes are not decoded. The default mode rejects incomplete animation exports. An explicit visibility mode exports the constant selectors from the supplied idle clip, retaining the skeleton's bind transforms. It does **not** reproduce the full source animation. Packed vertex attributes, UV overrides, deforming skin weights and game shaders also remain unresolved. See [format notes](docs/FORMAT.md).

## Run

Game assets are not included in this repository. Place your extracted MMB, CAMEL and editor-data files together, then run from this directory without installation:

```sh
python3 -m mmb2glb chr_cartman.mmb -o output/cartman.glb
```

The `.cameldata` and `.editordata` companions must have the same basename, or be supplied using `--cameldata` and `--editordata`. The MMB alone contains indices and a skeleton, not the complete vertex data.

A model-only export includes all alternate mouths, eyes and views. They overlap until you select a pose. For the supplied front view, explicitly request the partial ANIM selector export:

```sh
python3 -m mmb2glb chr_cartman.mmb \
  --anim anm_cartman_base_idle_front.anim \
  --animation-mode visibility --pose 0 \
  -o output/cartman_front.glb
```

`--pose 0` applies the first supplied clip's constant visibility selectors at rest. Each exported clip also contains STEP scale channels for these selectors over the source duration. Repeat `--anim` to supply more constant-selector clips; unsupported keyed streams are rejected. This sample's clip lasts 91/24 seconds, with 92 frames at 24 fps. Its packed translations and nonzero scale constants are omitted and recorded in the report and GLB extras.

Generated files:

- `cartman.glb`: 322 named triangle meshes, 626 skeleton nodes, rigid part attachments, depth layers, UV projections and materials.
- `cartman.textures.csv`: 1,610 links covering 80 distinct game texture paths, with mesh, part, bone, material and texture slot.
- `cartman.report.json`: counts, limitations, unresolved textures and original packed CAMEL tables in hex for future decoding.

The development sample contains 36,196 vertices and 40,203 triangles. Source game files and generated model examples are excluded from version control. You can reproduce the front-selector export using the command above with your local files.

## Textures

The supplied files reference DDS textures but **do not include the texture images**. Without them, GLB materials use their source RGB tints and the CSV retains all links. This does not reproduce the game's final appearance.

```sh
python3 -m mmb2glb chr_cartman.mmb \
  --textures /path/to/extracted/textures -o output/cartman.glb
```

PNG and JPEG images are embedded directly in the GLB. Converted PNG/JPEG equivalents of DDS filenames are preferred. Resolution first tries the full extracted game path, then a unique filename match, ignoring filename case. Ambiguous filenames raise an error. Preserve game subfolders when extracting textures with duplicate names.

For DDS decoding, or for separate transparency masks, install the optional Pillow dependency:

```sh
python3 -m pip install '.[textures]'
```

`--mask-channel luminance` multiplies diffuse alpha by the `TransparentColor` texture's luminance. This is opt-in because the source shader's exact mask-channel semantics have not been verified. Otherwise native diffuse alpha is preserved. Other shader texture slots remain in the CSV and material extras; normal/specular/emissive maps are not approximated as standard PBR inputs. Materials use `KHR_materials_unlit` for the flat 2D artwork.

## Rig behavior

Source skeleton hierarchy and local transforms are retained. Each part is rigidly weighted to the node identified by its `bone|mesh` name. Inverse bind matrices keep its source-space vertices in place at rest. Moving that bone moves the part and its descendants. This is a rigid cutout rig; it does not decode or claim per-vertex deforming skinning, IK, constraints or `.manimsys` logic.

Positions remain in the source XY plane with the recorded Z depth for each part. Parts remain double-sided flat surfaces, without extrusion. Coordinate units are preserved; their real-world scale has not been established. Analytic UVs are inferred from CAMEL projection records; packed overrides remain unresolved, so texture placement needs comparison with game renders.

## Installation and options

```sh
python3 -m pip install .
mmb2glb --help
```

Use `--csv` and `--report` to choose companion output paths. Existing outputs require `--force`; input assets cannot be overwritten by output paths. Parsing and serialization complete before writing outputs, and each output file is replaced atomically. The three files are not a single filesystem transaction.

Malformed or unsupported input exits with status 2 and an explanatory error. Unknown layouts are rejected rather than guessed. Only the supplied character and file revisions have been checked; compatibility with other characters, games or revisions is unverified.

## Verification

```sh
python3 -m unittest discover -s tests -v
```

The current suite has 16 tests. Tests verify sample counts, every exported vertex and index, source bounds, attachments, inverse bind matrices, buffer layout, CSV material links, selector timing, texture handling, truncated/corrupt input, strict animation rejection, and output protection. Sample regression tests require the supplied files in the repository root; texture-mask tests require optional Pillow.

The generated example was independently checked with the Khronos glTF Validator: **0 errors, 0 warnings**. It reports 322 informational notices for UV attributes unused by the untextured materials; the UVs are retained for later texture assignment. The validation output is kept with the local generated example. This validates GLB structure, not source animation fidelity.

`research/probe.py` and `research/preview.py` are development diagnostics tied to this sample; the converter itself reads counts and offsets from the files. Export follows the [Khronos glTF 2.0 specification](https://registry.khronos.org/glTF/specs/2.0/glTF-2.0.html).

Further work needed for the original full conversion request: decode ANIM packed transform values and changing key streams, verify deforming weight/attribute encoding, decode UV overrides, and compare textured/animated exports against additional source assets and game renders.
