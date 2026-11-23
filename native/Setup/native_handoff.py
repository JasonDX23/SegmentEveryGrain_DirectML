"""Native workspace handoff embedded into the preserved machine installer.

The installer remains responsible for Python, packages and weights. Every app
launch and Start-menu shortcut resolves to WinUI, never the legacy editor.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid


def app_directory():
    return Path(os.environ.get('LOCALAPPDATA',Path.home()))/'SegmentEveryGrainDesktop'


def resolve_native(config=None,executable=None,environment=None):
    config=config or {};environment=os.environ if environment is None else environment
    executable=Path(executable or sys.executable).resolve()
    app=Path(environment.get('LOCALAPPDATA',Path.home()))/'SegmentEveryGrainDesktop'
    candidates=[]
    if environment.get('SEGMENTEVERYGRAIN_NATIVE_APP'):
        candidates.append(Path(environment['SEGMENTEVERYGRAIN_NATIVE_APP']))
    # Prefer this extracted release over a previously remembered installation.
    candidates.append(executable.parent/'WinUI'/'SegmentEveryGrain.exe')
    if config.get('native_app'):candidates.append(Path(config['native_app']))
    marker=app/'native-app.json'
    try:candidates.append(Path(json.loads(marker.read_text(encoding='utf-8'))['native_app']))
    except (OSError,ValueError,KeyError,TypeError):pass
    for candidate in candidates:
        candidate=candidate.resolve()
        if candidate.is_file() and (candidate.parent/'SegmentEveryGrain.dll').is_file():
            return candidate
    raise FileNotFoundError('The native WinUI workspace was not found. Extract the complete release and keep the WinUI folder beside Machine Setup.exe. Setup will not open the old editor.')


def remember_native(target):
    app=app_directory();app.mkdir(parents=True,exist_ok=True)
    (app/'native-app.json').write_text(json.dumps({'native_app':str(target)},indent=2),encoding='utf-8')


def launch(config):
    target=resolve_native(config);remember_native(target)
    app=app_directory();ready=app/f'ready-{uuid.uuid4().hex}.json'
    environment=os.environ.copy()
    for key in ('TCL_LIBRARY','TK_LIBRARY','PYTHONHOME','PYTHONPATH'):
        environment.pop(key,None)
    environment['SEGMENTEVERYGRAIN_READY_FILE']=str(ready)
    if getattr(sys,'frozen',False):
        import ctypes
        ctypes.windll.kernel32.SetDllDirectoryW(None)
    with (app/'desktop.log').open('a',encoding='utf-8') as log:
        log.write(f'Opening native WinUI workspace: {target}\n');log.flush()
        process=subprocess.Popen([str(target)],cwd=str(target.parent),env=environment,
            stdout=log,stderr=log,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    process.ready_file=ready
    process.launch_started=time.monotonic()
    return process


def shortcut(config,log):
    target=resolve_native(config);remember_native(target)
    config['native_app']=str(target)
    app=app_directory()
    (app/'config.json').write_text(json.dumps(config,indent=2),encoding='utf-8')
    script=app/'create_shortcut.ps1'
    script.write_text('param($Target,$Shortcut)\n$s=(New-Object -ComObject WScript.Shell).CreateShortcut($Shortcut)\n$s.TargetPath=$Target\n$s.WorkingDirectory=Split-Path -Parent $Target\n$s.Save()\n',encoding='utf-8')
    destination=Path(os.environ['APPDATA'])/'Microsoft/Windows/Start Menu/Programs/Segment Every Grain.lnk'
    subprocess.run(['powershell','-NoProfile','-ExecutionPolicy','Bypass','-File',str(script),str(target),str(destination)],
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),check=True)
    log('Added the native WinUI workspace to the Windows Start menu.')


def setup_main(setup_class):
    import tkinter as tk
    from tkinter import messagebox
    root=tk.Tk()
    config={}
    try:config=json.loads((app_directory()/'config.json').read_text(encoding='utf-8'))
    except (OSError,ValueError):pass
    try:remember_native(resolve_native(config))
    except Exception as exc:
        root.withdraw();messagebox.showerror('Native application files missing',str(exc),parent=root);root.destroy();return
    setup_class(root)
    root.mainloop()


def check_launch(setup):
    from tkinter import messagebox
    process=setup.launched_process
    if process.ready_file.is_file():
        process.ready_file.unlink(missing_ok=True);setup.root.destroy();return
    if process.poll() is not None:
        text=(app_directory()/'desktop.log').read_text(encoding='utf-8',errors='replace')[-1800:]
        messagebox.showerror('Native app could not start',text,parent=setup.root)
        setup.status.set('Launch failed. Check desktop.log and winui-error.log in application data.');return
    if time.monotonic()-process.launch_started>180:
        setup.status.set('The native app is taking longer to start. Check its window and application-data logs.');return
    setup.root.after(300,setup.check_launch)
