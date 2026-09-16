# Local HDevelop debugger CLI

`scripts/hdev_debug.py` runs local procedures in a persistent, isolated Python
process. Each invocation returns one JSON document. No HDevelop UI or MCP is
required. The ordinary `hdev_call.py` runner remains unchanged.

## Setup and first session

Use Python with bindings matching the installed HALCON runtime and a valid runtime license.
Install the skill's `requirements.txt` (drawsvg and thrift). The runtime is also
used to decode the serialized variable values in the session process.

Invoke the script by its path in the skill, with the working directory set to
the target project so relative data files retain their meaning. These examples
assume the skill repository is the working directory:

```powershell
python scripts/hdev_debug.py start tests/fixtures/debug.hdev --procedure debug_probe --input Value=21
```

Keep the returned session ID. Each command below is a separate invocation:

```powershell
python scripts/hdev_debug.py status --session SESSION_ID
python scripts/hdev_debug.py step --session SESSION_ID
python scripts/hdev_debug.py inspect --session SESSION_ID --variables Intermediate
python scripts/hdev_debug.py source --session SESSION_ID --procedure debug_probe
python scripts/hdev_debug.py breakpoint add --session SESSION_ID --procedure debug_probe --line 9
python scripts/hdev_debug.py continue --session SESSION_ID
python scripts/hdev_debug.py preview --session SESSION_ID --variables Region,Contour --background Image
python scripts/hdev_debug.py close --session SESSION_ID
```

`start` accepts the same `--input Name=Value` and `--image Name=PATH` syntax as the
normal runner. `--output-dir` defaults to `result/debug`; each session gets its
own subdirectory. `--idle-timeout` defaults to 300 seconds and `--max-lifetime`
to 3600 seconds. Increase them explicitly for longer investigations (maximum
86400 seconds). Both limits bound abandoned sessions, including native hangs.

The native HALCON server intentionally uses no password for this local workflow.
The CLI control channel binds to loopback and uses a random session token, but
**that does not restrict the native HALCON server's bind address**. Use only a
trusted local host/network; do not open inbound firewall access for it. This CLI
only starts its own engine, never attaches to an existing production process.

## Commands and state

| Command | Behavior |
| --- | --- |
| `start` | Load a local procedure and pause before its first executable statement. |
| `status` | State, stop ID, source context, next statement, stack and breakpoints or final results. |
| `source --procedure NAME` | Loaded body with procedure/XML coordinates; `--offset` and `--limit` paginate it. |
| `step` | Native single-step mode; return the next stop or `running`. |
| `continue` | Resume until a breakpoint, error or completion. |
| `inspect --variables A,B` | Values and metadata; omitted names inspect all locals. |
| `preview --variables Region,Contour --background Image` | Export iconic variables as SVG and PNG. |
| `breakpoint add/remove --procedure NAME --line N` | Add/remove an unconditional line breakpoint. |
| `breakpoint add/remove --procedure NAME --variable NAME` | Add/remove a native variable write breakpoint. |
| `breakpoint list` | List session breakpoints. |
| `breakpoint clear [--procedure NAME]` | Clear all breakpoints, or those in one procedure. |
| `close` | Terminate the isolated process without executing the remaining code. Idempotent. |

`step` and `continue` wait up to 5 seconds (`--wait 0..30`). If execution has not
paused/completed, they return `state: running`; poll `status` for the **same
execution**. Do not retry `continue` or start another run just because the wait
elapsed. Inspection, stepping and breakpoint changes require a paused session.
Commands are serialized by the session process.

States: `paused`, `running`, `finished`, `failed`, `closed`, `expired`, and
`startup_failed`. Native unhandled errors pause first so local context can be
inspected. Continuing delivers the exception to the runner and yields `failed`.
An inaccessible control channel reports an error, not proof that execution has
stopped. Inspect the session log rather than automatically replaying the code.

`ok: true` means the CLI operation succeeded, not that the inspected procedure or
its `TestPass` output passed. Check `state`, final `outputs` and visualization
errors. `stop_id` increases on each observed stop, including repeated hits of the
same line in a loop. Native notifications establish stops, not line-number changes.

## Source and variables

- `next` has **not executed yet**. `procedure_line` is 1-based within the body;
  comments/blank lines count. Breakpoints must refer to executable lines.
- `xml_line` is the actual file coordinate when a reliable mapping is available;
  it is not interchangeable with `procedure_line`. External sources may have no
  file mapping. `source_sha256` identifies the loaded top-level program.
  `source_changed: true` warns when that file has changed or disappeared; XML
  coordinates are then suppressed while the loaded source remains inspectable.
- `last_step_from` is the starting location of the last step, not a trace of all
  statements executed by that step.
- `stack` is innermost-first. `inspect --frame 0` selects that frame; `--frame 1`
  selects its caller. Native depth indices are translated by the CLI.
- Control values include total `length`, a `values` page, and `truncated`.
  `--offset` and `--limit` (default 100, max 1000) avoid dumping long tuples.
  Integers, reals and strings are preserved; non-finite numbers become strings.
  Individual strings are capped at 2048 characters, with `strings_truncated` set
  explicitly when that happens.
  Handles are described, not made usable in the client.
