# Publishing on GitHub

This guide separates the **source repository** from a **downloadable Windows application**. The source checkout rebuilds the native frontend and launcher; the release must also supply the preserved setup utility and the complete published app.

## 1. Review the source repository

The root `.gitignore` excludes generated applications, model weights, private build tools, local results/recovery projects, logs, and machine validation reports. It does not remove local files.

Include the native source, documentation, screenshot, build/test scripts, and applicable license notices. The legacy `src/` overrides may be retained for reference; they are not used by the WinUI app.

Before committing, inspect the proposed files:

```powershell
git status --short
git diff --cached --stat
```

If you have not created a Git repository yet, initialize it first with `git init`. No repository name, remote, or account is assumed by these instructions.

Keep the following out of source history:

| Local content | Why it stays separate |
| --- | --- |
| `WinUI/` and the two root EXEs | Generated/shipped binaries belong in release assets. |
| `.tools/`, Python virtual environments, `bin/`, `obj/` | Local tooling and generated build files. |
| Model weights and package archives | Large downloaded assets, not the app's source. |
| `Recovered Projects/`, `backups/`, `verification/` | User work, test images, generated data and machine-specific reports. |
| Diagnostic logs and machine configuration | Local paths, adapter settings, and diagnostic context. |

Ignoring a file does not untrack it if it was already committed. Review the actual staged file list before publishing.

## 2. Declare the source and license scope

The checkout includes the readable native handoff and archive-update recipe in `native/Setup/`. That recipe updates a supplied `Machine Setup.exe`; it does not build the original provisioning engine from scratch. The original provisioning source and the complete source/build recipe for its patched Python packages are not included. The native app currently expects the setup-provided engine, including `segmenteverygrain 0.6.0+directml.5`.

State this limitation in the release notes, as the README does. A full source-reproducible distribution would also need those installer/backend sources, dependency pins, and a documented way to reproduce the patched artifacts. Do not describe an arbitrary `pip install segmenteverygrain` as equivalent to this engine.

Choose a license for the newly written desktop/launcher code and add its top-level `LICENSE` before presenting that code as licensed open source. Preserve the existing third-party notices and any applicable notices accompanying the installed runtime/model components. This documentation does not choose a project license on the owner's behalf.

## 3. Build and check the Windows application

1. Keep the preserved **Machine Setup.exe** at the repository root.
2. Complete engine setup on the test machine.
3. Close running app windows to release locked build/output files.
4. Run `native\Build.ps1` from the repository root. CPython 3.11 is needed to update setup's archive; the private setup runtime is used when available.
5. Run the progress/worker tests documented in the README.
6. Open the root launcher and exercise image opening, segmentation, fill/outline switches, an edit with undo, ruler calibration, CSV export, and project save/reopen.
7. Open **Machine Setup.exe** directly: it should show setup. Check **Open existing installation** and **Install & open app** hand off to WinUI, and that the Start-menu shortcut targets the native workspace.

Also test the ZIP on another Windows account or machine before publishing a release. That installation path has not been established by simply launching a build that already has a configured runtime.

Check that the published directory contains the application's compiled resources:

```powershell
Test-Path '.\WinUI\SegmentEveryGrain.exe'
Test-Path '.\WinUI\SegmentEveryGrain.pri'
Test-Path '.\WinUI\MainWindow.xbf'
Test-Path '.\WinUI\Backend\worker.py'
Test-Path '.\WinUI\Backend\progress.py'
```

All should return `True`. Keep the rest of the published DLLs/runtime files as well.

## 4. Assemble a clean release ZIP

Run this in PowerShell at the repository root after a successful build. It packages explicit release paths rather than the whole working directory:

```powershell
$releaseName = 'SegmentEveryGrain-Windows-x64.zip'
$releaseItems = @(
    'Segment Every Grain.exe'
    'Machine Setup.exe'
    'WinUI'
    'README.md'
    'READ_ME.txt'
    'docs'
    'segmenteverygrain-LICENSE.txt'
    'SAM2-LICENSE.txt'
    'uv-LICENSE-APACHE.txt'
    'uv-LICENSE-MIT.txt'
)

foreach ($item in $releaseItems) {
    if (-not (Test-Path -LiteralPath $item)) {
        throw "Missing release item: $item"
    }
}

# Include the application license once you have selected and added it.
if (Test-Path -LiteralPath 'LICENSE') {
    $releaseItems += 'LICENSE'
}

# Compress-Archive reports an error if the destination already exists.
# Choose another release filename instead of replacing an archive unintentionally.
Compress-Archive -Path $releaseItems -DestinationPath $releaseName
Get-FileHash -LiteralPath $releaseName -Algorithm SHA256
```

This excludes user projects, recovery copies, logs, model caches, and the local SDK. It includes the README's referenced screenshot by including `docs/`.

Extract the finished ZIP into a new folder and launch it from there. Verify **Machine setup** can be reached, the native launcher works, and the `WinUI/` directory has not been flattened or omitted. Setup downloads the private Python environment and selected SAM weights; the app ZIP is not an offline installer for those downloads.

## 5. Create the GitHub release

After creating your GitHub repository and pushing the reviewed source:

1. Open **Releases → Draft a new release**.
2. Choose your version tag and write release notes describing the changes.
3. Attach the Windows application ZIP as a release asset.
4. Include its SHA-256 checksum in the release notes.
5. State the tested Windows/GPU configuration, setup/network requirements, and known limitations.
6. Publish when your source, license choice, and packaged-app checks are ready.

GitHub automatically adds source archives. Explain that users who want to run the application should download your **Windows application ZIP**, not those source archives.

Suggested release-note topics:

- Native WinUI interface and included editing/measurement features.
- First-time setup through the included `Machine Setup.exe`.
- GPU/CPU configuration and which hardware was actually tested.
- Current-stage ETA behavior and unknown-duration phases.
- Existing project compatibility and the added grain ID fields.
- The source/build limitations of the preserved installer and patched engine.

This guide prepares the files and instructions; it does not create a remote repository or publish a release automatically.
