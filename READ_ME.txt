SEGMENT EVERY GRAIN — NATIVE WINUI 3 WORKSPACE

For the complete setup instructions, illustrated tutorial, troubleshooting,
developer guide and GitHub release preparation, see README.md and
docs\PUBLISHING.md. This text file is a short offline quick reference.

START
Double-click Segment Every Grain.exe. Keep the WinUI folder beside it.
The interface is native C# / WinUI 3. It uses the existing private Python
segmentation engine; no browser, notebook server, Tkinter window, or separate
.NET installation is needed. Image processing stays local.

FIRST-TIME SETUP
Run Machine Setup.exe, or Workspace options > Machine setup in the app.
Install your GPU/CPU environment and the Detailed (Large) or Fast (Tiny) model.
Internet is needed for initial dependencies and model downloads. The original
setup utility now opens the native WinUI workspace after installation and
closes once the workspace is ready. Open existing installation also opens WinUI.
Machine Setup.exe always opens setup; Segment Every Grain.exe opens the app.

WORKFLOW
1. Open image. Choose a model, minimum area, and processing device.
2. Segment image. Outlines and the measurements table appear together.
   Start with an empty canvas prepares manual segmentation without auto masks.
   Outlines and Color fill are independent switches above the image. Color fill
   gives grains stable individual colors; either view can be used on its own.
3. Select grains in the image or table. Ctrl+click selects multiple grains.
   Delete removes selections; Merge joins touching/overlapping selections.
   Undo/Redo restores mask corrections and ruler calibration changes.
4. Use the canvas toolbar to select, pan, add a grain with one click, or place
   foreground/background points. To replace an outline, delete it, place points
   inside/outside it, then choose Correct an outline > Create from points.
5. Enter the known ruler length and unit. Choose Draw reference and drag between
   matching ruler marks. Apply length to reference updates an existing ruler.
   Remove calibration restores pixel units. Calibration does not fix perspective.
6. Inspect Grain measurements. Click headings to sort numerically; Selected only
   filters to selected grains. Scroll sideways for every CSV field. Drag the
   divider between image and table to resize the panes.
7. Export CSV writes ALL current grain measurements, including stable grain_id
   values matching the image. Selected only affects the display, not the export.
   Table numbers use six significant digits; CSV retains full precision.
8. Save project writes image, masks, measurements and ruler settings. Later saves
   update that project. Workspace options > Save project as writes a new copy.
   Open project restores project.json from the old or native editor. Undo history
   belongs to the current session and is not saved into the project.

SHORTCUTS
Ctrl+O: image. Ctrl+Shift+O: project. Ctrl+S: save. Ctrl+Z/Y: undo/redo.
V: select. H: pan by dragging. A: add grain. F: fit image. Delete: delete masks.
Escape: clear selection and points. Ctrl+wheel or touch pinch: zoom.
Text and numeric fields retain their editing shortcuts.

EXPORTS
image.png: original RGB image.
grains.geojson: edited outlines in image pixels, with grain_id properties.
mask.png: semantic training mask (background/grain/boundary), not instance IDs.
measurements.csv: grain IDs, shape metrics, centroids and color statistics.
Sizes use mm/cm when calibrated, otherwise pixels. Areas use squared units.
Centroids stay in image pixels. Orientation is in radians.
project.json: model, unit and ruler settings for reopening.
run.json: device, grain count, timing and measurement units.

ENGINE
The bottom progress bar covers engine startup, image/project loading, model
loading, segmentation, edits, calibration, exporting, saving, and drawing the
result overlays. It shows the current stage and completed work where available.
Remaining-time estimates apply to the CURRENT STAGE and use measured throughput;
they adapt as processing continues. Unknown-duration phases show an animated
bar, elapsed time, and Estimating time remaining instead of a guessed countdown.

%LOCALAPPDATA%\SegmentEveryGrainDesktop\runtime: private Python and packages.
%LOCALAPPDATA%\SegmentEveryGrainDesktop\config.json: machine settings.
%LOCALAPPDATA%\segmenteverygrain\models: model cache.
%LOCALAPPDATA%\SegmentEveryGrainDesktop\winui-worker.log: engine diagnostics.
%LOCALAPPDATA%\SegmentEveryGrainDesktop\winui-error.log: UI diagnostics.
The Python worker communicates over redirected standard streams; no network
service is started. Large images use overlapping patches and can take several
minutes. Failed requests preserve the active in-memory project. Wait for current
processing to finish before closing. Unsaved changes are checked before leaving.

SOURCE & BUILD
native\Grain: WinUI interface, native image editor and Python worker.
native\Launcher: Windows launcher; --setup opens the preserved installer.
native\Setup: native launch handoff and a CPython 3.11 installer-archive updater.
native\Build.ps1: publishes WinUI and rebuilds the root launcher.
Build requirements: .NET 8 SDK, NuGet access, GCC and windres for the launcher.
-SkipLauncher publishes only the C# app. The build's private SDK is in .tools;
it is not needed to run the release. WinUI contains its .NET and Windows App SDK
runtimes. The Python environment/model weights still need first-time setup.

VALIDATION
The RX 6600 DirectML pipeline was exercised with full-image segmentation and
SAM point-based mask creation. Checks cover geometry, stable grain IDs, CSV
parity, calibration, delete/merge/undo/redo, project save/reopen, selection-linked
native tables, numeric sorting, filtering, and two window sizes. Reports are in
verification. Run native\test_worker.py with the private Python to repeat the
engine checks; add --gpu --image <local-image-path> for inference. Use a
grain-rich sample to exercise time estimates. CPU speed was not benchmarked here.
This is a local build, not an official upstream release.

LICENSES / UPSTREAM
Upstream notices are retained alongside the app.
segmenteverygrain: https://github.com/zsylvester/segmenteverygrain
SAM 2: https://github.com/facebookresearch/sam2
uv: https://github.com/astral-sh/uv
Windows App SDK: https://github.com/microsoft/WindowsAppSDK
.NET: https://github.com/dotnet/runtime
