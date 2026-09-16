# HDevEngine Python Runner

Use `scripts/hdev_call.py` as the default for executing code in HDevelop `.hdev` files: call named local production procedures, helpers, or `test_*` directly through HALCON/Python HDevEngine. It avoids `main()` dispatchers, global variables, and `hrun -D` parameter plumbing. For intermediate-state inspection, use the [debugger](hdev_debug.md).

This is currently a procedure runner, not a whole-program runner: an action such as `--procedure NAME` is required, and `--procedure main` is not supported. For an existing program whose `main()` must execute, use the [hrun fallback](hrun.md).

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

Keep `main()` for examples. Test individual procedures directly from `test_*`,
including private helpers; no `main()` dispatcher or global overrides are needed.

Expose only inputs the test actually needs, with sensible documented defaults.
For file-based fixtures or optional debug artifacts, useful conventions are:

- `FixtureRoot` default `./images`
- `ResultDir` default `./result`
- `DebugLevel` default `0`

Do not add unused `FixtureRoot`, `ResultDir` or `DebugLevel` parameters to simple
tests. Pass declared inputs explicitly when calling `hdev_call.py`. HDevelop's
documented `<default_value>` metadata is for GUI/documentation support; do not
assume HDevEngine applies it automatically at runtime. The batch examples above
assume the selected tests declare those inputs; adapt arguments to their interfaces.

Every `test_*` procedure should return `TestPass` (`1` for pass, `0` for fail)
based on assertions about the procedure under test. Add diagnostics only when useful:

- `Message`: short human-readable assertion message.
- `DiagnosticsJson`: JSON text with machine-readable debug values.

Keep fixture loading and debug artifact writing in `test_*` procedures. Keep production image-processing logic in separate procedures that can also be called directly with `--procedure`.

The public production API contract (`Image` containing an actual image and scalar
boolean output `JobPass`) is defined in `SKILL.md`. It does not apply to private
helpers, tests or `main()` examples. A test of expected rejection can pass even
when the tested production procedure returns `JobPass = 0`; `TestPass` describes
whether the observed behavior matches the expectation.

## When to Use `hrun`

Use `hdev_call.py` by default. The exceptions and minimal invocation for `hrun` are in the [fallback note](hrun.md). Do not use `hrun -D` globals as the primary unit-test path for `.hdev` code.

## Optional SVG visualization

For authoring, read [visualization](visualization.md): color palette, `dev_*` example, supported SVG options, retained drawing behavior, and limitations. This section covers setup, invocation, and output files.

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
JSON gains `visualizations: [{"window_id": 1, "path": ".../window_1.svg"}]`.
Paths are absolute. Repeated runs use numeric filename suffixes instead of
overwriting files. Batch mode exports into one subdirectory per procedure and
reports visualizations inside each entry in `results`. Graphics are also exported
after a procedure exception. Rendering/export failures set `ok: false` and exit
code 1, with `visualization_errors` or `visualization_error` details.

Exercise the extended options with:

```powershell
python scripts/hdev_call.py tests/fixtures/svg.hdev --procedure options_preview --svg-dir result
```

Verify with `python -m unittest discover -s tests -v`; the SVG integration tests
require drawsvg, compatible HALCON/Python/runtime versions, and a valid license.
