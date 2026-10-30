# Reverse-engineering notes

These observations come from the five supplied Cartman files. **Observed** means structurally verified against this sample; semantic interpretations remain hypotheses unless explicitly tested. Do not apply layouts to other Snowdrop games without checking them.

## MMB CB

All demonstrated numbers are little-endian.

| Location | Observed layout |
| --- | --- |
| 0 | `MMB CB` (hex `4d 4d 42 cb`) |
| 4 | uint32 complete file size: 343604 |
| 8 | uint32 skeleton-node count: 626 |
| 12 onward | Repeated: uint16 UTF-8 byte count, name bytes, 16 float32 matrix elements, int16 parent index |
| 48020 | uint32 part count: 322 |
| 48024 onward | Repeated: uint16 name length, UTF-8 `node\|mesh` name, 144 bytes of part metadata |
| 102386 onward | Contiguous uint16 triangle index blocks; end exactly matches file length |

Skeleton matrices have translation at elements 12–14 and affine homogeneous entries; the converter treats them as column-major local matrices. Parents precede children, with -1 marking roots. The sample has two roots, `cartman` and `__BoneTransforms`.

Part metadata offsets are relative to the byte immediately following its name:

| Offset | Layout / interpretation |
| --- | --- |
| 0 | 6 float32 XYZ minimum/maximum bounds |
| 24 | Other float32 bounds/radius data; semantics not established |
| 48 | uint16 0, uint16 1, uint16 39, uint32 1, uint32 1, uint8 F0; invariant in this sample |
| 63 | uint32 triangle index count; **not vertex count** |
| 75 | Repeated index count |
| 87 | uint32 index byte size |
| 91 | uint32 absolute index file offset |
| 95 | Repeated byte size |
| 111 | uint16 3 and additional fields with unverified semantics |
| 124 | uint32 2 (index width) |
| 132 | uint32 index count, uint32 zero, uint32 index byte size |

All 322 parts have equal minimum and maximum Z. The unique vertex count of each part equals `max(indices) + 1`, and its CAMEL vertex range matches that count. Total indices: 120609. Total unique per-part vertices: 36196.

## CAMEL v3

| Byte position in sample | Layout |
| --- | --- |
| 0 | uint32 version 3 |
| 4 | uint32 part count 322 |
| 8 | uint32 packed word count 11642 |
| 12 | 11642 uint32 packed words (46568 bytes) |
| 46580 | 322 records of 152 bytes |
| 95524 | uint32 vertex count 36196 |
| 95528 | 36196 float32 XY pairs |
| 385096 | uint32 depth count 322, then 322 float32 depths |
| 386388 | uint32 count 1307, then 1307 packed uint32 values |
| 391620 | uint32 count 1132, then 1132 uint32 values (zero in this sample) |

The record format is `<12f7I2H16f2f` (152 bytes):

| Record offset | Interpretation |
| --- | --- |
| 0 | 2 float32 UV projection origin (inferred) |
| 8 | 2 float32 UV offsets (inferred; zero in sample) |
| 16 | 4 float32 U projection direction and scale (inferred) |
| 32 | 4 float32 V projection direction and scale (inferred) |
| 48 | Four uint32 packed-word start/count values for two streams |
| 64 | uint32 first vertex in global XY table |
| 68 | uint32 material index; equals part index in this sample |
| 72 | uint32 offset into the packed 1307-value table; exact semantics unresolved |
| 76 | Two uint16 flags: `(0,1)` or `(5,1)` |
| 80 | 16 float32 matrix values; meaning unresolved, retained as metadata |
| 144 | 2 float32 UV axis signs, `(-1,1)` in this sample |

The first packed-word stream has sizes consistent with three bits per vertex; the second with six bits per vertex. Their semantics, the 1307 packed values, and the final auxiliary table remain unresolved. No colors, UV overrides, or deforming weights are fabricated from these fields. The original bytes are retained in the JSON report.

For every mesh, XY ranges **exactly** reproduce the MMB XY bounds within float32 tolerance. The depth array agrees with both MMB Z bounds. This independently confirms the geometry layout and matching, including vertices for alternate poses.

UV projection currently uses:

```text
d = XY * axisSigns - origin
u = dot(d, uDirection.xy) * uDirection.w + offset.x
v = dot(d, vDirection.xy) * vDirection.w + offset.y
```

