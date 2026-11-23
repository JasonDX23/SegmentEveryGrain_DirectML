"""Retarget the preserved CPython 3.11 PyInstaller setup to the native app.

Rebuilds the CArchive, preserving every original payload except its launcher
entry. The added handoff source is readable/testable; no decompiler is required.
"""
import argparse
import hashlib
import marshal
from pathlib import Path
import shutil
import struct
import sys
import types
import zlib

MAGIC=b'MEI\014\013\012\013\016'
COOKIE=struct.Struct('!8sIIII64s')
ENTRY=struct.Struct('!iIIIBc')
MARKER='grain-native-handoff-v1'


def inventory(data):
    cookie_at=data.rfind(MAGIC)
    if cookie_at<0:raise ValueError('Not a PyInstaller setup executable.')
    magic,size,toc_at,toc_size,version,library=COOKIE.unpack_from(data,cookie_at)
    if version!=311 or sys.version_info[:2]!=(3,11):raise ValueError('Installer handoff rebuilding requires CPython 3.11.')
    if cookie_at+COOKIE.size!=len(data):raise ValueError('Unexpected bytes after the installer archive; refusing to rewrite it.')
    start=len(data)-size;cursor=start+toc_at;end=cursor+toc_size;entries=[]
    if start<0 or end!=cookie_at:raise ValueError('Invalid installer archive boundaries.')
    while cursor<end:
        length,offset,compressed,uncompressed,flag,kind=ENTRY.unpack_from(data,cursor)
        if length<ENTRY.size or cursor+length>end:raise ValueError('Invalid archive directory record.')
        name=data[cursor+ENTRY.size:cursor+length].split(b'\0',1)[0].decode('utf-8')
        if offset+compressed>toc_at:raise ValueError('Archive entry crosses the directory boundary.')
        payload=data[start+offset:start+offset+compressed]
        entries.append((name,payload,uncompressed,flag,kind));cursor+=length
    return data[:start],entries,library


def stub(name,signature,action,arguments):
    source=f'''def {name}({signature}):
    import sys
    from pathlib import Path
    path=Path(sys._MEIPASS)/'native_handoff.py'
    namespace={{'__name__':'grain_native_handoff','__file__':str(path)}}
    exec(compile(path.read_text(encoding='utf-8'),str(path),'exec'),namespace)
    return namespace[{action!r}]({arguments})
'''
    return next(c for c in compile(source,MARKER,'exec').co_consts if isinstance(c,types.CodeType))


def rewrite_entry(raw):
    code=marshal.loads(raw)
    if not isinstance(code,types.CodeType):raise ValueError('Unexpected installer launcher entry.')
    constants=[];replaced=set()
    for constant in code.co_consts:
        if isinstance(constant,types.CodeType) and constant.co_name=='launch':
            constant=stub('launch','config','launch','config');replaced.add('launch')
        elif isinstance(constant,types.CodeType) and constant.co_name=='main':
            constant=stub('main','','setup_main','Setup');replaced.add('main')
        elif isinstance(constant,types.CodeType) and constant.co_name=='Setup':
            methods=[]
            for method in constant.co_consts:
                if isinstance(method,types.CodeType) and method.co_name=='shortcut':
                    method=stub('shortcut','self, config','shortcut','config, self.log');replaced.add('shortcut')
                elif isinstance(method,types.CodeType) and method.co_name=='check_launch':
                    method=stub('check_launch','self','check_launch','self');replaced.add('check_launch')
                methods.append(method)
            constant=constant.replace(co_consts=tuple(methods))
        constants.append(constant)
    if replaced!={'launch','main','shortcut','check_launch'}:raise ValueError(f'Unrecognized installer: found {replaced}.')
    return marshal.dumps(code.replace(co_consts=tuple(constants)))


def patch_bytes(data,handoff):
    prefix,entries,library=inventory(data);patched=[];found=False
    existing=next((zlib.decompress(p) if f else p for n,p,l,f,k in entries if n=='native_handoff.py'),None)
    entry=next((zlib.decompress(p) if f else p for n,p,l,f,k in entries if n=='desktop_launcher'),None)
    if existing==handoff and entry is not None:
        code=marshal.loads(entry);routes={}
        for constant in code.co_consts:
            if not isinstance(constant,types.CodeType):continue
            if constant.co_name in ('launch','main'):routes[constant.co_name]=constant.co_filename
            if constant.co_name=='Setup':
                routes.update({m.co_name:m.co_filename for m in constant.co_consts if isinstance(m,types.CodeType) and m.co_name in ('shortcut','check_launch')})
        if routes==dict.fromkeys(('launch','main','shortcut','check_launch'),MARKER):return data
    for name,payload,length,flag,kind in entries:
        if name=='native_handoff.py':continue
        if name=='desktop_launcher':
            raw=zlib.decompress(payload) if flag else payload
            raw=rewrite_entry(raw);payload=zlib.compress(raw,9);length=len(raw);flag=1;found=True
        patched.append((name,payload,length,flag,kind))
    if not found:raise ValueError('Installer launcher was not found.')
    patched.append(('native_handoff.py',zlib.compress(handoff,9),len(handoff),1,b'b'))
    payloads=bytearray();toc=bytearray()
    for name,payload,length,flag,kind in patched:
        encoded=name.encode('utf-8')+b'\0';record_size=((ENTRY.size+len(encoded)+15)//16)*16
        toc.extend(ENTRY.pack(record_size,len(payloads),len(payload),length,flag,kind))
        toc.extend(encoded);toc.extend(b'\0'*(record_size-ENTRY.size-len(encoded)));payloads.extend(payload)
    size=len(payloads)+len(toc)+COOKIE.size
    output=prefix+payloads+toc+COOKIE.pack(MAGIC,size,len(payloads),len(toc),311,library)
    # Independently reread and verify all unchanged members before publishing.
    _,checked,_=inventory(output);expected={n:(p,l,f,k) for n,p,l,f,k in entries if n not in ('desktop_launcher','native_handoff.py')}
    actual={n:(p,l,f,k) for n,p,l,f,k in checked if n not in ('desktop_launcher','native_handoff.py')}
    if actual!=expected:raise ValueError('An unrelated installer payload changed.')
    return bytes(output)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--installer',type=Path,required=True)
    parser.add_argument('--backup-dir',type=Path,required=True)
    args=parser.parse_args();path=args.installer.resolve();data=path.read_bytes()
    handoff=Path(__file__).with_name('native_handoff.py').read_bytes()
    patched=patch_bytes(data,handoff)
    if patched==data:print(f'Native setup handoff already current: {path.name}');return
    backup=args.backup_dir.resolve();backup.mkdir(parents=True,exist_ok=True)
    saved=backup/(path.stem+'-'+hashlib.sha256(data).hexdigest()[:12]+'.exe')
    if not saved.exists():shutil.copy2(path,saved)
    temporary=path.with_suffix('.exe.native-update')
    try:temporary.write_bytes(patched);temporary.replace(path)
    finally:temporary.unlink(missing_ok=True)
    print(f'Updated native setup handoff: {path.name}; original saved to {saved}')


if __name__=='__main__':main()
