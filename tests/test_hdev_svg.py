"""Small end-to-end SVG tests; require matching HALCON/Python and drawsvg."""
import base64
import json
import struct
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SVG = "{http://www.w3.org/2000/svg}"
XLINK = "{http://www.w3.org/1999/xlink}"


class SvgTests(unittest.TestCase):
    def run_cli(self, directory, *args):
        run = subprocess.run(
            [sys.executable, str(ROOT / "scripts/hdev_call.py"),
             str(ROOT / "tests/fixtures/svg.hdev"), "--svg-dir", directory, *args],
            capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(run.stderr, "")
        return run.returncode, json.loads(run.stdout)

    def test_windows_geometry_and_embedded_image(self):
        with tempfile.TemporaryDirectory(prefix="hdev svg ") as directory:
            code, result = self.run_cli(directory, "--procedure", "render_preview")
            self.assertEqual(code, 0, result)
            self.assertTrue(result["test_pass"])
            self.assertEqual(len(result["visualizations"]), 2)
            first, second = [
                ET.parse(item["path"]).getroot() for item in result["visualizations"]
            ]
            self.assertEqual(first.attrib["viewBox"], "0 0 400 320")
            image = first.find(".//" + SVG + "image")
            data = base64.b64decode(image.attrib[XLINK + "href"].split(",", 1)[1])
            self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
            self.assertEqual(struct.unpack(">II", data[16:24]), (100, 80))
            paths = first.findall(".//" + SVG + "path")
            self.assertTrue(any(p.attrib.get("fill") == "#ff0000ff" and
                                p.attrib["d"].count("Z") > 1 for p in paths))
            self.assertTrue(any(p.attrib.get("stroke") == "#00ffffff" and
                                p.attrib.get("stroke-width") == "3.0" for p in paths))
            self.assertIsNotNone(first.find(".//" + SVG + "clipPath"))
            self.assertIsNotNone(first.find(".//" + SVG + "text"))
            self.assertIsNone(second.find(".//" + SVG + "image"))  # clear_window
            self.assertTrue(second.findall(".//" + SVG + "path"))  # closed window retained
            self.assertNotIn("warnings", result)
            # Repeat export must not overwrite a prior result.
            previous = Path(result["visualizations"][0]["path"])
            original = previous.read_bytes()
            code, repeated = self.run_cli(directory, "--procedure", "render_preview")
            self.assertEqual(code, 0, repeated)
            self.assertNotEqual(previous, Path(repeated["visualizations"][0]["path"]))
            self.assertEqual(previous.read_bytes(), original)

    def test_batch_keeps_graphics_on_failure(self):
        with tempfile.TemporaryDirectory(prefix="hdev svg ") as directory:
            code, result = self.run_cli(directory, "--match", "^render_")
            self.assertEqual(code, 1, result)
            self.assertEqual(result["failed"], ["render_failure"])
            paths = [Path(v["path"]) for item in result["results"]
                     for v in item["visualizations"]]
            self.assertEqual(len(set(paths)), 4)
            self.assertTrue(all(path.is_file() for path in paths))
            self.assertEqual({path.parent.name for path in paths},
                             {"render_preview", "render_failure"})



    def test_extended_options(self):
        import halcon as h
        with tempfile.TemporaryDirectory(prefix="hdev svg ") as directory:
            code, result = self.run_cli(directory, "--procedure", "options_preview")
            self.assertEqual(code, 0, result)
            first, second = [ET.parse(v["path"]).getroot() for v in result["visualizations"]]
            paths = first.findall(".//" + SVG + "path")
            self.assertTrue({"#ff0000ff", "#00ff00ff", "#0000ffff"} <=
                            {p.attrib.get("fill") for p in paths})
            magenta = [p for p in paths if "#ff00ffff" in
                       (p.attrib.get("fill"), p.attrib.get("stroke"))]
            self.assertEqual([(p.attrib["fill"], p.attrib["stroke"]) for p in magenta],
                             [("none", "#ff00ffff"), ("#ff00ffff", "none"),
                              ("#ff00ffff", "#ff00ffff")])
            self.assertTrue(any(r.attrib.get("fill") == "#ffeeccdd"
                                for r in first.findall(".//" + SVG + "rect")))
            blur = first.find(".//" + SVG + "feGaussianBlur")
            self.assertEqual(float(blur.attrib["stdDeviation"]), 2)
            rotated = next(t for t in first.findall(".//" + SVG + "text") if t.text == "Rotated")
            self.assertEqual((float(rotated.attrib["x"]), float(rotated.attrib["y"])), (182, 122))
            self.assertEqual(float(rotated.attrib["font-size"]), 16)  # not scaled by 4x zoom
            self.assertTrue(any("rotate(-30" in g.attrib.get("transform", "")
                                for g in first.findall(".//" + SVG + "g")))
            self.assertIn("backdrop_blur_sigma", result["warnings"][0])
            images = second.findall(".//" + SVG + "image")
            self.assertEqual(len(images), 2)
            for i, image in enumerate(images):
                data = base64.b64decode(image.attrib[XLINK + "href"].split(",", 1)[1])
                png = Path(directory) / f"lut_{i}.png"
                png.write_bytes(data)
                obj = h.read_image(str(png))
                if i == 0:
                    self.assertEqual(h.count_channels(obj), [3])
                    self.assertEqual(list(h.get_grayval(obj, 0, 0)), [255, 255, 255])
                    self.assertTrue(all(abs(v - 127.5) <= 1 for v in h.get_grayval(obj, 0, 1)))
                    self.assertEqual(list(h.get_grayval(obj, 0, 2)), [0, 0, 0])
                else:
                    self.assertEqual(list(h.get_grayval(obj, 0, 0)), [0])  # default resets LUT/range

    def test_native_palettes_shapes_and_luts(self):
        import halcon as h
        sys.path.insert(0, str(ROOT))
        from scripts.hdev_svg import SvgDisplay
        adapter = SvgDisplay()
        for count in (3, 6, 12):
            adapter.dev_set_colored(count)
            self.assertEqual(len(set(adapter.defaults["colors"])), count)
        adapter.dev_open_window(0, 0, 80, 80, "white")
        adapter.dev_set_part(0, 0, 79, 79)
        circle = h.gen_circle(20, 20, 5)
        for shape in ("rectangle1", "rectangle2", "ellipse", "convex", "outer_circle", "inner_circle"):
            with self.subTest(shape=shape):
                adapter.dev_clear_window()
                adapter.dev_set_shape(shape)
                adapter.dev_display(circle)
                self.assertTrue(adapter.window().elements)
                self.assertFalse(adapter.errors)
        adapter.dev_set_shape("icon")
        self.assertIn("icon", adapter.warnings[-1])
        self.assertEqual(adapter.window().shape, "inner_circle")  # unsupported setter preserves state
        adapter.dev_set_color("forest green")
        self.assertEqual(adapter.window().colors, ["#228b22ff"])
        ramp = h.gen_image_const("byte", 256, 1)
        h.set_grayval(ramp, [0] * 256, list(range(256)), list(range(256)))
        for lut, ends in (("inverse", (255, 0)), ("sqr", (0, 255)), ("jet", (None, None)),
                          ("batlow", (None, None))):
            with self.subTest(lut=lut):
                adapter.dev_set_lut(lut)
                out = adapter.image_for_display(ramp, adapter.window())
                self.assertEqual(h.count_channels(out), [3])
                if ends[0] is not None:
                    self.assertEqual(list(h.get_grayval(out, 0, 0)), [ends[0]] * 3)
                    self.assertEqual(list(h.get_grayval(out, 0, 255)), [ends[1]] * 3)
        with tempfile.TemporaryDirectory() as directory:
            lut_file = Path(directory) / "solid.lut"
            lut_file.write_text("12 34 56\n" * 256, encoding="ascii")
            adapter.dev_set_lut(str(lut_file))
            out = adapter.image_for_display(ramp, adapter.window())
            self.assertEqual(list(h.get_grayval(out, 0, 128)), [12, 34, 56])
        self.assertFalse(adapter.errors)

if __name__ == "__main__":
    unittest.main()
