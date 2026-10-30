import struct
from pathlib import Path
b=Path('chr_cartman.mmb').read_bytes();p=12;bones=[]
for i in range(626):
 n=struct.unpack_from('<H',b,p)[0];p+=2;name=b[p:p+n].decode();p+=n;mat=struct.unpack_from('<16f',b,p);p+=64;parent=struct.unpack_from('<h',b,p)[0];p+=2;bones.append((name,parent,mat))
p+=4;parts=[]
for i in range(322):
 n=struct.unpack_from('<H',b,p)[0];p+=2;name=b[p:p+n].decode();p+=n;h=b[p:p+144];p+=144
 count=struct.unpack_from('<I',h,63)[0];off=struct.unpack_from('<I',h,91)[0];inds=struct.unpack_from('<'+str(count)+'H',b,off)
 parts.append((name,h,inds))
if __name__=='__main__':
 print('unique total',sum(max(x[2])+1 for x in parts))
 for name,h,inds in parts[:6]:print(name,max(inds)+1, len(inds))
