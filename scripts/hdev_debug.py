#!/usr/bin/env python3
"""Persistent local HDevelop debugger CLI. JSON stdout, no HDevelop or MCP.

The session process owns HALCON and its persistent Thrift connection. Short CLI
commands use authenticated loopback JSON IPC; the underlying HALCON server has
no password and may listen beyond loopback. Use only on a trusted local host.
"""
import argparse
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid

if __package__:
    from .hdev_call import JsonArgumentParser, parse_name_value, parse_name_path
else:
    from hdev_call import JsonArgumentParser, parse_name_value, parse_name_path

MAX_MESSAGE = 2 * 1024 * 1024
TERMINAL = ("closed", "expired", "startup_failed")


def registry():
    # Temp storage is host-local even when the workspace is an SMB share.
    user = hashlib.sha256(str(Path.home()).encode()).hexdigest()[:12]
    path = Path(tempfile.gettempdir()) / f"halcon-skill-debug-{user}"
    path.mkdir(mode=0o700, exist_ok=True)
    return path


def record_path(session):
    if not re.fullmatch(r"[0-9a-f]{32}", session):
        raise ValueError("Invalid session ID")
    return registry() / f"{session}.json"


def save(path, data):
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=True, allow_nan=False)
    os.chmod(temporary, 0o600)
    # Windows may briefly deny replacement while another CLI has the record open.
    for attempt in range(30):
        try:
            temporary.replace(path)
            break
        except PermissionError:
            if attempt == 29:
                raise
            time.sleep(.02)


def receive(sock):
    with sock.makefile("rb") as stream:
        line = stream.readline(MAX_MESSAGE + 1)
    if not line.endswith(b"\n") or len(line) > MAX_MESSAGE:
        raise ValueError("Invalid or oversized IPC message")
    return json.loads(line)


def transmit(sock, data):
    message = json.dumps(data, ensure_ascii=True, allow_nan=False).encode() + b"\n"
    if len(message) > MAX_MESSAGE:
        raise ValueError("IPC response too large; request a smaller page")
    sock.sendall(message)


def error(exc):
    return {"ok": False, "error": {"type": type(exc).__name__, "message": str(exc)}}


def request(session, command, **args):
    path = record_path(session)
    if not path.exists():
        raise ValueError("Unknown session ID")
    record = json.loads(path.read_text(encoding="utf-8"))
    if record["state"] in TERMINAL:
        return {"ok": command in ("status", "close"), "session": session,
                "state": record["state"], "reason": record.get("reason"),
                "error": record.get("error"), "output_dir": record["output_dir"]}
    try:
        with socket.create_connection(("127.0.0.1", record["port"]), timeout=3) as sock:
            sock.settimeout(float(args.get("wait", 0)) + 15)
            transmit(sock, {"token": record["token"], "command": command, **args})
            return receive(sock)
    except (OSError, KeyError) as exc:
        # A cached record alone is not evidence that a process is alive/dead.
        raise RuntimeError("Session unavailable; do not restart automatically. "
                           f"Inspect {record.get('log')} for details") from exc


def start(args):
    session = uuid.uuid4().hex
    program = Path(args.program).resolve(strict=True)
    output = (Path(args.output_dir).resolve() / session)
    output.mkdir(parents=True)
    config = {"session": session, "token": secrets.token_hex(32),
              "program": str(program), "procedure": args.procedure,
              "inputs": dict(args.input),
              "images": {name: str(Path(path).resolve(strict=True)) for name, path in args.image},
              "output_dir": str(output), "idle_timeout": args.idle_timeout,
              "max_lifetime": args.max_lifetime, "cwd": str(Path.cwd()),
              "state": "starting", "log": str(output / "session.log")}
    path = record_path(session)
    save(path, config)
    flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    with open(config["log"], "ab", buffering=0) as log:
        child = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "_serve", session],
                                 stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                 creationflags=flags, start_new_session=os.name != "nt", close_fds=True)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        record = json.loads(path.read_text(encoding="utf-8"))
        if record["state"] == "ready":
            result = request(session, "status")
            result["local_server_warning"] = "HALCON debug server has no password; trusted host/network only"
            return result
        if record["state"] == "startup_failed":
            return {"ok": False, "session": session, "state": "startup_failed", "error": record["error"]}
        if child.poll() is not None:
            raise RuntimeError(f"Debug process exited ({child.returncode}); see {config['log']}")
        time.sleep(.05)
    child.terminate()  # Only this start invocation's own child, never a stored PID.
    child.wait(timeout=5)
    raise TimeoutError(f"Debug startup exceeded 30 seconds; see {config['log']}")


