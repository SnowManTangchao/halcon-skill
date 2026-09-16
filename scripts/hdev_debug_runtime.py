"""Session-owned HALCON execution, debugger state and on-demand previews."""
import hashlib
import math
import re
from pathlib import Path
import threading
import time
from xml.parsers import expat

import halcon as h

if __package__:
    from .hdev_debug_protocol import DebugClient, DebugProtocolError, I32, STRING
    from .hdev_svg import SvgDisplay, buffer_window, scalar
    from .hdev_debug_values import Vector, deserialize, select_path
else:
    from hdev_debug_protocol import DebugClient, DebugProtocolError, I32, STRING
    from hdev_svg import SvgDisplay, buffer_window, scalar
    from hdev_debug_values import Vector, deserialize, select_path


def json_value(value):
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (tuple, list)):
        return [json_value(x) for x in value]
    return {"type": type(value).__name__, "representation": str(value)}


def source_map(path):
    """Map procedure body lines to actual XML file lines, not guessed offsets."""
    mapping, procedure, in_body = {}, None, False
    parser = expat.ParserCreate()
    def start(name, attrs):
        nonlocal procedure, in_body
        if name == "procedure":
            procedure = attrs["name"]
            mapping[procedure] = []
        elif name == "body":
            in_body = True
        elif in_body and name in ("l", "c"):
            mapping[procedure].append(parser.CurrentLineNumber)
    def end(name):
        nonlocal in_body
        if name == "body":
            in_body = False
    parser.StartElementHandler, parser.EndElementHandler = start, end
    raw = Path(path).read_bytes()
    parser.Parse(raw, True)
    return mapping, hashlib.sha256(raw).hexdigest()


