# HDevEngine Python Runner

Use `scripts/hdev_call.py` to call local HDevelop `.hdev` procedures directly through HALCON/Python HDevEngine. Prefer this runner for debugging and unit tests because it avoids `main()` dispatchers, global variables, and `hrun -D` parameter plumbing.

## Prerequisites

- Native HALCON runtime and license installed.
- MVTec HALCON/Python package available to the Python interpreter, typically `mvtec-halcon`.
- The Python package version must match or be compatible with the installed HALCON runtime.

The runner imports `halcon` lazily. If setup is missing, it emits JSON with a clear setup error instead of failing at Python module import time.

## Commands

List local procedures:

```bash
python scripts/hdev_call.py program.hdev --list-procedures
```

Run one procedure:

```bash
python scripts/hdev_call.py program.hdev --procedure inspect_part --image Image=images/part.png --input Threshold=128
```

Run all local unit tests:

```bash
python scripts/hdev_call.py program.hdev --match '^test_' --input FixtureRoot=./images --input ResultDir=./result --input DebugLevel=0
```

Run selected tests by name pattern:

```bash
python scripts/hdev_call.py program.hdev --match 'edge|contrast' --input FixtureRoot=./images --input ResultDir=./result --input DebugLevel=0
```

## Parameter Passing

Use `--input Name=Value` for control parameters. Values support:

- integers: `--input Threshold=128`
- floats: `--input Scale=1.5`
- booleans: `--input Debug=true`
- JSON arrays/objects: `--input Limits='[10, 200]'`
- quoted strings: `--input Mode=\"strict\"`
- raw strings as fallback: `--input FixtureRoot=./images`

Use `--image Name=PATH` for iconic image parameters. The runner loads the image with `halcon.read_image(PATH)` and passes the resulting HObject to the named input parameter.

## Output Contract

The runner prints JSON to stdout for success, runtime failure, and usage errors. It exits with:

- `0` when execution succeeded and all executed tests passed.
- `1` when execution failed or any executed procedure returned `TestPass := 0`.
- `2` for CLI usage errors such as missing action, malformed `--input`, or invalid `--match` regex.

Output control parameters are collected by name from HDevEngine procedure metadata. Iconic outputs are represented as placeholder strings such as `<HObject image>`; the runner does not serialize image data.

If a procedure returns an output control parameter named `TestPass`, the JSON payload includes `test_pass`. Batch mode uses this value to populate `failed`.

## `test_*` Procedure Pattern

Name local `.hdev` unit tests with a `test_` prefix, for example:

- `test_nominal_part_passes`
- `test_low_contrast_rejects`
- `test_board_count_guard_plus_one`

Do not require numbered names or group names. Use `--match` for ad hoc selections.

Every `test_*` procedure should expose explicit inputs with sensible documented defaults:

- `FixtureRoot` default `./images`
- `ResultDir` default `./result`
- `DebugLevel` default `0`

Pass these values explicitly when calling `hdev_call.py`. HDevelop's documented `<default_value>` metadata is for GUI/documentation support; do not assume HDevEngine applies it automatically at runtime.

Every `test_*` procedure should return these output control parameters:

- `TestPass`: `1` for pass, `0` for fail.
- `Message`: short human-readable assertion message.
- `DiagnosticsJson`: JSON text with machine-readable debug values.

Keep fixture loading and debug artifact writing in `test_*` procedures. Keep production image-processing logic in separate procedures that can also be called directly with `--procedure`.

## When to Use `hrun`

Use `hrun` only when a whole-program smoke run is enough, when HDevEngine/Python is not available, or when verifying runtime behavior that specifically depends on `main()`. Do not use `hrun -D` globals as the primary unit-test path for `.hdev` code.

## Optional SVG visualization

Install the Python dependency with `python -m pip install -r requirements.txt`.
Install `mvtec-halcon` separately with the version matching your HALCON runtime;
it is intentionally not pinned in `requirements.txt`.
HALCON/Python must match the native HALCON selected by your environment.

With multiple Windows installations, select the licensed version matching the
bindings before running Python, for example for HALCON 26.05:

```powershell
$env:HALCONROOT = "$env:LOCALAPPDATA\Programs\MVTec\HALCON-26.05-Progress"
$env:PATH = "$env:HALCONROOT\bin\x64-win64;$env:PATH"
```

These assignments apply only to the current PowerShell session; adjust the
installation path as needed.

```powershell
python scripts/hdev_call.py tests/fixtures/svg.hdev --procedure render_preview --svg-dir result
```

