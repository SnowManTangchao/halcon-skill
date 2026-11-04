# HALCON Vision Script Authoring Skill

> **Proof of Concept** — This skill is under active development and may change significantly.

中文说明见 [README.zh-CN.md](README.zh-CN.md)。

An [Agent Skill](https://agentskills.io) for generating, refactoring, running, and reviewing [MVTec](https://www.mvtec.com) [HALCON](https://www.mvtec.com/products/halcon) vision scripts. It produces [HDevelop](https://www.mvtec.com/products/halcon/work-with-halcon/hdevelop) (`.hdev`) and [HDevelopEVO](https://www.mvtec.com/products/halcon/work-with-halcon/hdevelopevo) (`.hscript`) programs with accurate operator usage, parameter defaults and documentation.

This skill follows the open [Agent Skills](https://agentskills.io) standard and works with any compatible agent, including [Claude Code](https://claude.ai/code) and [OpenAI Codex](https://developers.openai.com/codex).

## What It Does

- **Generates complete, executable scripts** in both HDevelop XML (`.hdev`) and HDevelopEVO plain-text (`.hscript`) formats
- **Selects appropriate HALCON operators** with valid parameter ranges and sensible defaults
- **Builds structured vision pipelines** following a proven workflow: input → ROI → preprocessing → detection → decision
- **Creates reusable procedures** documented in English by default, plus the user's language when different and additional existing project languages
- **Runs individual procedures and tests** with explicit inputs, JSON results, and optional SVG visualization through the Python runner
- **Debugs live HDevelop procedures without HDevelop** using persistent sessions, stepping, breakpoints, vector inspection, and iconic previews
- **Runs complete programs headlessly** via `hrun` or `hscriptengine`
- **Uses installed HALCON documentation** — operator references, solution guides, and examples

## Prerequisites

- An AI coding agent that supports [Agent Skills](https://agentskills.io)
- [HALCON](https://www.mvtec.com/products/halcon) (or compatible version) installed with `HALCONROOT` and `HALCONEXAMPLES` environment variables set
- A valid HALCON runtime license for execution
- For the Python runner/debugger: Python and HALCON Python bindings matching the installed runtime, plus the dependencies below
- For complete-program execution: the selected `hrun` or `hscriptengine` executable available on your PATH; neither is required merely to use the Python procedure runner

Install the Python helper dependencies from the skill folder:

```bash
python -m pip install -r requirements.txt
```

This installs the SVG and debug-protocol dependencies, not the HALCON bindings or license. See the [Python setup reference](references/hdevengine_python_runner.md) for runtime configuration.

## Installation

### Option A: Using `npx skills` (multi-agent)

Installs the skill for all supported agents at once (Claude Code, Cursor, Codex, Copilot, Gemini CLI, and more):

```bash
npx skills add https://github.com/bertram-eu/halcon-skill.git
```

Or using GitHub shorthand:

```bash
npx skills add bertram-eu/halcon-skill
```

To update the skill to the latest version:

```bash
npx skills update bertram-eu/halcon-skill
```

### Option B: Manual (git clone)

Clone the repository and copy the entire skill folder into your agent's skills directory, including `scripts/`, `references/`, and `requirements.txt`, not just `SKILL.md`. The exact path depends on your agent:

```bash
git clone https://github.com/bertram-eu/halcon-skill.git
```

## Usage

Once installed, the skill activates automatically when you ask for HALCON-related tasks. Examples:

```
> Write an HDevelop script that reads an image, applies a threshold, and measures the area of all detected regions.

> Create an .hscript procedure that performs template matching with subpixel accuracy.

> Debug my barcode reading script — it fails on low-contrast images.

> Convert this HDevelop script to HDevelopEVO format.
```

The skill defaults to `.hdev` (HDevelop XML) format. Mention "HDevelopEVO", "HScript", or ".hscript" to get plain-text output instead.

## What's Included

```
halcon-skill/
├── SKILL.md          # Workflow selection and shared authoring rules
├── references/       # Formats, runners, debugger, palette, installed resources
├── scripts/          # Python procedure runner, SVG rendering, persistent debugger
├── tests/            # Helper integration tests and HDevelop fixtures
└── requirements.txt  # SVG and debug-protocol dependencies
```

## Choosing an Execution Tool

| Need | Tool | Details |
|---|---|---|
| Default for `.hdev`: call a named local procedure or `test_*`, get JSON or SVG | `scripts/hdev_call.py` | [Runner](references/hdevengine_python_runner.md) |
| Inspect intermediate state without HDevelop | `scripts/hdev_debug.py` | [Debugger](references/hdev_debug.md) |
| Fallback: execute an existing program's `main()` or run without Python bindings | `hrun` | [Fallback note](references/hrun.md) |
| Run `.hscript` | `hscriptengine` | [HScript engine](references/hscriptengine.md) |

For example, from the repository root:

```bash
python scripts/hdev_call.py tests/fixtures/debug.hdev --procedure debug_probe --input Value=21
```

Use `test_*` procedures for individual procedure tests and `main()` for examples. Public production procedures take a real `Image` and return boolean `JobPass`; private helpers and test/example entry points are exempt.

## Limitations

This is a proof of concept. Known limitations:

- Requires a local HALCON installation and license for execution and documentation access
- The skill relies on HALCON's HTML operator docs at `HALCONROOT/doc/html/` — if your installation is incomplete, operator lookups may fail
- Generated scripts should always be reviewed and tested before production use
- Remote debugging uses an unofficial native protocol. Read the [debugger limitations and session lifecycle](references/hdev_debug.md) before use; the password-free HALCON server belongs on a trusted host/network and must not be exposed remotely

## License

See [LICENSE](LICENSE) for details.