class DebugSession:
    """Owns all native objects; only execute() runs on the engine thread."""
    def __init__(self, config, port):
        self.config = config
        self.output_dir = Path(config["output_dir"])
        self.xml_lines, self.source_hash = source_map(config["program"])
        self.engine = h.HDevEngine()
        self.engine.set_attribute("execute_procedures_jit_compiled", "false")
        self.engine.set_attribute("debug_port", port)
        self.engine.set_attribute("debug_password", "")
        self.display = SvgDisplay()
        self.engine.set_hdev_operator_impl(self.display)
        self.program = h.HDevProgram(config["program"])
        self.procedure = h.HDevProcedure.load_local(self.program, config["procedure"])
        self.execution = h.HDevProcedureCall(self.procedure)
        for name, value in config["inputs"].items():
            self.execution.set_input_control_param_by_name(name, value)
        for name, path in config["images"].items():
            self.execution.set_input_iconic_param_by_name(name, h.read_image(path))
        self.engine.start_debug_server()
        self.execution.wait_for_debug_connection()
        self.client = DebugClient(port)
        self.client.attach(config["session"])
        self.state, self.reason = "running", "starting"
        self.finished = threading.Event()
        self.result = None
        self.sources, self.breakpoints = {}, set()
        self.stop_id, self.last_step = 0, None
        self.stop_context = None
        self.thread = threading.Thread(target=self.execute, daemon=True)
        self.thread.start()
        self.wait(5)

    def execute(self):
        try:
            self.execution.execute()
            outputs = {str(name): json_value(self.execution.get_output_control_param_by_name(name))
                       for name in self.procedure.output_control_param_names}
            self.result = {"outputs": outputs}
        except Exception as exc:
            self.result = {"error": {"type": type(exc).__name__, "message": str(exc)}}
        finally:
            try:
                self.result["visualizations"] = self.display.export(self.output_dir / "display")
                self.result["visualization_errors"] = self.display.errors
                self.result["warnings"] = self.display.warnings
            except Exception as exc:
                self.result["visualization_errors"] = [str(exc)]
            self.finished.set()

    def poll(self):
        for _ in range(1000):
            event = self.client.event()
            if not event["type"]:
                break
            if event["type"] == 3:
                self.state = "paused"
                self.stop_id += 1
                self.stop_context = event["context"]
                self.reason = {1: "entry", 2: "breakpoint", 3: "variable_breakpoint", 4: "exception"}.get(
                    event["reason"], "step" if self.reason == "step" else "paused")
            elif event["type"] == 5:
                raise RuntimeError("Debug session disconnected")
        if self.finished.is_set():
            self.state = "failed" if "error" in self.result else "finished"

    def wait(self, seconds):
        deadline = time.monotonic() + seconds
        while True:
            self.poll()
            if self.state != "running" or time.monotonic() >= deadline:
                return
            time.sleep(.01)

    def body(self, procedure):
        if procedure not in self.sources:
            self.sources[procedure] = self.client.call(
                "debug:GetProcBody", ((1, STRING, procedure),)).decode("utf-8").splitlines()
        return self.sources[procedure]

    def location(self, procedure, line):
        lines = self.body(procedure)
        mapping = self.xml_lines.get(procedure, [])
        # Only publish XML coordinates when body cardinality agrees with runtime.
        xml_line = mapping[line - 1] if (not self.source_changed() and
            len(mapping) == len(lines) and 0 < line <= len(mapping)) else None
        return {"procedure": procedure, "procedure_line": line,
                "file": self.config["program"] if xml_line is not None else None,
                "xml_line": xml_line,
                "text": lines[line - 1] if 0 < line <= len(lines) else None}

    def source_changed(self):
        try:
            return hashlib.sha256(Path(self.config["program"]).read_bytes()).hexdigest() != self.source_hash
        except OSError:
            return True

    def stack(self):
        self.client.call("debug:DetermineActiveThread")
        return [self.location(frame[1][1].decode(), frame[2][1] + 1)
                for frame in reversed(self.client.call("debug:GetCallStack"))]

    def status(self):
        self.poll()
        result = {"state": self.state, "stop_id": self.stop_id, "reason": self.reason,
                  "source_sha256": self.source_hash, "source_changed": self.source_changed(),
                  "breakpoints": self.points(),
                  "last_step_from": self.last_step}
        if self.state == "paused":
            frames = self.stack()
            result["stack"] = frames
            result["next"] = frames[0] if frames else None
            if self.reason == "variable_breakpoint":
                result["variable"] = self.stop_context
                result["next"] = None
                result["location_note"] = "Write already executed; native stack location may be stale"
            if frames:
                top = frames[0]
                n, proc = top["procedure_line"], top["procedure"]
                result["source_context"] = [self.location(proc, i) for i in
                    range(max(1, n - 2), min(len(self.body(proc)), n + 2) + 1)]
            if self.reason == "exception":
                result["exception"] = repr(self.client.call("debug:GetLastErrorInfo"))
        elif self.finished.is_set():
            result.update(self.result)
        return result

    def require_paused(self):
        self.poll()
        if self.state != "paused":
            raise ValueError(f"Operation requires a paused session, currently {self.state}")
        self.client.call("debug:DetermineActiveThread")

    def move(self, action, wait):
        self.require_paused()
        # Consume notifications BEFORE resume; a new event, not a changed line,
        # proves the next stop (loops can hit the same breakpoint repeatedly).
        self.last_step = self.stack()[0] if action == "step" and self.reason != "variable_breakpoint" else None
        self.client.call("debug:Step", ((1, I32, 0),)) if action == "step" else self.client.call("debug:Run")
        self.state, self.reason = "running", action
        self.wait(wait)
        return self.status()

    def variables(self, frame=0):
        self.require_paused()
        if not 0 <= frame < len(self.stack()):
            raise ValueError("Frame index out of range")
        return [{"name": item[1][1].decode(), "iconic": item[2][1], "dimension": item[3][1]}
                for item in self.client.call("debug:GetVariables", ((1, I32, len(self.stack()) - 1 - frame),))]

    def value(self, variable, frame, path=()):
        raw = self.client.call("debug:GetVariableValue",
                               ((1, I32, len(self.stack()) - 1 - frame), (2, STRING, variable["name"])))
        if not raw:
            raise ValueError("Variable is not initialized at the current stop")
        value = (Vector(raw, variable["iconic"], variable["dimension"]) if variable["dimension"]
                 else deserialize(raw, variable["iconic"]))
        return select_path(value, path)

    def inspect(self, names, frame, offset, limit, vector_path=()):
        catalog = {v["name"]: v for v in self.variables(frame)}
        result = []
        for name in names or catalog:
            if name not in catalog:
                result.append({"name": name, "error": "Unknown variable"})
                continue
            entry = dict(catalog[name])
            try:
                value = self.value(entry, frame, vector_path)
                if vector_path:
                    entry.update(vector_path=list(vector_path), variable_dimension=entry["dimension"])
                entry.update(describe_value(value, entry["iconic"], offset, limit))
            except (DebugProtocolError, h.HOperatorError, ValueError) as exc:
                entry["error"] = str(exc)
            result.append(entry)
        return {"state": self.state, "stop_id": self.stop_id, "frame": frame, "variables": result}

    def points(self):
        return [{"procedure": p, **({"variable": v} if v else {"line": n})}
                for p, n, v in sorted(self.breakpoints)]

    def breakpoint(self, operation, procedure, line, variable=None):
        self.require_paused()
        points = self.breakpoints.copy()
        if operation == "clear":
            points = {p for p in points if procedure and p[0] != procedure} if procedure else set()
        elif operation in ("add", "remove"):
            if not procedure or (line is None) == (variable is None):
                raise ValueError("Breakpoint add/remove requires --procedure and exactly one of --line or --variable")
            lines = self.body(procedure)
            if variable is not None:
                if not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", variable):
                    raise ValueError("--variable must be a variable name, not an expression")
                line = 0
            elif not 1 <= line <= len(lines) or not lines[line - 1].strip() or lines[line - 1].lstrip().startswith("*"):
                raise ValueError("Breakpoint must refer to an executable procedure body line (1-based)")
            point = (procedure, line, variable or "")
            points.add(point) if operation == "add" else points.discard(point)
        if operation != "list":
            self.client.set_breakpoints(sorted(points))
            if operation == "add":
                try:
                    if point not in self.client.get_breakpoints(procedure):
                        raise ValueError("HALCON did not accept the breakpoint; check the variable name or source line")
                except Exception:
                    self.client.set_breakpoints(sorted(self.breakpoints))
                    raise
            self.breakpoints = points
        return {"state": self.state, "breakpoints": self.points()}

    def preview(self, names, frame, background, index, vector_path=()):
        self.require_paused()
        catalog = {v["name"]: v for v in self.variables(frame)}
        objects = []
        for name in ([background] if background else []) + names:
            if name not in catalog or not catalog[name]["iconic"]:
                raise ValueError(f"{name} is not an iconic variable")
            obj = self.value(catalog[name], frame, vector_path if name != background else ())
            if isinstance(obj, Vector):
                raise ValueError(f"{name}: select an iconic leaf with --vector-path")
            count = h.count_obj(obj)
            if index is not None and name != background:
                if not 1 <= index <= count:
                    raise ValueError(f"{name}: object index out of range")
                obj, count = h.select_obj(obj, index), 1
            if count > 50:
                raise ValueError(f"{name} contains {count} objects; select one with --index")
            objects.append((name, obj))
        return render_preview(objects, self.output_dir / "previews", self.stop_id)


