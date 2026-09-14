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
