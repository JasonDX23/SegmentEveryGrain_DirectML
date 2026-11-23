"""Exercise the real preserved install-button worker, then launch and await WinUI.

This intentionally reruns setup with the current machine settings. Run with the
base Python 3.11 interpreter, not the private environment being configured.
No Windows input automation or mock package installation is involved.
"""
import importlib.util
import json
import marshal
import os
from pathlib import Path
import queue
import shutil
import sys
import time
import zlib

ROOT=Path(__file__).resolve().parent.parent
spec=importlib.util.spec_from_file_location('setup_update',ROOT/'native/Setup/update_installer.py')
updater=importlib.util.module_from_spec(spec);spec.loader.exec_module(updater)


class Value:
    def __init__(self,value=None):self.value=value
    def get(self):return self.value
    def set(self,value):self.value=value
    def state(self,*args,**kwargs):pass
    def configure(self,*args,**kwargs):pass
    def start(self,*args,**kwargs):pass
    def stop(self,*args,**kwargs):pass


class InlineThread:
    def __init__(self,target,**kwargs):self.target=target
    def start(self):self.target()


def main():
    if sys.version_info[:2]!=(3,11):raise RuntimeError('Use CPython 3.11.')
    installer=ROOT/'Machine Setup.exe'
    app=Path(os.environ['LOCALAPPDATA'])/'SegmentEveryGrainDesktop'
    config=json.loads((app/'config.json').read_text(encoding='utf-8'))
    if Path(sys.executable).resolve()==Path(config['python']).resolve():raise RuntimeError('Use base Python; setup updates the private environment.')
    assets=ROOT/'.tools/setup-validation-assets';assets.mkdir(parents=True,exist_ok=True)
    _,entries,_=updater.inventory(installer.read_bytes())
    keep={'uv.exe','native_handoff.py','wheels/sam_2-1.0+directml-py3-none-any.whl',
          'wheels/segmenteverygrain-0.6.0+directml.5-py3-none-any.whl'}
    code=None
    for name,payload,size,flag,kind in entries:
        if name in keep:
            path=(assets/name).resolve()
            if not path.is_relative_to(assets.resolve()):raise RuntimeError('Invalid asset path')
            path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(zlib.decompress(payload) if flag else payload)
        if name=='desktop_launcher':code=marshal.loads(zlib.decompress(payload) if flag else payload)
    if code is None:raise RuntimeError('Missing launcher')
    backup=ROOT/'backups/setup-handoff';backup.mkdir(parents=True,exist_ok=True)
    saved=backup/'config-before-install-test.json'
    if not saved.exists():shutil.copy2(app/'config.json',saved)
    sys._MEIPASS=str(assets);sys.frozen=True;sys.executable=str(installer)
    namespace={'__name__':'installer_integration_test','__file__':str(installer)}
    exec(code,namespace)
    namespace['RESOURCES']=assets
    native_spec=importlib.util.spec_from_file_location('setup_native_handoff',assets/'native_handoff.py')
    handoff=importlib.util.module_from_spec(native_spec);native_spec.loader.exec_module(handoff)
    handoff.remember_native(ROOT/'WinUI/SegmentEveryGrain.exe')
    setup=object.__new__(namespace['Setup'])
    setup.root=None;setup.running=False;setup.cancelled=False;setup.process=None
    setup.backend=Value(config['backend']);setup.adapter=Value(config.get('adapter_name',''))
    setup.variant=Value(config.get('variant','large'));setup.status=Value()
    setup.install_button=Value();setup.cancel_button=Value();setup.progress=Value();setup.events=queue.Queue()
    original_thread=namespace['threading'].Thread
    started=time.monotonic()
    try:
        namespace['threading'].Thread=InlineThread
        setup.install()
    finally:namespace['threading'].Thread=original_thread
    installed=None
    while not setup.events.empty():
        kind,payload=setup.events.get()
        if kind=='error':raise RuntimeError(payload)
        if kind=='log':print(payload,flush=True)
        if kind=='installed':installed=payload
    if installed is None:raise RuntimeError('The installer did not complete.')
    process=namespace['launch'](installed)
    deadline=time.monotonic()+150
    while time.monotonic()<deadline:
        if process.ready_file.is_file():break
        if process.poll() is not None:raise RuntimeError('Native app exited before readiness.')
        time.sleep(.2)
    else:raise TimeoutError('Native readiness handshake timed out.')
    ready=json.loads(process.ready_file.read_text());process.ready_file.unlink()
    if ready!={'ready':True,'ui':'winui3'}:raise RuntimeError(f'Unexpected workspace: {ready}')
    report={'passed':True,'install_button_worker':True,'native_ready_handshake':True,
            'backend':installed['backend'],'variant':installed['variant'],'seconds':round(time.monotonic()-started,2),
            'native_app':installed['native_app']}
    (ROOT/'verification/setup-native-install.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
