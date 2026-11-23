"""Regression checks for installer routing, readiness and archive preservation."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
from unittest import mock
import zlib
import marshal
import sys
import types

ROOT=Path(__file__).resolve().parent


def module(name,relative):
    spec=importlib.util.spec_from_file_location(name,ROOT/relative)
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value


handoff=module('native_setup_handoff','Setup/native_handoff.py')
patcher=module('native_setup_patcher','Setup/update_installer.py')


def check():
    installer=ROOT.parent/'Machine Setup.exe'
    with tempfile.TemporaryDirectory(prefix='grain-setup-test-') as tmp:
        root=Path(tmp);release=root/'release with spaces';native=release/'WinUI'/'SegmentEveryGrain.exe'
        native.parent.mkdir(parents=True);native.write_bytes(b'test fixture');native.with_suffix('.dll').write_bytes(b'test fixture')
        setup=release/'Machine Setup.exe';env={'LOCALAPPDATA':str(root/'data'),'APPDATA':str(root/'roaming')}
        assert handoff.resolve_native(executable=setup,environment=env)==native
        with mock.patch.dict(os.environ,env),mock.patch.object(sys,'executable',str(setup)):
            handoff.remember_native(native)
            assert handoff.resolve_native(executable=root/'installed'/'Segment Every Grain.exe',environment=env)==native
            def start(command,**kwargs):
                assert command==[str(native)]
                assert 'segmenteverygrain.desktop' not in str(command)
                for key in ('TCL_LIBRARY','TK_LIBRARY','PYTHONHOME','PYTHONPATH'):assert key not in kwargs['env']
                assert kwargs['cwd']==str(native.parent)
                return types.SimpleNamespace()
            with mock.patch.object(handoff.subprocess,'Popen',side_effect=start):
                process=handoff.launch({'python':'unused-legacy-python.exe'})
                assert process.ready_file.name.startswith('ready-')
            native.unlink()
            try:handoff.resolve_native(executable=setup,environment=env)
            except FileNotFoundError:pass
            else:raise AssertionError('Must never fall back to the legacy editor.')
            native.write_bytes(b'test fixture')
            config={'backend':'cpu','python':'engine.exe'}
            with mock.patch.object(handoff.subprocess,'run') as run:
                handoff.shortcut(config,lambda text:None)
                assert str(native) in run.call_args.args[0]
                saved=json.loads((handoff.app_directory()/'config.json').read_text())
                assert saved['native_app']==str(native) and saved['backend']=='cpu'

        data=installer.read_bytes();source=(ROOT/'Setup/native_handoff.py').read_bytes()
        patched=patcher.patch_bytes(data,source)
        assert patcher.patch_bytes(patched,source)==patched,'Archive update must be idempotent.'
        prefix,before,_=patcher.inventory(data);newprefix,after,_=patcher.inventory(patched)
        assert prefix==newprefix
        unchanged=lambda entries:{n:(p,l,f,k) for n,p,l,f,k in entries if n not in ('desktop_launcher','native_handoff.py')}
        assert unchanged(before)==unchanged(after)
        raw=next(p for n,p,l,f,k in after if n=='desktop_launcher')
        code=marshal.loads(zlib.decompress(raw))
        launch=next(c for c in code.co_consts if isinstance(c,types.CodeType) and c.co_name=='launch')
        main=next(c for c in code.co_consts if isinstance(c,types.CodeType) and c.co_name=='main')
        assert launch.co_filename==patcher.MARKER and 'segmenteverygrain.desktop' not in launch.co_consts
        assert main.co_filename==patcher.MARKER
        assert zlib.decompress(next(p for n,p,l,f,k in after if n=='native_handoff.py'))==source
    print('PASS: native launch, relocated release, remembered target, environment cleanup, shortcut, missing-app error, archive integrity and idempotence')


if __name__=='__main__':check()