def serve(session):
    """One single-threaded broker; execution and expiry watchdog are separate."""
    path = record_path(session)
    config = json.loads(path.read_text(encoding="utf-8"))
    lock = threading.Lock()
    def finish(state, reason=None):
        with lock:
            config.update(state=state, reason=reason)
            save(path, config)
        # Stopping the debug server resumes HALCON execution. Instead, terminate
        # our isolated process so close/expiry cannot execute remaining code.
        os._exit(0)
    try:
        if __package__:
            from .hdev_debug_runtime import DebugSession
        else:
            from hdev_debug_runtime import DebugSession
        with socket.socket() as temporary:
            temporary.bind(("127.0.0.1", 0))
            engine_port = temporary.getsockname()[1]
        runtime = DebugSession(config, engine_port)
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(8)
        listener.settimeout(.5)
        activity = [time.monotonic()]
        began = activity[0]
        config.update(state="ready", port=listener.getsockname()[1], pid=os.getpid())
        save(path, config)
        def expire():
            while True:
                time.sleep(.25)
                now = time.monotonic()
                if now - activity[0] > config["idle_timeout"]:
                    finish("expired", "idle_timeout")
                if now - began > config["max_lifetime"]:
                    finish("expired", "max_lifetime")
        threading.Thread(target=expire, daemon=True).start()
        while True:
            try:
                connection, _ = listener.accept()
            except socket.timeout:
                continue
            closing = False
            with connection:
                connection.settimeout(3)
                try:
                    payload = receive(connection)
                    if not hmac.compare_digest(str(payload.pop("token", "")), config["token"]):
                        raise ValueError("Invalid local session token")
                    activity[0] = time.monotonic()
                    command = payload.pop("command")
                    if command == "close":
                        response, closing = {"state": "closed"}, True
                    elif command == "status":
                        response = runtime.status()
                    elif command in ("step", "continue"):
                        response = runtime.move(command, payload.get("wait", 5))
                    elif command == "inspect":
                        response = runtime.inspect(payload["variables"], payload["frame"],
                                                   payload["offset"], payload["limit"], payload["vector_path"])
                    elif command == "preview":
                        response = runtime.preview(payload["variables"], payload["frame"],
                                                   payload["background"], payload["index"], payload["vector_path"])
                    elif command == "breakpoint":
                        response = runtime.breakpoint(payload["operation"], payload["procedure"], payload["line"], payload["variable"])
                    elif command == "source":
                        procedure = payload["procedure"] or config["procedure"]
                        lines = runtime.body(procedure)
                        offset, limit = payload["offset"], payload["limit"]
                        response = {"procedure": procedure, "total_lines": len(lines),
                                    "lines": [runtime.location(procedure, i + 1)
                                              for i in range(offset, min(len(lines), offset + limit))]}
                    else:
                        raise ValueError(f"Unknown debug command: {command}")
                    activity[0] = time.monotonic()
                    response = {"ok": True, "session": session, "output_dir": config["output_dir"], **response}
                except Exception as exc:
                    response = {**error(exc), "session": session}
                try:
                    transmit(connection, response)
                except ValueError as exc:
                    transmit(connection, {**error(exc), "session": session})
                except OSError:
                    # A disconnected CLI must not tear down an otherwise live
                    # session or cause its last command to be replayed.
                    pass
            if closing:
                finish("closed", "requested")
    except Exception as exc:
        config.update(state="startup_failed", error=error(exc)["error"])
        save(path, config)
        # Native threads may still be paused even if initialization failed.
        os._exit(1)


def parser():
    p = JsonArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    s = sub.add_parser("start")
    s.add_argument("program")
    s.add_argument("--procedure", required=True)
    s.add_argument("--input", action="append", type=parse_name_value, default=[])
    s.add_argument("--image", action="append", type=parse_name_path, default=[])
    s.add_argument("--output-dir", default="result/debug")
    s.add_argument("--idle-timeout", type=float, default=300)
    s.add_argument("--max-lifetime", type=float, default=3600)
    for command in ("status", "step", "continue", "inspect", "preview", "breakpoint", "source", "close"):
        c = sub.add_parser(command)
        c.add_argument("--session", required=True)
        if command in ("step", "continue"):
            c.add_argument("--wait", type=float, default=5)
        if command in ("inspect", "preview"):
            c.add_argument("--variables", default="", help="Comma-separated names")
            c.add_argument("--frame", type=int, default=0)
            c.add_argument("--vector-path", default="", help="Zero-based vector indices, e.g. 0,2")
        if command in ("inspect", "source"):
            c.add_argument("--offset", type=int, default=0)
            c.add_argument("--limit", type=int, default=100)
        if command in ("source", "breakpoint"):
            c.add_argument("--procedure")
        if command == "preview":
            c.add_argument("--background")
            c.add_argument("--index", type=int)
        if command == "breakpoint":
            c.add_argument("operation", choices=("add", "remove", "clear", "list"))
            c.add_argument("--line", type=int, help="1-based procedure body line, NOT XML file line")
            c.add_argument("--variable", help="Native write breakpoint on a variable")
    return p


def main():
    try:
        if len(sys.argv) == 3 and sys.argv[1] == "_serve":
            serve(sys.argv[2])
            return 0
        args = parser().parse_args()
        for name, low, high in (("idle_timeout", 1, 86400), ("max_lifetime", 1, 86400),
                                ("wait", 0, 30), ("limit", 1, 1000), ("offset", 0, 1000000),
                                ("frame", 0, 1000), ("index", 1, 1000000)):
            value = getattr(args, name, None)
            if value is not None and not low <= value <= high:
                raise ValueError(f"--{name.replace('_', '-')} must be between {low} and {high}")
        if args.command == "start":
            result = start(args)
        else:
            values = vars(args).copy()
            command, session = values.pop("command"), values.pop("session")
            if "variables" in values:
                values["variables"] = [n.strip() for n in values["variables"].split(",") if n.strip()]
                path = values["vector_path"]
                if path and not re.fullmatch(r"[0-9]+(?:,[0-9]+)*", path):
                    raise ValueError("--vector-path must contain comma-separated nonnegative indices")
                values["vector_path"] = [int(i) for i in path.split(",")] if path else []
                if len(values["vector_path"]) > 64:
                    raise ValueError("--vector-path exceeds maximum depth 64")
            if command == "preview" and not values["variables"]:
                raise ValueError("preview requires --variables")
            result = request(session, command, **values)
        print(json.dumps(result, ensure_ascii=True, allow_nan=False))
        return 0 if result.get("ok") else 1
    except Exception as exc:
        print(json.dumps(error(exc)))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
