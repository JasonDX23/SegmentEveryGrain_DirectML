param([switch]$SkipLauncher)
$ErrorActionPreference='Stop'
$workspacePath=Split-Path -Parent $PSScriptRoot
$localDotnet=Join-Path $workspacePath '.tools\dotnet\dotnet.exe'
$dotnetPath=if(Test-Path -LiteralPath $localDotnet){$localDotnet}else{'dotnet'}
& $dotnetPath publish (Join-Path $PSScriptRoot 'Grain\Grain.csproj') -c Release -p:Platform=x64 -o (Join-Path $workspacePath 'WinUI')
if($LASTEXITCODE -ne 0){throw 'WinUI publish failed.'}
if(-not $SkipLauncher){
    Push-Location (Join-Path $PSScriptRoot 'Launcher')
    try {
        New-Item -ItemType Directory -Force 'bin' | Out-Null
        & windres launcher.rc -O coff -o 'bin\launcher.res'
        if($LASTEXITCODE -ne 0){throw 'Launcher resource build failed.'}
        & gcc launcher.c 'bin\launcher.res' -municode -mwindows -O2 -s -static-libgcc -lshell32 -o 'bin\Segment Every Grain.exe'
        if($LASTEXITCODE -ne 0){throw 'Launcher build failed.'}
        $mainExe=Join-Path $workspacePath 'Segment Every Grain.exe'
        $setupExe=Join-Path $workspacePath 'Machine Setup.exe'
        if(-not(Test-Path -LiteralPath $setupExe)){
            if(-not(Test-Path -LiteralPath $mainExe)){throw 'The original setup executable is missing.'}
            Copy-Item -LiteralPath $mainExe -Destination $setupExe
        }
        $setupPython=Join-Path $env:LOCALAPPDATA 'SegmentEveryGrainDesktop\runtime\Scripts\python.exe'
        if(-not(Test-Path -LiteralPath $setupPython)){$setupPython='python'}
        & $setupPython (Join-Path $PSScriptRoot 'Setup\update_installer.py') --installer $setupExe --backup-dir (Join-Path $workspacePath 'backups\setup-handoff')
        if($LASTEXITCODE -ne 0){throw 'Setup handoff update failed. CPython 3.11 is required; use the private setup runtime or install Python 3.11 for building.'}
        Copy-Item -LiteralPath 'bin\Segment Every Grain.exe' -Destination $mainExe
    }finally{Pop-Location}
}
Write-Output 'Native WinUI app published. Launch Segment Every Grain.exe from the workspace root.'
$shortcutPath=Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Segment Every Grain.lnk'
$shell=New-Object -ComObject WScript.Shell
$shortcut=$shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath=Join-Path $workspacePath 'Segment Every Grain.exe'
$shortcut.WorkingDirectory=$workspacePath
$shortcut.Description='Native WinUI grain segmentation and measurement workspace'
$shortcut.IconLocation=(Join-Path $workspacePath 'Segment Every Grain.exe')+',0'
$shortcut.Save()