This is an inferred analytic projection. Texture pixels were not supplied, so orientation, overrides, and source shader sampling have not been visually verified.

## Editor data

The file starts with uint32 material count, followed by one record per material:

```text
uint32 recordVersion = 1
uint16 + bytes materialName
uint16 + bytes shaderName
uint32 textureSlotCount
repeat slots:
    uint16 + bytes slotName
    uint16 + bytes gameTexturePath
```

The 322 material records end at byte 141315. Following them are `14 * materialCount` zero bytes, uint32 revision 3, and 322 parameter records of `<I26f` (108 bytes). Each starts with uint32 1. The first three floats are interpreted as RGB tint; the fourth is consistently about 0.8 and is **not assumed to be opacity**. Remaining parameters are retained but not assigned unverified shader meanings.

There are five texture slots per material, totaling 1610 links and 80 distinct paths. Material indices from CAMEL determine the CSV mapping; texture paths are not assigned using nearest names or file order heuristics.

## ANIM v14

Header:

```text
0x00  ANIM
0x04  uint16 version = 14
0x06  uint16 flags = 3
0x08  float32 fps = 24
0x0c  float32 duration = 3.7916667
0x10  uint32 frame count = 92
0x14  uint32 workspace size = 1248 (not an absolute file offset)
0x18  three uint32 fields (semantics unresolved)
0x24  uint32 named-track count = 124
0x28  41 additional header bytes (semantics unresolved)
0x51  TYPE section
```

Section sequence:

```text
TYPE DTRA DROT DSCA
TRAI TRAD CHAK CAKS
ROTI ROTD CHAK CAKS
SCAI SCAD CHAK CAKS
NAME PART IKEF IKEA
```

- `TYPE` has 124 bytes, all 5 in this sample.
- `DTRA` has 32 bytes; `DROT` is empty; `DSCA` has 8 bytes. Packed numeric encoding is unresolved.
- `TRAI`, `ROTI`, and `SCAI` each contain 124 uint16 entries.
- `FFFF` denotes no explicit track (inferred).
- `FFFE` in SCAI selects zero scale, used to hide alternate views/parts (inferred from the consistent cutout selector hierarchy).
- `8000+n` references constant packed data (inferred). Four translation constants and one nonzero scale constant are referenced.
- `TRAD`, `ROTD`, `SCAD`, and `CHAK` are empty. `CAKS` holds two zero bytes per occurrence. There is **no changing-keyframe example** here.
- `NAME` contains 124 NUL-terminated names, including the non-model state track `anm_state`.
- `PART` and `IKEF` each contain uint32 zero in the sample.
- `IKEA` contains a uint32 zero, uint32 path-byte count, NUL-terminated source path, one zero byte, uint32 metadata count and that many uint32 values, uint32 track count, uint32 runtime-block length and the runtime block. The reader validates the counted ranges and exact end of file.

The repeated CHAK/CAKS names must be parsed in sequence rather than stored in a tag-keyed dictionary. Index table sizes are computed from the header count; boundaries of unresolved constant sections are inferred from the following expected tag. This is intentionally limited: tag-like bytes in an unknown packed representation may cause an explicit parse failure, and unsupported animation streams are never exported as valid motion.

Default strict mode rejects this sample's unresolved packed translation and scale constants. Explicit `visibility` mode exports its 95 zero-scale selectors and holds other nodes at their skeleton bind transforms. The resulting clip is marked partial, lists omitted transform tracks, and stores original DTRA/DROT/DSCA bytes in GLB animation extras. It must not be treated as a full pose or motion conversion.

## Other companions

`.manimsys` starts with a `FF BVM` serialized object and includes animation-state/layer configuration. It is not decoded or needed for the structural model export. This converter does not execute or approximate that state machine. `.editordata` and `.cameldata` are required for the implemented conversion route.

## Remaining validation

The structural geometry is verified against all supplied bounds and indices. Rigid bone attachment is inferred from the part names, with correct inverse bind cancellation tested mathematically. Source geometry rendered with flat material tints produces a recognizable front silhouette when the sample selector clip is applied. No game textures or additional animated examples were available to validate appearance, UV overrides, packed transform codecs, or deforming weights.
