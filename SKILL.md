---
name: halcon-skill
description: Generate, refactor, run, and review HALCON HDevelop (`.hdev`) and HDevelopEVO (`.hscript`) programs with accurate operator usage, parameter defaults, value ranges, and practical vision pipelines. Use when the user asks for HDevelop or HScript code, operator selection, debugging logic, converting requirements into vision scripts, or building reusable procedures.
---

# HALCON Vision Script Authoring Skill

Generate, refactor, run, and review HALCON vision programs. Preserve the project's existing format; default new programs to `.hdev` unless HDevelopEVO/`.hscript` is requested. Ask only when the choice materially affects an ambiguous task.

Generate or edit HALCON artifacts (`.hdev`, `.hdvp`, `.hdpl`, `.hscript`) unless the user requests other changes.

## Choose the workflow

Read only the references relevant to the task, before using that format or tool.

| Task | Tool and required reference |
|---|---|
| Author or edit HDevelop XML and procedure documentation | [HDevelop format](references/hdev_format.md) |
| Author or edit HDevelopEVO text and imports | [HScript format](references/hscript_format.md) |
| Run `.hdev` code (default: named local procedure or `test_*`) with explicit inputs, JSON results, optional SVG | `scripts/hdev_call.py` — [Python runner](references/hdevengine_python_runner.md) |
| Inspect intermediate `.hdev` state, step, set breakpoints, inspect vectors or preview iconic values without HDevelop | `scripts/hdev_debug.py` — [Debugger](references/hdev_debug.md) |
| Fallback: execute an existing `.hdev` program's `main()`, or run without Python bindings | `hrun` — [short fallback note](references/hrun.md) |
| Execute `.hscript` | `hscriptengine` — [HScript engine](references/hscriptengine.md) |

For operator signatures, defaults, valid ranges, installed examples, or runtime locations, read [HALCON environment and documentation](references/halcon_environment.md). Verify operator details against the installed reference rather than guessing.

For overlays and annotations, read [visualization](references/visualization.md): the exact color palette, `dev_*` usage, supported SVG options, and limitations. For SVG setup, invocation, and output files, read the Python runner reference.

## Procedure responsibilities

- **Public production API:** Every procedure intended for an external application must accept an iconic input named `Image` containing an actual image (semantic type `image`, not a region, XLD, path, or placeholder), and return scalar boolean `JobPass` (`1` = pass, `0` = fail).
- **Private helpers:** Procedures used only internally or by `test_*` need only their task-specific parameters. Calling a helper through the test runner does not make it a public production API.
- **Tests:** Use `test_*` for individual public or private procedures, with explicit inputs and assertions; follow the Python runner's test pattern. Test success is distinct from production `JobPass`: an expected rejection may pass the test.
- **Examples:** Use `main()` for example orchestration, not as the unit-test interface. Put example parameters together at the top.
- Test and example entry points are exempt from the public production signature. Avoid hidden global state; globals are not required for test inputs.

## Documentation languages

Document every procedure (including `main()` or the HScript main section) and every parameter. Apply this policy to generated or updated documentation:

- English is always the default.
- Add the user's local language when known and different from English.
- Inspect existing project documentation and also use its additional languages. Preserve these languages when updating documentation.
- This normally means one or two languages; existing project languages may increase that number. Do not impose German or a fixed number of translated copies.
- Use the format-specific reference for XML language tags or comment blocks. Any untagged text fallback must be English; it is not another language.

Include purpose, a realistic usage example, and parameter semantics, ranges, units, and defaults where applicable. Keep translations consistent with the same behavior.

## Authoring constraints

- Keep acquisition/input, ROI, preprocessing, detection or measurement, and decision/reporting understandable. Make outputs and pass/fail reasons explicit.
- Expose tunable parameters through procedure inputs with sensible documented defaults and valid ranges. Reuse repeated logic and expensive handles/models.
- Use calibrated transforms for metric measurements rather than pixel approximations.
- Use idiomatic HALCON syntax and stable, task-specific names. In HScript, use `public proc` for imported APIs, `proc` for file-local helpers, and `from ... import *` for external procedures.
- Account for region clipping when generating absolute-coordinate ROIs: establish the relevant image dimensions first or explicitly configure `clip_region` as appropriate.
- Use `dev_*` operators for visualization in production procedures as well as examples and tests. Keep production overlays alongside the logic they explain; visualization is not restricted to `main()` or `test_*`. Use multiple windows where useful and `dev_set_part` rather than cropping merely for display. Only file export of annotated artifacts belongs in examples/tests or the runner, not production procedures.
- Keep visualization optional and non-blocking; handle unavailable displays gracefully. No `stop()`, `dev_open_dialog`, or interactive operators in headless code. Use `return ()` or `throw` for error paths and handle plausible runtime failures.
- Use `par_start`/`par_join` only for independent work with isolated outputs.
- Do not add camera access or external communication (network, industrial communication, file I/O) unless requested. Do not infer permission to operate equipment from a debugging request.

## Tests and artifacts

Check for an `images` folder, class splits such as `ok`/`nok` or training/test/validation, and JSON/YAML annotations; use supplied fixtures appropriately. Write requested test/run artifacts under `result/` by default, with runner JSON or CLI logs associated with each tested image. Pass only the inputs the test needs.

Use ordinary execution for regression tests. Debug only when intermediate state is needed: form a hypothesis, inspect relevant source/variables, and request previews selectively.

Keep the same debugger session ID across commands. If it is still `running`, poll `status` rather than starting another run. Close the session when finished; closing terminates the isolated process without executing remaining statements. Code changes require a new session and ordinary regression tests. Never automatically replay camera, file, network, or equipment side effects.

The native debug server has no password. Use a trusted host/network and do not expose it remotely; read the debugger reference before starting it.

## Delivery

Provide complete executable code for requested solutions, state critical image/calibration/polarity/lighting assumptions, explain key operator choices, and identify parameters likely to need tuning. Report execution evidence and remaining limitations without claiming unrun tests passed.
