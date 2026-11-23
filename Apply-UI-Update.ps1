$ErrorActionPreference = 'Stop'
$packagePath = Join-Path $env:LOCALAPPDATA 'SegmentEveryGrainDesktop\runtime\Lib\site-packages\segmenteverygrain'
if (-not (Test-Path -LiteralPath (Join-Path $packagePath 'desktop.py'))) {
    throw 'Run first-time app setup before applying the UI update.'
}
$backupPath = Join-Path $PSScriptRoot ('backups\runtime-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $backupPath -Force | Out-Null
foreach ($name in @('desktop.py', 'inference.py')) {
    Copy-Item -LiteralPath (Join-Path $packagePath $name) -Destination $backupPath
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot "src\segmenteverygrain\$name") -Destination (Join-Path $packagePath $name)
}
Write-Output "UI update installed. Reopen Segment Every Grain. Original files: $backupPath"
