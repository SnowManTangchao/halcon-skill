#!/usr/bin/env python3
"""Run local HDevelop procedures through HALCON HDevEngine."""

from __future__ import annotations

import argparse
import ast
import importlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


HALCON_SETUP_MESSAGE = (
    "Could not import HALCON Python bindings. Install/configure MVTec HALCON/Python "
    "('mvtec-halcon') and the native HALCON runtime, then ensure they are visible "
    "to this Python environment."
)


class UsageError(Exception):
    """CLI usage error that should be returned as JSON."""


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise UsageError(message)


@dataclass(frozen=True)
class CliResult:
    exit_code: int
    payload: dict[str, Any]


def import_halcon() -> Any:
    """Import HALCON lazily so this module remains testable without HALCON."""
    try:
        return importlib.import_module("halcon")
    except Exception as exc:  # pragma: no cover - exact import failures vary by install
        raise RuntimeError(HALCON_SETUP_MESSAGE) from exc


def parse_input_value(raw: str) -> Any:
    lowered = raw.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False

    try:
        return int(raw)
    except ValueError:
        pass

    try:
        return float(raw)
    except ValueError:
        pass

    if raw.startswith(("[", "{", '"', "'")):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
        try:
            return ast.literal_eval(raw)
        except (SyntaxError, ValueError):
            pass

    return raw


def parse_name_value(raw: str) -> tuple[str, Any]:
    if "=" not in raw:
        raise argparse.ArgumentTypeError("expected Name=Value")
    name, value = raw.split("=", 1)
    if not name:
        raise argparse.ArgumentTypeError("input name must not be empty")
    return name, parse_input_value(value)


def parse_name_path(raw: str) -> tuple[str, str]:
    if "=" not in raw:
        raise argparse.ArgumentTypeError("expected Name=PATH")
    name, path = raw.split("=", 1)
    if not name:
        raise argparse.ArgumentTypeError("image input name must not be empty")
    if not path:
        raise argparse.ArgumentTypeError("image path must not be empty")
    return name, path


def _error_dict(exc: BaseException) -> dict[str, Any]:
    error: dict[str, Any] = {
        "type": type(exc).__name__,
        "message": str(exc),
    }
    for attr in ("error_code", "procedure_name", "line_number", "line_text"):
        if hasattr(exc, attr):
            error[attr] = _jsonable(getattr(exc, attr))
    return error


def _failure(exc: BaseException, **extra: Any) -> dict[str, Any]:
    result = {"ok": False, "error": _error_dict(exc)}
    result.update(extra)
    return result


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if hasattr(value, "to_tuple"):
        try:
            return _jsonable(value.to_tuple())
        except Exception:
            pass
    return str(value)


def _make_program(halcon: Any, program_path: str) -> Any:
    return halcon.HDevProgram(program_path)


def _local_procedure_names(program: Any) -> list[str]:
    method = getattr(program, "get_local_procedure_names", None)
    if callable(method):
        return [str(name) for name in method()]
    raise AttributeError("HDevProgram does not expose get_local_procedure_names")


def _load_local_procedure(halcon: Any, program: Any, procedure_name: str) -> Any:
    procedure_cls = halcon.HDevProcedure
    return procedure_cls.load_local(program, procedure_name)


def _procedure_param_names(procedure: Any, kind: str) -> list[str]:
    attribute_names = {
        "output_control": "output_control_param_names",
        "output_iconic": "output_iconic_param_names",
    }
    value = getattr(procedure, attribute_names[kind], None)
    if value is not None:
        return [str(name) for name in value]
    return []


def _set_control_input(call: Any, name: str, value: Any) -> None:
    call.set_input_control_param_by_name(name, value)


def _set_iconic_input(call: Any, name: str, value: Any) -> None:
    call.set_input_iconic_param_by_name(name, value)


def _get_control_output(call: Any, name: str) -> Any:
    return call.get_output_control_param_by_name(name)


def _get_iconic_output(call: Any, name: str) -> Any:
    return call.get_output_iconic_param_by_name(name)


def _iconic_placeholder(value: Any) -> str:
    for attr_name in ("get_object_type", "type_name"):
        attr = getattr(value, attr_name, None)
        if callable(attr):
            try:
                return f"<HObject {attr()}>"
            except Exception:
                break
        if attr is not None:
            return f"<HObject {attr}>"
    return f"<HObject {type(value).__name__}>"


def _test_pass_value(outputs: dict[str, Any]) -> bool | None:
    if "TestPass" not in outputs:
        return None
    value = outputs["TestPass"]
    if isinstance(value, (list, tuple)) and len(value) == 1:
        value = value[0]
    if isinstance(value, str):
        lowered = value.lower()
        if lowered in ("false", "0", "no"):
            return False
        if lowered in ("true", "1", "yes"):
            return True
    return bool(value)


def list_procedures(program_path: str) -> dict[str, Any]:
    try:
        halcon = import_halcon()
        program = _make_program(halcon, program_path)
        return {
            "ok": True,
            "program": program_path,
            "procedures": _local_procedure_names(program),
        }
    except Exception as exc:
        return _failure(exc, program=program_path)