def describe_value(value, iconic, offset, limit, expand=True):
    if isinstance(value, Vector):
        result = {"dimension": value.dimension, "length": len(value)}
        if expand:
            elements = []
            for index in range(offset, min(len(value), offset + limit)):
                entry = {"index": index}
                try:
                    entry.update(describe_value(value.child(index), iconic, 0, min(limit, 10), False))
                except (ValueError, h.HOperatorError) as exc:
                    entry["error"] = str(exc)
                elements.append(entry)
            result.update(offset=offset, elements=elements,
                          truncated=offset > 0 or len(value) > offset + limit)
        return result
    if iconic:
        count = h.count_obj(value)
        return {"dimension": 0, "count": count,
                "classes": h.get_obj_class(h.select_obj(value, list(range(1, min(count, 20) + 1)))) if count else [],
                "truncated": count > 20}
    page = value[offset:offset + limit]
    return {"dimension": 0, "length": len(value), "offset": offset,
            "values": json_value([v[:2048] if isinstance(v, str) else v for v in page]),
            "strings_truncated": any(isinstance(v, str) and len(v) > 2048 for v in page),
            "truncated": offset > 0 or len(value) > offset + limit}


def render_preview(objects, directory, stop_id):
    """SVG uses the existing renderer; PNG is an inspectable native buffer view."""
    bounds, items = [], []
    for name, objects_tuple in objects:
        for i in range(1, h.count_obj(objects_tuple) + 1):
            obj = h.select_obj(objects_tuple, i)
            kind = scalar(h.get_obj_class(obj))
            if kind == "image":
                w, ht = h.get_image_size(obj)
                bounds.append((0, 0, scalar(ht) - 1, scalar(w) - 1))
            elif kind == "region":
                if scalar(h.area_center(obj)[0]) > 0:
                    bounds.append(tuple(scalar(v) for v in h.smallest_rectangle1(obj)))
            elif kind == "xld_cont":
                rows, cols = h.get_contour_xld(obj)
                if rows:
                    bounds.append((min(rows), min(cols), max(rows), max(cols)))
            else:
                raise ValueError(f"Preview does not support object class {kind}")
            items.append((name, kind, obj))
    if not bounds:
        return {"empty": True, "artifacts": [], "stop_id": stop_id}
    r1, c1 = min(b[0] for b in bounds), min(b[1] for b in bounds)
    r2, c2 = max(b[2] for b in bounds), max(b[3] for b in bounds)
    margin = 0 if any(kind == "image" for _, kind, _ in items) else 2
    r1, c1, r2, c2 = r1 - margin, c1 - margin, r2 + margin, c2 + margin
    width, height = c2 - c1 + 1, r2 - r1 + 1
    scale = min(1, 1024 / max(width, height))
    width, height = max(1, round(width * scale)), max(1, round(height * scale))
    import uuid
    directory = directory / uuid.uuid4().hex
    directory.mkdir(parents=True)
    display = SvgDisplay()
    display.dev_open_window(0, 0, width, height, "#273338")
    display.dev_set_part(r1, c1, r2, c2)
    display.dev_set_draw("margin")
    colors = ["#85A407", "#005F87", "#E77910"]
    png = directory / "preview.png"
    with buffer_window(width, height) as window:
        h.set_window_param(window, "background_color", "#273338")
        h.clear_window(window)
        h.set_part(window, r1, c1, r2, c2)
        h.set_draw(window, "margin")
        for i, (_, kind, obj) in enumerate(items):
            color = colors[i % len(colors)]
            display.dev_set_color(color)
            display.dev_display(obj)
            h.set_color(window, color)
            native = display.image_for_display(obj, display.window()) if kind == "image" else obj
            h.disp_obj(native, window)
        h.write_image(h.dump_window_image(window), "png", 0, str(png))
    if display.errors:
        raise RuntimeError("; ".join(display.errors))
    svg = display.export(directory)[0]["path"]
    return {"empty": False, "stop_id": stop_id, "width": width, "height": height,
            "part": [r1, c1, r2, c2], "warnings": display.warnings,
            "artifacts": [{"format": "svg", "path": svg}, {"format": "png", "path": str(png)}]}
