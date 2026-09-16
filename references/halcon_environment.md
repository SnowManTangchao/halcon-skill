# HALCON environment and documentation

Read this reference when locating installed operator documentation, examples, or runtime resources. Resolve environment variables on the current host; paths and available components vary by installation and version.

## HALCONROOT

`HALCONROOT` points to the HALCON installation. Search the relevant installed resource rather than assuming a fixed operator count or directory inventory.

| Relative path | Use |
|---|---|
| `doc/html/reference/operators/` | Operator signatures, parameter defaults, valid values, and examples |
| `doc/pdf/manuals/` | HDevelop, programming, and parallel programming manuals |
| `doc/pdf/solution_guide/` | Application-specific guidance for matching, measuring, classification, 3D, and acquisition |
| `procedures/general/` | Built-in reusable procedures and documentation examples |
| `procedures/dl/` | Installed deep-learning helpers |
| `procedures/templates/` | Procedure templates |
| `bin/` | Installed executables and runtime libraries; inspect platform-specific subdirectories |
| `images/`, `lut/` | Sample images and visualization lookup tables |

## HALCONEXAMPLES

`HALCONEXAMPLES` points to installed examples. Search `hdevelop/` for `.hdev`, `hdevelopevo/` for `.hscript`, and `solution_guide/` for examples accompanying the guides. Resolve referenced images using the installed `images/` directories. Do not assume every format or example is installed.

## Runtime setup

For the default `.hdev` execution path and Python/HALCON binding setup, read [Python runner](hdevengine_python_runner.md). Use [hrun](hrun.md) only for its documented fallback cases, and [hscriptengine](hscriptengine.md) for `.hscript`. Authoring does not require every runner to be installed.
