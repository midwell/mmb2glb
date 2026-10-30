"""Diagnostic flat-color source preview; requires Pillow, not part of converter."""
from PIL import Image, ImageDraw
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from mmb2glb.formats import read_mmb, read_cameldata, read_editordata, read_anim
bones, parts=read_mmb('chr_cartman.mmb')
read_cameldata('chr_cartman.cameldata',parts)
materials=read_editordata('chr_cartman.editordata',len(parts))
a=read_anim('anm_cartman_base_idle_front.anim'); visibility=a.visibility()
hidden={}
for bone in bones:
 hidden[bone.name] = not visibility.get(bone.name,True) or (bone.parent>=0 and hidden[bones[bone.parent].name])
visible=[p for p in parts if not hidden[p.name.rsplit('|',1)[0]]]
image=Image.new('RGB',(900,1000),'#eef0f4');draw=ImageDraw.Draw(image)
for part in sorted(visible,key=lambda p:p.vertices[0][2]):
 color=tuple(round(c*255) for c in materials[part.material].color)
 points=[(450+x*290,900-y*290) for x,y,z in part.vertices]
 for j in range(0,len(part.indices),3):
  draw.polygon([points[k] for k in part.indices[j:j+3]],fill=color)
draw.text((24,24),'Source geometry diagnostic: flat tints, no game textures',fill='#333333')
image.save('examples/cartman.preview.png')
print('visible parts',len(visible))
