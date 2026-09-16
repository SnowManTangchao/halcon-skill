# Visualization and SVG rendering

Read this reference when authoring overlays or using the skill's SVG renderer. It describes the renderer's supported subset, not the complete HALCON operator API. For dependency setup, `--svg-dir`, JSON results, and output paths, see [Python runner](hdevengine_python_runner.md#optional-svg-visualization).

## Production visualization

Use `dev_*` operators for visualization in production code, not only in examples or tests. Production procedures may display input images, intermediate results, overlays, and result text alongside their processing logic. Keep visualization optional and non-blocking; disabling it must not change processing results or `JobPass`. Writing image/SVG artifacts to disk remains the responsibility of examples/tests or the runner, rather than production procedures.

## Color scheme

Use the following palette for all HALCON overlays, annotations, and result displays. Use the exact hexadecimal HALCON color codes instead of named colors such as `'green'`, `'red'`, or `'blue'` when a palette color exists.

At the top of each procedure that performs visualization, declare only the colors that procedure actually uses. Name each variable by its meaning in the procedure, not by its hue or position. Prefer names such as `ColorGoodDetection`, `ColorFailure`, `ColorCalculatedValue`, `ColorWarningLow`, `ColorWarningHigh`, or `ColorDismissedFeature`; avoid names such as `Green`, `Red`, `Color1`, or `OverlayColor`.

| Meaning | Source color | RGB | HALCON code |
|---|---|---:|---|
| Good or accepted detection, `JobPass = true` | `OK` / green | 133, 164, 7 | `#85A407` |
| Error, failure, rejected detection, `JobPass = false` | `Alarm` / red | 202, 51, 51 | `#CA3333` |
| Calculated or measured value | `Accent` / blue | 0, 95, 135 | `#005F87` |
| Low warning or special attention | `WarningLow` / yellow | 234, 206, 33 | `#EACE21` |
| High warning or special attention | `WarningHigh` / orange | 231, 121, 16 | `#E77910` |
| Dismissed, suppressed, or otherwise excluded feature | yellow or orange according to severity | 234, 206, 33 or 231, 121, 16 | `#EACE21` or `#E77910` |

Use the neutral colors only when a visualization needs a background, panel, inactive element, or neutral annotation:

| Source color | RGB | HALCON code |
|---|---:|---|
| `Light` | 218, 220, 224 | `#DADCE0` |
| `DarkGrey` | 39, 51, 56 | `#273338` |
| `Grey` | 64, 77, 83 | `#404D53` |
| `LightGrey` | 196, 199, 204 | `#C4C7CC` |
| `White` | 249, 247, 248 | `#F9F7F8` |

Use RGBA codes (`#rrggbbaa`) only when translucency is useful, for example when a filled region would otherwise hide the image. Keep thin contours and text opaque unless there is a specific reason not to. The standard translucent aliases use alpha 128 (`80` hexadecimal):

| Meaning | HALCON code |
|---|---|
| Transparent failure/red | `#CA333380` |
| Transparent good detection/green | `#85A40780` |
| Transparent calculated value/blue | `#005F8780` |
| Transparent white | `#F9F7F880` |
| Transparent low warning/yellow | `#EACE2180` |
| Transparent high warning/orange | `#E7791080` |

When matching the predefined Qt constant `AlarmTranslucent` exactly, use alpha 127 (`#CA33337F`). When matching the generic `transparentRed` alias, use alpha 128 (`#CA333380`).

Example procedure-local declarations and use:

```hdevelop
* Declare only colors used by this procedure.
ColorGoodDetection := '#85A407'
ColorFailure := '#CA3333'
ColorCalculatedValue := '#005F87'
ColorDismissedFeature := '#E7791080'

dev_set_color (ColorGoodDetection)
dev_display (AcceptedDetections)
dev_set_color (ColorFailure)
dev_display (FailedDetections)
dev_set_color (ColorCalculatedValue)
dev_disp_text ('Width: ' + Width$'.2f' + ' mm', 'window', 12, 12, ColorCalculatedValue, 'box', 'false')
dev_set_color (ColorDismissedFeature)
dev_display (DismissedFeatures)
```

For native graphics windows only, the same variables can be used with `set_color(WindowHandle, Color)`. The Python SVG runner uses virtual handles: do not pass them to `set_color`, `disp_message`, or other native-window helpers. Use supported `dev_*` operations instead; see [SVG limitations](#svg-limitations).

## Window, image, overlay, and text example

Visualization body fragment, also suitable inside a production procedure's optional visualization block: `Image` is an existing image and `Region` is an existing result region in the same coordinate system. The region is displayed as an accepted detection for illustration; choose the semantic color according to the actual result. Procedure interface and documentation are omitted. This example owns its window; do not close a caller-owned window.

```hdevelop
ColorBackground := '#273338'
ColorGoodDetection := '#85A407'
get_image_size (Image, Width, Height)
dev_open_window (0, 0, 640, 480, ColorBackground, WindowHandle)
dev_set_part (0, 0, Height - 1, Width - 1)
dev_display (Image)
dev_set_draw ('margin')
dev_set_line_width (2)
dev_set_color (ColorGoodDetection)
dev_display (Region)
dev_disp_text ('Accepted region', 'window', 12, 12, ColorGoodDetection, 'box', 'false')
dev_close_window ()
```

Display the image before its overlays. Use `dev_set_part` for the viewport instead of cropping the image merely for display. For multiple views, open separate windows and select the intended window with `dev_set_window` before drawing. Keep visualization optional when the same procedure also runs without the SVG adapter or a native display.

## SVG drawing behavior

Each window is saved as a standalone SVG of its final retained drawing state,
including windows closed by the procedure. Images are embedded as PNG; regions
and XLD contours are SVG paths. Closed windows retain their last contents;
cleared windows discard previous drawing elements. Style changes affect
subsequent drawing operations. Color, shape, contour, draw, line-width and LUT
settings also establish defaults for subsequently opened windows.

## Supported dev_* operations

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

## SVG limitations

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
