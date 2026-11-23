# Native grain workspace

The image is the primary work surface. Warm neutral surfaces, a forest-green
accent, Segoe typography, and Fluent controls give it a coherent Windows
identity. One sidebar groups analysis, refinement and calibration. The
measurements panel remains visible and resizable. Selection is linked in both
directions, with warm gold highlighting on the image. All values are real.

The WinUI interface contains no Tkinter or webview. A Python worker reuses the
DirectML/PyTorch/SAM pipeline and numeric/export routines under Agg. Requests
and responses use private redirected stdio. Model output goes to a separate
diagnostic log so it cannot corrupt JSON protocol framing.

Grain IDs persist through save/reopen. Display geometry is simplified by 0.3 px;
source geometry determines measurements and exports. Large images use a display
scale while hit testing and ruler endpoints remain in original image pixels.
Native geometry is retained across calibration and export operations.

Undo/redo retains up to 60 session snapshots. Failed requests restore the
in-memory project. Closing checks unsaved edits and keeps an active processing
operation from being silently abandoned. Native file/folder pickers handle
open, save-as and CSV destinations. Existing projects are backward compatible;
native saves add grain IDs to GeoJSON and CSV.

The bottom progress strip receives structured phase, percent, work-count and
ETA events from the worker. Segmentation observes actual U-Net batches and SAM
prompts, mapping each patch into monotonic overall work progress. The estimate
is explicitly scoped to the current stage and is measured from completed work.
Unknown-duration phases stay indeterminate and show elapsed time. Native outline
creation yields between chunks so the progress strip can keep rendering.
Transient inference hooks are restored on success or failure; inference order
and output remain unchanged. Provisional measurements during prompt generation
do not advance the final-measurement phase.

The preserved setup executable has a source-controlled native handoff resource.
Its launch routine, Start-menu registration and startup check are retargeted to
WinUI while the original Python/package/model provisioning payloads are retained.
Setup itself always opens its wizard. The native app acknowledges readiness via
a per-launch application-data file; the wizard closes after that acknowledgment.

Independent outline/fill switches support original image, outlines, fills, or
both. Individual fill colors derive from stable grain IDs. Selection retains
its gold outline while preserving the grain's color.

Validation covers the real RX 6600 pipeline and SAM one-point prediction,
geometry/export integration, native production request paths, linked selection,
numeric sorting, filtering, ruler units, project round trips, and two window
sizes. The native UI was visually reviewed through Windows Computer Use.
Stageshow's design principles inform the hierarchy; its React illustration kit
and animation gate do not apply to this working WinUI application.