- Unknown/uninitialized/unsupported values return per-variable errors;
  other requested variables remain inspectable. No arbitrary expression
  evaluation or variable modification is offered.
- Iconic inspection returns count and classes, not huge pixel arrays.

## Vectors

Control and iconic vectors expose their `dimension`, `length` and an `elements`
page with zero-based `index` values. Nested vectors are summarized one level at a
time; control leaves show up to 10 tuple values in the overview. Empty vectors
and empty tuple elements remain distinct. Use `--vector-path` to inspect a child
or leaf, without sending expressions to the native server:

```powershell
python scripts/hdev_debug.py inspect --session SESSION_ID --variables Nested
python scripts/hdev_debug.py inspect --session SESSION_ID --variables Nested --vector-path 0
python scripts/hdev_debug.py inspect --session SESSION_ID --variables Nested --vector-path 0,2 --offset 10 --limit 20
python scripts/hdev_debug.py preview --session SESSION_ID --variables Images --vector-path 1
```

`--offset`/`--limit` page the selected vector's children or the selected leaf's
tuple values. `dimension` describes the selected value; `variable_dimension`
preserves the original dimension when a path is supplied. Paths apply to each
requested variable. For previews, paths apply to foreground variables only;
`--background` must be a non-vector iconic variable. Select a complete path to
an iconic leaf before using `--index` (which remains **1-based** within its object
tuple). Vector paths themselves are **zero-based**.

The complete serialized variable is transferred, but only requested leaves are
decoded. The existing 64 MiB transfer limit still applies; vector inspection is
bounded to 64 dimensions and 100000 elements per opened vector. The reconstructed
HVCT envelope is validated; HALCON decodes the enclosed metadata, tuples and
objects. Unsupported formats produce explicit errors rather than guessed values.

## Variable and conditional breakpoints

```powershell
python scripts/hdev_debug.py breakpoint add --session SESSION_ID --procedure debug_loop --variable Result
python scripts/hdev_debug.py breakpoint remove --session SESSION_ID --procedure debug_loop --variable Result
```

Use either `--line` or `--variable`, not both. Line and variable breakpoints can
coexist; `list` and `clear` cover both. Variables must be names, not expressions
or vector-element paths. HALCON silently ignores nonexistent variable names;
the CLI reads back registration and restores the previous set if an addition
was rejected.

A native variable breakpoint reports `reason: variable_breakpoint` and the
triggering `variable`. It stops **after a write**, so inspection sees the new
value; this is not a client-side comparison against the old value. At these
stops, the native stack's source position can be stale: `next` is deliberately
null and `location_note` explains the limitation. Do not infer the exact writing
statement from that stack position.

No native conditional-breakpoint facility was found in the inspected HALCON
26.05 protocol. The `HenDebugBreakpoint` reader/writer accepts exactly four
fields: `is_var_breakpoint`, `proc_id`, `line_number`, `var_name`; other field IDs
are skipped. The debug service exposes `SetBreakpoints`/`GetProcBreakpoints`, but
no condition-setting or expression-evaluation RPC was found. This is a finding
about the inspected implementation, not a claim about every HALCON version.
No session-side condition evaluation or automatic resume workaround is used.

## Iconic previews

Images, regions and XLD contours are transferred from the paused frame using
HALCON serialization; no prior `dev_display` is needed. The existing SVG renderer
produces vector overlays/embedded images. An invisible native buffer produces
a PNG for the agent's image viewer. Both artifact paths are absolute and unique.

Variables share their original coordinate system. `--background Image` draws the
image before overlays. Standalone regions/contours fit their bounds, including
negative coordinates. Previews have a maximum dimension of 1024 pixels and do not
change the procedure's graphics state. Serialized values larger than 64 MiB are
not supported by this implementation.

`--index N` selects a 1-based element of each foreground iconic tuple. Otherwise
at most 50 objects per variable are previewed; larger tuples produce an explicit
error rather than silently hiding objects. Empty tuples return `empty: true`
without artifacts. `--frame` also works for previews.

The engine uses the runner's headless `dev_*` adapter. Its final display SVGs are
exported under the session's `display` directory. Direct native graphics calls
with virtual handles retain the runner's existing limitations.

## Scope and lifecycle

The protocol is reconstructed and undocumented. No HALCON version gate is applied;
integration tests have been run on Windows with HALCON 26.05.
JIT execution is disabled for the session. Parallel `par_start`, conditional
breakpoints, arbitrary remote attachment and password
authentication are not supported. This is a diagnosis tool, not a replacement for
reproducible tests.

Session records are stored in per-user host-local temporary storage, including
when the workspace is a network share. Logs/previews go in the selected output
directory. Closed/expired records remain small tombstones so `status` and repeated
`close` can report the outcome. Close/expiry terminate the owned process: simply
stopping the native debug server would resume paused code and could cause side
effects. Code changes require a **new session**, not implicit hot reload.
