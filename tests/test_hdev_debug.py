"""End-to-end checks against the actual local HALCON debug server."""
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import xml.etree.ElementTree as ET

from scripts.hdev_debug import record_path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts/hdev_debug.py"
FIXTURE = ROOT / "tests/fixtures/debug.hdev"


class DebugTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="hdev-debug-test-")
        self.sessions = []

    def tearDown(self):
        for session in self.sessions:
            self.cli("close", "--session", session)
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                record = json.loads(record_path(session).read_text())
                if record["state"] in ("closed", "expired", "startup_failed"):
                    break
                time.sleep(.02)
        self.directory.cleanup()

    def cli(self, *args, ok=True):
        result = subprocess.run([sys.executable, str(CLI), *map(str, args)],
                                cwd=ROOT, text=True, capture_output=True, timeout=40)
        value = json.loads(result.stdout)
        if ok:
            self.assertEqual(result.returncode, 0, value)
            self.assertTrue(value["ok"], value)
        else:
            self.assertNotEqual(result.returncode, 0, value)
            self.assertFalse(value["ok"], value)
        return value

    def start(self, procedure="debug_probe", *args):
        value = self.cli("start", FIXTURE, "--procedure", procedure,
                         "--output-dir", self.directory.name, *args)
        self.sessions.append(value["session"])
        return value

    def command(self, name, session, *args, **kwargs):
        return self.cli(name, "--session", session, *args, **kwargs)

    def test_step_inspect_breakpoint_and_previews(self):
        start = self.start("debug_probe", "--input", "Value=21")
        sid = start["session"]
        self.assertEqual(start["state"], "paused")
        self.assertEqual(start["next"]["procedure_line"], 2)  # Body comment counts.
        self.assertIn("Intermediate :=", FIXTURE.read_text().splitlines()[start["next"]["xml_line"] - 1])
        step = self.command("step", sid)
        self.assertEqual(step["next"]["procedure_line"], 3)
        self.assertEqual(step["reason"], "step")
        self.assertEqual(step["last_step_from"]["procedure_line"], 2)
        values = self.command("inspect", sid, "--variables", "Intermediate,Image,NotThere")["variables"]
        self.assertEqual(values[0]["values"], [42])
        self.assertIn("error", values[1])
        self.assertIn("error", values[2])
        self.command("breakpoint", sid, "add", "--procedure", "debug_probe", "--line", 1, ok=False)
        self.command("breakpoint", sid, "add", "--procedure", "debug_probe", "--line", 9)
        stopped = self.command("continue", sid)
        self.assertEqual((stopped["reason"], stopped["next"]["procedure_line"]), ("breakpoint", 9))
        values = self.command("inspect", sid, "--variables", "Mixed,Long,Image,Region,Contour,Empty", "--limit", 3)["variables"]
        self.assertEqual(values[0]["values"], [1, 2.5, "hello"])
        self.assertEqual((values[1]["length"], values[1]["truncated"]), (200, True))
        self.assertEqual([v["classes"] for v in values[2:]], [["image"], ["region"], ["xld_cont"], []])
        page = self.command("inspect", sid, "--variables", "Long", "--offset", 198, "--limit", 3)["variables"][0]
        self.assertEqual(page["values"], [198, 199])
        for names, background in (("Image", []), ("Region", []), ("Contour", []),
                                  ("Region,Contour", ["--background", "Image"])):
            preview = self.command("preview", sid, "--variables", names, *background)
            svg, png = [Path(a["path"]) for a in preview["artifacts"]]
            root = ET.parse(svg).getroot()
            self.assertTrue(root.tag.endswith("svg"))
            self.assertEqual(png.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
            self.assertTrue(svg.stat().st_size > 200)
        self.assertTrue(self.command("preview", sid, "--variables", "Empty")["empty"])
        self.command("preview", sid, "--variables", "Mixed", ok=False)
        self.command("breakpoint", sid, "clear")
        result = self.command("continue", sid)
        self.assertEqual((result["state"], result["outputs"]["Result"]), ("finished", [43]))
        self.command("step", sid, ok=False)

    def test_repeated_breakpoint_and_remove(self):
        sid = self.start("debug_loop")["session"]
        self.command("breakpoint", sid, "add", "--procedure", "debug_loop", "--line", 3)
        first = self.command("continue", sid)
        second = self.command("continue", sid)
        self.assertEqual(first["next"]["procedure_line"], second["next"]["procedure_line"])
        self.assertGreater(second["stop_id"], first["stop_id"])
        value = self.command("inspect", sid, "--variables", "Result")["variables"][0]
        self.assertEqual(value["values"], [1])
        self.command("breakpoint", sid, "remove", "--procedure", "debug_loop", "--line", 3)
        final = self.command("continue", sid)
        self.assertEqual((final["state"], final["outputs"]["Result"]), ("finished", [3]))

    def test_vector_inspection_and_preview(self):
        sid = self.start("debug_vectors")["session"]
        self.command("breakpoint", sid, "add", "--procedure", "debug_vectors", "--line", 8)
        self.command("continue", sid)
        data = self.command("inspect", sid, "--variables", "Values,Nested,EmptyVector,Images,Sparse")["variables"]
        self.assertEqual([e["values"] for e in data[0]["elements"]], [[1, 2], [], [3.5, "hello"]])
        self.assertEqual((data[1]["dimension"], data[1]["length"]), (2, 2))
        self.assertEqual([e["length"] for e in data[1]["elements"]], [3, 1])
        self.assertEqual((data[2]["length"], data[2]["elements"]), (0, []))
        self.assertEqual([e["classes"] for e in data[3]["elements"]], [["image"], ["image"]])
        self.assertEqual([e["values"] for e in data[4]["elements"]], [[], [], [7]])
        page = self.command("inspect", sid, "--variables", "Values", "--offset", 2, "--limit", 1)["variables"][0]
        self.assertEqual(page["elements"][0]["index"], 2)
        self.assertTrue(page["truncated"])
        leaf = self.command("inspect", sid, "--variables", "Nested", "--vector-path", "0,2",
                            "--offset", 1, "--limit", 1)["variables"][0]
        self.assertEqual((leaf["dimension"], leaf["variable_dimension"], leaf["values"]), (0, 2, ["hello"]))
        for path in ("8", "0,0,0"):
            self.assertIn("error", self.command("inspect", sid, "--variables", "Nested", "--vector-path", path)["variables"][0])
        self.command("inspect", sid, "--vector-path", "-1", ok=False)
        self.command("preview", sid, "--variables", "Images", ok=False)
        preview = self.command("preview", sid, "--variables", "Images", "--vector-path", "1")
        self.assertEqual((preview["width"], preview["height"]), (16, 12))
        self.assertTrue(all(Path(a["path"]).exists() for a in preview["artifacts"]))

    def test_variable_breakpoints(self):
        sid = self.start("debug_loop")["session"]
        args = ("--procedure", "debug_loop", "--variable", "Result")
        self.command("breakpoint", sid, "add", *args, "--line", 3, ok=False)
        self.command("breakpoint", sid, "add", "--procedure", "debug_loop", "--variable", "Result > 1", ok=False)
        self.command("breakpoint", sid, "add", "--procedure", "debug_loop", "--line", 5)
        self.command("breakpoint", sid, "add", "--procedure", "debug_loop", "--variable", "NotThere", ok=False)
        self.command("breakpoint", sid, "add", *args)
        points = self.command("breakpoint", sid, "list")["breakpoints"]
        self.assertEqual(len(points), 2)
        self.assertIn({"procedure": "debug_loop", "variable": "Result"}, points)
        for expected in (0, 1):
            stopped = self.command("continue", sid)
            self.assertEqual((stopped["reason"], stopped["variable"]), ("variable_breakpoint", "Result"))
            self.assertIsNone(stopped["next"])
            self.assertEqual(self.command("inspect", sid, "--variables", "Result")["variables"][0]["values"], [expected])
        self.command("breakpoint", sid, "remove", *args)
        stopped = self.command("continue", sid)
        self.assertEqual((stopped["reason"], stopped["next"]["procedure_line"]), ("breakpoint", 5))
        self.command("breakpoint", sid, "clear", "--procedure", "debug_loop")
        self.assertEqual(self.command("continue", sid)["outputs"]["Result"], [3])

    def test_nested_call_stack_and_frame(self):
        sid = self.start("debug_nested", "--input", "Value=7")["session"]
        self.command("breakpoint", sid, "add", "--procedure", "debug_probe", "--line", 9)
        stopped = self.command("continue", sid)
        self.assertEqual(stopped["next"]["procedure"], "debug_probe")
        self.assertEqual([s["procedure"] for s in stopped["stack"]], ["debug_probe", "debug_nested"])
        outer = self.command("inspect", sid, "--frame", 1, "--variables", "OuterLocal")["variables"][0]
        self.assertEqual(outer["values"], [107])
        self.command("breakpoint", sid, "clear")
        self.assertEqual(self.command("continue", sid)["outputs"]["Result"], [122])

    def test_running_close_and_expiry(self):
        sid = self.start("debug_wait", "--input", "Delay=30")["session"]
        running = self.command("continue", sid, "--wait", .05)
        self.assertEqual(running["state"], "running")
        self.command("inspect", sid, "--variables", "Result", ok=False)
        self.assertEqual(self.command("close", sid)["state"], "closed")
        sid = self.start("debug_loop", "--idle-timeout", 1)["session"]
        time.sleep(1.8)
        record = json.loads(record_path(sid).read_text())
        self.assertEqual(record["state"], "expired")
        with self.assertRaises(OSError):
            socket.create_connection(("127.0.0.1", record["port"]), timeout=.5)
        self.assertEqual(self.command("status", sid)["state"], "expired")

    def test_exception_and_invalid_request(self):
        self.cli("status", "--session", "../not-a-session", ok=False)
        sid = self.start("debug_probe", "--input", "Value='bad'")["session"]
        stopped = self.command("continue", sid)
        self.assertEqual((stopped["state"], stopped["reason"]), ("paused", "exception"))
        self.assertIn("exception", stopped)
        self.assertEqual(self.command("continue", sid)["state"], "failed")


if __name__ == "__main__":
    unittest.main()
