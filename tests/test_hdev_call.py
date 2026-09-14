"""Runner tests; require HALCON/Python, the native runtime, and a valid license."""

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.hdev_call import parse_input_value

FIXTURE = Path(__file__).with_name("fixtures") / "runner.hdev"


class HDevCallTests(unittest.TestCase):
    def run_cli(self, *args):
        completed = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "hdev_call.py"),
             str(FIXTURE), *args],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(completed.stderr, "")
        return completed.returncode, json.loads(completed.stdout)

    def test_input_values(self):
        for raw, expected in [
            ("42", 42), ("3.5", 3.5), ("true", True), ("False", False),
            ("[1, 2]", [1, 2]), ('{"a": 1}', {"a": 1}),
            ('"hello world"', "hello world"), ("raw-value", "raw-value"),
        ]:
            with self.subTest(raw=raw):
                self.assertEqual(parse_input_value(raw), expected)

    def test_list_procedures(self):
        code, result = self.run_cli("--list-procedures")
        self.assertEqual(code, 0)
        self.assertTrue(result["ok"])
        self.assertEqual(set(result["procedures"]), {"test_double", "test_failure"})

    def test_single_procedure(self):
        for value, expected_code in [(21, 0), (0, 1)]:
            with self.subTest(value=value):
                code, result = self.run_cli(
                    "--procedure", "test_double", "--input", f"Value={value}",
                )
                self.assertEqual(code, expected_code)
                self.assertTrue(result["ok"])
                self.assertEqual(result["outputs"]["control"]["Result"], [value * 2])
                self.assertEqual(result["test_pass"], expected_code == 0)

    def test_batch_selection_and_failure(self):
        for pattern, expected_code, names, failed in [
            ("^test_double$", 0, {"test_double"}, []),
            ("^test_", 1, {"test_double", "test_failure"}, ["test_failure"]),
        ]:
            with self.subTest(pattern=pattern):
                code, result = self.run_cli("--match", pattern, "--input", "Value=21")
                self.assertEqual(code, expected_code)
                self.assertEqual(result["ok"], expected_code == 0)
                self.assertEqual(set(result["procedures"]), names)
                self.assertEqual(result["failed"], failed)

    def test_usage_errors(self):
        for args in [
            (), ("--procedure", "test_double", "--input", "BadInput"),
            ("--match", "["),
        ]:
            with self.subTest(args=args):
                code, result = self.run_cli(*args)
                self.assertEqual(code, 2)
                self.assertFalse(result["ok"])
                self.assertTrue(result["usage_error"])


if __name__ == "__main__":
    unittest.main()