The runner registers a headless `HDevOperatorBase` adapter for the duration of
the call, then unregisters it. No visible graphics windows are opened.
Short-lived native buffer windows resolve HALCON colors and sample native LUTs;
they are always closed after the query. Buffer-window support is required on
the target platform (verified on Windows with HALCON 26.05).
Each window is saved as a standalone SVG of its final retained drawing state,
including windows closed by the procedure. Images are embedded as PNG; regions
and XLD contours are SVG paths. Closed windows retain their last contents;
cleared windows discard previous drawing elements. Style changes affect
subsequent drawing operations. Color, shape, contour, draw, line-width and LUT
settings also establish defaults for subsequently opened windows.

JSON gains `visualizations: [{"window_id": 1, "path": ".../window_1.svg"}]`.
Paths are absolute. Repeated runs use numeric filename suffixes instead of
overwriting files. Batch mode exports into one subdirectory per procedure and
reports visualizations inside each entry in `results`. Graphics are also exported
after a procedure exception. Rendering/export failures set `ok: false` and exit
code 1, with `visualization_errors` or `visualization_error` details.

Supported callbacks:

- Open/select/query/clear/close windows and change their dimensions.
- `dev_set_part`: explicit inclusive image bounds; `(0,0,-1,-1)` fits the last
  displayed image. Pixel centers map from HALCON row/column to SVG y/x.
- `dev_set_color`, `dev_set_line_width`, `dev_set_draw` (fill/margin).
- `dev_set_colored`: native 3-, 6- and 12-color palettes, cycling per object
  within each display call; `dev_set_color` replaces the palette. Named colors
  (including names with spaces) and alpha values are resolved by HALCON.
- `dev_set_shape`: original, rectangle1, rectangle2, inner_circle, outer_circle,
  ellipse and convex. HALCON's `shape_trans` produces the display regions;
  rasterized region boundaries may differ slightly from native analytic shapes.
- `dev_display`: PNG-compatible images, regions (including holes), XLD contours.
- `dev_set_contour_style`: stroke, fill (without outline), stroke_and_fill.
- `dev_set_lut`: native named LUTs (e.g. inverse, jet, batlow), LUT files and
  native RGB tuples. Supports `[LUT, minimum, maximum]` (or 768 RGB entries
  followed by minimum/maximum). The native table is sampled at 256 byte values,
  then applied to single-channel images. Non-byte grayscale images are normalized
  to their domain's minimum/maximum unless an explicit range is supplied;
  constant images map to zero. RGB images bypass the grayscale LUT.
  `default`/`linear` reset the table; omitting range arguments resets the range.
- `dev_disp_text`: numeric image/window positions; window alignment via
  top/center/bottom and left/center/right; multiple positions with scalar
  broadcasting; multiline text and cycling colors. Text keeps a fixed 16px
  monospace size even when its image-coordinate anchor is zoomed.
  Supports box, box_color, box_padding, border_color, border_width, border_radius,
  shadow, shadow_color, shadow_sigma, shadow_dx, shadow_dy and rotation via
  rotate_phi/rotate_row/rotate_col. Box and shadow defaults follow HALCON.
  Symbolic alignment uses a 12px window margin. Character widths and line spacing
  are deterministic approximations; native font metrics are not reproduced.

Exercise the extended options with:

```powershell
python scripts/hdev_call.py tests/fixtures/svg.hdev --procedure options_preview --svg-dir result
```

Limitations:

- This is a display approximation, not a pixel-identical HDevelop renderer.
  The final viewport transforms retained image-coordinate geometry; changing
  window size or part does not emulate every native redraw behavior.
- Shape `icon` (requires a custom icon), non-default paint modes, special part
  modes and text backdrop blur are not implemented. These and unknown options
  are reported in JSON `warnings`; unsupported style setters preserve the
  previous setting. Invalid supported parameters, native palette/LUT failures
  and callback errors produce `visualization_errors` with a failed result.
- Only callbacks exposed by HDevEngine/Python can be intercepted. Other
  `dev_*` operators retain HDevEngine behavior and cannot all be diagnosed.
- Virtual handles are not native windows: direct graphics operators such as
  `disp_obj`, `set_font` or helpers using ordinary window operators are not
  supported with these handles. Use the supported `dev_*` operations.
- Callback registration is process-global. SVG calls are intended for the
  sequential CLI runner; do not combine them with another custom display
  adapter or concurrent HDevEngine calls in the same process.

Verify with `python -m unittest discover -s tests -v`; the SVG integration tests
require drawsvg, compatible HALCON/Python/runtime versions, and a valid license.