def run_procedure(
    program_path: str,
    procedure_name: str,
    *,
    control_inputs: dict[str, Any] | None = None,
    image_inputs: dict[str, str] | None = None,
    svg_dir: str | None = None,
) -> dict[str, Any]:
    control_inputs = control_inputs or {}
    image_inputs = image_inputs or {}
    display = None
    engine = None

    try:
        halcon = import_halcon()
        if svg_dir is not None:
            if __package__:
                from .hdev_svg import SvgDisplay
            else:
                from hdev_svg import SvgDisplay
            display = SvgDisplay()
            engine = halcon.HDevEngine()
            engine.set_hdev_operator_impl(display)
        program = _make_program(halcon, program_path)
        procedure = _load_local_procedure(halcon, program, procedure_name)
        call = halcon.HDevProcedureCall(procedure)

        for name, value in control_inputs.items():
            _set_control_input(call, name, value)
        for name, path in image_inputs.items():
            _set_iconic_input(call, name, halcon.read_image(path))

        call.execute()

        control_output_names = _procedure_param_names(procedure, "output_control")
        iconic_output_names = _procedure_param_names(procedure, "output_iconic")
        control_outputs = {
            name: _jsonable(_get_control_output(call, name))
            for name in control_output_names
        }
        iconic_outputs = {
            name: _iconic_placeholder(_get_iconic_output(call, name))
            for name in iconic_output_names
        }
        test_pass = _test_pass_value(control_outputs)

        result: dict[str, Any] = {
            "ok": True,
            "program": program_path,
            "procedure": procedure_name,
            "outputs": {
                "control": control_outputs,
                "iconic": iconic_outputs,
            },
        }
        if test_pass is not None:
            result["test_pass"] = test_pass
    except Exception as exc:
        result = _failure(exc, program=program_path, procedure=procedure_name)
    finally:
        if engine is not None:
            try:
                engine.unset_hdev_operator_impl()
            except Exception as exc:
                result["ok"] = False
                result["visualization_cleanup_error"] = _error_dict(exc)

    if display is not None:
        try:
            result["visualizations"] = display.export(svg_dir)
        except Exception as exc:
            result["ok"] = False
            result["visualization_error"] = _error_dict(exc)
        if display.warnings:
            result["warnings"] = display.warnings
        if display.errors:
            result["ok"] = False
            result["visualization_errors"] = display.errors
    return result


def run_matching_procedures(
    program_path: str,
    pattern: str,
    *,
    control_inputs: dict[str, Any] | None = None,
    image_inputs: dict[str, str] | None = None,
    svg_dir: str | None = None,
) -> dict[str, Any]:
    try:
        matcher = re.compile(pattern)
    except re.error as exc:
        return _failure(exc, program=program_path, match=pattern, usage_error=True)

    listed = list_procedures(program_path)
    if not listed.get("ok"):
        return listed

    matched = [name for name in listed["procedures"] if matcher.search(name)]
    results = [
        run_procedure(
            program_path,
            name,
            control_inputs=control_inputs,
            image_inputs=image_inputs,
            svg_dir=str(Path(svg_dir) / name) if svg_dir is not None else None,
        )
        for name in matched
    ]
    failed = [
        result.get("procedure", "<unknown>")
        for result in results
        if not result.get("ok") or result.get("test_pass") is False
    ]

    return {
        "ok": not failed,
        "program": program_path,
        "match": pattern,
        "procedures": matched,
        "failed": failed,
        "results": results,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = JsonArgumentParser(
        description="Call local HDevelop procedures through HALCON HDevEngine."
    )
    parser.add_argument("program", help="Path to the .hdev program")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--procedure", help="Local procedure name to execute")
    action.add_argument(
        "--list-procedures",
        action="store_true",
        help="List local procedure names",
    )
    action.add_argument("--match", help="Run local procedures whose names match REGEX")
    parser.add_argument("--svg-dir", help="Export final dev_* window contents as SVG files.")
    parser.add_argument(
        "--input",
        dest="inputs",
        action="append",
        type=parse_name_value,
        default=[],
        metavar="Name=Value",
        help="Control input parameter. Values support numbers, booleans, simple literals, and strings.",
    )
    parser.add_argument(
        "--image",
        dest="images",
        action="append",
        type=parse_name_path,
        default=[],
        metavar="Name=PATH",
        help="Iconic image input parameter loaded with halcon.read_image(PATH).",
    )
    return parser.parse_args(argv)


def _usage_failure(exc: UsageError) -> dict[str, Any]:
    return {
        "ok": False,
        "error": {
            "type": "usage_error",
            "message": str(exc),
        },
        "usage_error": True,
    }


def run_cli(argv: list[str] | None = None) -> CliResult:
    try:
        args = parse_args(argv)
    except UsageError as exc:
        return CliResult(2, _usage_failure(exc))

    control_inputs = dict(args.inputs)
    image_inputs = dict(args.images)

    if args.list_procedures:
        result = list_procedures(args.program)
    elif args.procedure:
        result = run_procedure(
            args.program,
            args.procedure,
            control_inputs=control_inputs,
            image_inputs=image_inputs,
            svg_dir=args.svg_dir,
        )
    else:
        result = run_matching_procedures(
            args.program,
            args.match,
            control_inputs=control_inputs,
            image_inputs=image_inputs,
            svg_dir=args.svg_dir,
        )

    if result.get("usage_error"):
        return CliResult(2, result)
    if not result.get("ok") or result.get("test_pass") is False:
        return CliResult(1, result)
    return CliResult(0, result)


def main(argv: list[str] | None = None) -> int:
    result = run_cli(argv)
    print(json.dumps(result.payload, indent=2, sort_keys=True))
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
