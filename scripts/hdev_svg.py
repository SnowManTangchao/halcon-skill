"""Headless HDevEngine display callbacks backed by drawsvg.

Virtual handles are HALCON dictionaries, not native graphics windows.
Use only through dev_* callbacks; ordinary graphics operators require real windows.
"""
from dataclasses import dataclass, field
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from tempfile import TemporaryDirectory

import drawsvg as draw
import halcon as h


@contextmanager
def buffer_window(width=1, height=1):
    """Short-lived invisible HALCON window for native color/LUT queries."""
    handle = h.open_window(0, 0, width, height, 0, "buffer", "")
    try:
        yield handle
    finally:
        h.close_window(handle)


def rgb_colors(red, green, blue, alpha=None):
    alpha = [255] * len(red) if alpha is None else alpha
    return [f"#{r:02x}{g:02x}{b:02x}{a:02x}" for r, g, b, a in zip(red, green, blue, alpha)]


def scalar(value):
    return value[0] if isinstance(value, (list, tuple)) else value


def sequence(value):
    return list(value) if isinstance(value, (list, tuple)) else [value]


def capture_error(method):
    """Keep Python exceptions out of ctypes callbacks and report them in JSON."""
    @wraps(method)
    def callback(self, *args, **kwargs):
        try:
            return method(self, *args, **kwargs)
        except Exception as exc:
            self.errors.append(f"{method.__name__}: {type(exc).__name__}: {exc}")
            return 0 if method.__name__ in ("dev_open_window", "dev_get_window") else None
    return callback


@dataclass
class TextBlock:
    """Text stays in screen pixels even when its anchor uses image coordinates."""
    lines: list
    colors: list
    row: float | str
    column: float | str
    coord_system: str
    options: dict

    def drawing(self, window):
        opts = self.options
        # Fixed monospace metrics keep box and SVG text layout consistent.
        font_size, line_height = 16, 20
        width = max((len(line) for line in self.lines), default=0) * font_size * .6
        height = len(self.lines) * line_height
        padding = opts["box_padding"]
        def position(value, extent, size, start, end):
            if isinstance(value, str):
                return {start: 12 + padding, "center": (extent - size) / 2,
                        end: extent - size - 12 - padding}[value]
            return float(value)
        x = position(self.column, window.width, width, "left", "right")
        y = position(self.row, window.height, height, "top", "bottom")
        if self.coord_system == "image":
            sx, sy, tx, ty = window.transform()
            x, y = x * sx + tx, y * sy + ty
        group = draw.Group()
        angle = opts["rotate_phi"]
        if angle:
            cx = opts["rotate_col"]
            cy = opts["rotate_row"]
            if self.coord_system == "image":
                if not isinstance(cx, str):
                    cx = cx * sx + tx
                if not isinstance(cy, str):
                    cy = cy * sy + ty
            cx = {"text_left": x, "text_center": x + width / 2,
                  "text_right": x + width}.get(cx, cx)
            cy = {"text_top": y, "text_center": y + height / 2,
                  "text_bottom": y + height}.get(cy, cy)
            group.args["transform"] = f"rotate({-angle} {cx} {cy})"
        if opts["box"]:
            box_args = dict(rx=opts["border_radius"], ry=opts["border_radius"])
            if opts["shadow"]:
                shadow_args = dict(fill=opts["shadow_color"], **box_args)
                if opts["shadow_sigma"]:
                    blur = draw.Filter(x="-100%", y="-100%", width="300%", height="300%")
                    blur.append(draw.FilterItem("feGaussianBlur", stdDeviation=opts["shadow_sigma"]))
                    shadow_args["filter"] = blur
                group.append(draw.Rectangle(
                    x - padding + opts["shadow_dx"], y - padding + opts["shadow_dy"],
                    width + 2 * padding, height + 2 * padding, **shadow_args))
            group.append(draw.Rectangle(
                x - padding, y - padding, width + 2 * padding, height + 2 * padding,
                fill=opts["box_color"], stroke=opts["border_color"],
                stroke_width=opts["border_width"], **box_args))
        for i, line in enumerate(self.lines):
            if line:
                group.append(draw.Text(
                    line, font_size, x, y + i * line_height,
                    fill=self.colors[i % len(self.colors)], font_family="monospace",
                    dominant_baseline="text-before-edge",
                    textLength=len(line) * font_size * .6, lengthAdjust="spacingAndGlyphs"))
        return group


@dataclass
class SvgWindow:
    width: int
    height: int
    background: str
    part: tuple | None = None
    image_size: tuple | None = None
    colors: list = field(default_factory=lambda: ["white"])
    line_width: float = 1
    draw_mode: str = "fill"
    contour_style: str = "stroke"
    shape: str = "original"
    lut: tuple | None = None
    gray_range: tuple | None = None
    closed: bool = False
    elements: list = field(default_factory=list)

    def transform(self):
        r1, c1, r2, c2 = self.part or (
            0, 0, (self.image_size or (self.width, self.height))[1] - 1,
            (self.image_size or (self.width, self.height))[0] - 1,
        )
        sx, sy = self.width / (c2 - c1 + 1), self.height / (r2 - r1 + 1)
        return sx, sy, (-c1 + .5) * sx, (-r1 + .5) * sy

    def drawing(self):
        drawing = draw.Drawing(self.width, self.height)
        drawing.append(draw.Rectangle(0, 0, self.width, self.height, fill=self.background))
        sx, sy, tx, ty = self.transform()
        clip = draw.ClipPath()
        clip.append(draw.Rectangle(0, 0, self.width, self.height))
        viewport = draw.Group(clip_path=clip)
        drawing.append(viewport)
        for element, image_coords in self.elements:
            if isinstance(element, TextBlock):
                element = element.drawing(self)
            group = draw.Group(transform=(
                f"matrix({sx} 0 0 {sy} {tx} {ty})"
                if image_coords else ""))
            group.append(element)
            viewport.append(group)
        return drawing


class SvgDisplay(h.HDevOperatorBase):
    """One adapter per sequential runner invocation; callbacks are process-global."""

    def __init__(self):
        self.windows = {}
        self.active = None
        self.warnings = []
        self.errors = []
        self.defaults = {}
        self.color_cache = {}

    def colors(self, values):
        """Resolve HALCON names (including spaces), hex colors and alpha."""
        key = tuple(str(value) for value in sequence(values))
        if not key:
            raise ValueError("At least one display color is required")
        if key not in self.color_cache:
            with buffer_window() as handle:
                h.set_color(handle, key)
                self.color_cache[key] = rgb_colors(*h.get_rgba(handle))
        return self.color_cache[key].copy()

    def set_style(self, **values):
        # HDevelop style setters also establish defaults for future windows.
        self.defaults.update(values)
        if self.active is not None:
            for key, value in values.items():
                setattr(self.window(), key, value)

    def warn(self, message):
        if message not in self.warnings:
            self.warnings.append(message)

    def window(self):
        if self.active is None:
            raise ValueError("No active SVG window; call dev_open_window first")
        return self.windows[self.active]

    def dev_open_window(self, row, column, width, height, background):
        width, height = int(scalar(width)), int(scalar(height))
        if width == -1:
            width = 512
        if height == -1:
            height = 512
        if width <= 0 or height <= 0:
            raise ValueError("SVG window dimensions must be positive")
        handle = h.create_dict()
        self.windows[handle] = SvgWindow(
            width, height, self.colors([scalar(background)])[0], **self.defaults)
        self.active = handle
        return handle

    def dev_get_window(self):
        self.window()
        return self.active

    def dev_set_window(self, window_handle):
        handle = scalar(window_handle)
        if handle not in self.windows or self.windows[handle].closed:
            raise ValueError("Unknown or closed SVG window")
        self.active = handle

    def dev_close_window(self):
        if self.active is not None:
            self.window().closed = True
            self.active = next(
                (key for key in reversed(self.windows) if not self.windows[key].closed), None)

    def dev_clear_window(self):
        self.window().elements.clear()

    def dev_set_window_extents(self, row, column, width, height):
        window = self.window()
        for name, value in (("width", width), ("height", height)):
            value = int(scalar(value))
            if value > 0:
                setattr(window, name, value)
            elif value != -1:
                raise ValueError("SVG window dimensions must be positive or -1")

    def dev_set_part(self, row_1, column_1, row_2, column_2):
        part = tuple(float(scalar(v)) for v in (row_1, column_1, row_2, column_2))
        if part == (0, 0, -1, -1):
            self.window().part = None
        elif part[2] >= part[0] and part[3] >= part[1]:
            self.window().part = part
        else:
            self.warn(f"dev_set_part: unsupported special coordinates {part}")

    def dev_set_color(self, color_name):
        self.set_style(colors=self.colors(color_name))

    def dev_set_line_width(self, line_width):
        width = float(scalar(line_width))
        if width < 1:
            raise ValueError("Line width must be at least 1")
        self.set_style(line_width=width)

    def dev_set_draw(self, draw_mode):
        mode = scalar(draw_mode)
        if mode in ("fill", "margin"):
            self.set_style(draw_mode=mode)
        else:
            self.warn(f"dev_set_draw: unsupported mode {mode}")

    def dev_set_contour_style(self, style):
        style = scalar(style)
        if style in ("stroke", "fill", "stroke_and_fill"):
            self.set_style(contour_style=style)
        else:
            self.warn(f"dev_set_contour_style: unsupported style {style}")

    def dev_set_shape(self, shape):
        shape = scalar(shape)
        if shape in ("original", "convex", "ellipse", "inner_circle", "outer_circle",
                     "rectangle1", "rectangle2"):
            self.set_style(shape=shape)
        else:
            self.warn(f"dev_set_shape: unsupported shape {shape}; previous shape retained")

    def dev_set_colored(self, num_colors):
        count = scalar(num_colors)
        if count not in h.query_colored():
            raise ValueError(f"Unsupported number of colors: {count}")
        with buffer_window() as handle:
            h.set_colored(handle, count)
            colors = rgb_colors(*h.get_rgb(handle))
        self.set_style(colors=colors)

    def dev_set_lut(self, lut_name):
        values = sequence(lut_name)
        gray_range = None
        if (len(values) == 3 and isinstance(values[0], str)) or len(values) == 770:
            low, high = map(float, values[-2:])
            if not low < high:
                raise ValueError("LUT gray range requires minimum < maximum")
            gray_range = (low, high)
            values = values[:-2]
        if values in (["default"], ["linear"]):
            self.set_style(lut=None, gray_range=gray_range)
            return
        # Sample the native LUT at each byte value; supports installed named
        # palettes, .lut files and HALCON RGB tuples without reimplementing them.
        with buffer_window(256, 1) as handle:
            h.set_lut(handle, values)
            ramp = h.gen_image_const("byte", 256, 1)
            h.set_grayval(ramp, [0] * 256, list(range(256)), list(range(256)))
            h.set_part(handle, 0, 0, 0, 255)
            h.disp_image(ramp, handle)
            rgb = h.dump_window_image(handle)
            lut = tuple(tuple(int(v) for v in h.get_grayval(
                h.access_channel(rgb, channel), [0] * 256, list(range(256))))
                for channel in (1, 2, 3))
        self.set_style(lut=lut, gray_range=gray_range)

    def image_for_display(self, image, window):
        if scalar(h.count_channels(image)) != 1:
            return image
        gray_range = window.gray_range
        if gray_range is None and scalar(h.get_image_type(image)) != "byte":
            low, high, _ = h.min_max_gray(h.get_domain(image), image, 0)
            gray_range = (scalar(low), scalar(high))
        if gray_range is not None:
            low, high = gray_range
            scale = 255 / (high - low) if high > low else 0
            image = h.convert_image_type(
                h.scale_image(h.convert_image_type(image, "real"), scale, -low * scale), "byte")
        if window.lut is not None:
            channels = [h.lut_trans(image, list(table)) for table in window.lut]
            image = h.compose3(*channels)
        return image

    def dev_set_paint(self, mode):
        if sequence(mode) != ["default"]:
            self.warn(f"dev_set_paint: {mode} ignored; using default")

    def dev_display(self, object):
        window = self.window()
        for index in range(1, h.count_obj(object) + 1):
            obj = h.select_obj(object, index)
            kind = scalar(h.get_obj_class(obj))
            color = window.colors[(index - 1) % len(window.colors)]
            if kind == "region" and window.shape != "original":
                obj = h.shape_trans(obj, window.shape)
            if kind == "image":
                width, height = h.get_image_size(obj)
                width, height = scalar(width), scalar(height)
                window.image_size = (width, height)
                with TemporaryDirectory(prefix="hdev-svg-") as temp:
                    path = str(Path(temp) / "image.png")
                    h.write_image(self.image_for_display(obj, window), "png", 0, path)
                    element = draw.Image(-.5, -.5, width, height, path=path, embed=True,
                                         preserveAspectRatio="none")
                window.elements.append((element, True))
            elif kind == "region" and window.draw_mode == "fill":
                # Run rectangles preserve holes and exact pixel-cell boundaries.
                rows, starts, ends = h.get_region_runs(obj)
                path = draw.Path(fill=color, stroke="none")
                for row, start, end in zip(rows, starts, ends):
                    path.M(start - .5, row - .5).H(end + .5).V(row + .5).H(start - .5).Z()
                window.elements.append((path, True))
            elif kind in ("region", "xld_cont"):
                contours = h.gen_contour_region_xld(obj, "border_holes") if kind == "region" else obj
                for contour_index in range(1, h.count_obj(contours) + 1):
                    rows, cols = h.get_contour_xld(h.select_obj(contours, contour_index))
                    if not rows:
                        continue
                    style = window.contour_style if kind == "xld_cont" else "stroke"
                    fill = color if style in ("fill", "stroke_and_fill") else "none"
                    stroke = color if style in ("stroke", "stroke_and_fill") else "none"
                    path = draw.Path(fill=fill, stroke=stroke, stroke_width=window.line_width,
                                     vector_effect="non-scaling-stroke")
                    path.M(cols[0], rows[0])
                    for row, col in zip(rows[1:], cols[1:]):
                        path.L(col, row)
                    if kind == "region":
                        path.Z()
                    window.elements.append((path, True))
            else:
                self.warn(f"dev_display: unsupported object class {kind}")

    def dev_disp_text(self, string, coord_system, row, column, color,
                      gen_param_name, gen_param_value):
        window = self.window()
        coords = scalar(coord_system)
        if coords not in ("image", "window"):
            raise ValueError(f"Unsupported text coordinate system: {coords}")
        rows, cols, strings = sequence(row), sequence(column), sequence(string)
        count = max(len(rows), len(cols))
        if not count or len(rows) not in (1, count) or len(cols) not in (1, count):
            raise ValueError("Text row/column tuples must have matching lengths or be scalar")
        if count > 1 and len(strings) not in (1, count):
            raise ValueError("Multiple positions need one string or one string per position")
        for values, symbols in ((rows, ("top", "center", "bottom")),
                                (cols, ("left", "center", "right"))):
            if any(not isinstance(v, (int, float)) and
                   not (coords == "window" and v in symbols) for v in values):
                raise ValueError("Text positions must be numeric or valid window alignments")
        colors = self.colors([value or window.colors[0]
                              for value in (sequence(color) or window.colors)])
        options = self.text_options(gen_param_name, gen_param_value)
        for i in range(count):
            text = ("\n".join(str(s) for s in strings) if count == 1
                    else str(strings[i % len(strings)]))
            lines = text.rstrip("\n").split("\n")
            block = TextBlock(lines, colors if count == 1 else [colors[i % len(colors)]],
                              rows[i % len(rows)], cols[i % len(cols)], coords, options)
            window.elements.append((block, False))

    def text_options(self, names, values):
        names, values = sequence(names), sequence(values)
        if len(names) != len(values):
            raise ValueError("Text option names and values must have matching lengths")
        supplied = dict(zip(names, values))
        box_color = supplied.get("box_color", "#fce9d4")
        options = {
            "box": True, "box_color": box_color,
            "shadow": not (str(box_color).startswith("#") and len(str(box_color)) == 9),
            "shadow_color": "white" if "box_color" in supplied else "#f28d26",
            "border_radius": 2., "box_padding": 0., "shadow_sigma": 1.5,
            "shadow_dx": 2., "shadow_dy": 2., "border_color": "#ffffff",
            "border_width": 0., "rotate_phi": 0.,
            "rotate_col": "text_center", "rotate_row": "text_center",
        }
        for name, value in supplied.items():
            if name in options:
                options[name] = value
            elif name != "backdrop_blur_sigma" or value != 0:
                self.warn(f"dev_disp_text: unsupported option {name}; ignored")
        for name in ("box", "shadow"):
            value = options[name]
            if value not in (True, False, "true", "false"):
                raise ValueError(f"{name} must be true or false")
            options[name] = value in (True, "true")
        for name in ("box_color", "shadow_color", "border_color"):
            options[name] = self.colors([options[name]])[0]
        for name in ("border_radius", "box_padding", "shadow_sigma", "shadow_dx",
                     "shadow_dy", "border_width", "rotate_phi"):
            options[name] = float(options[name])
            if name in ("border_radius", "box_padding", "shadow_sigma", "border_width") and options[name] < 0:
                raise ValueError(f"{name} must be nonnegative")
        for name, allowed in (("rotate_col", ("text_left", "text_center", "text_right")),
                              ("rotate_row", ("text_top", "text_center", "text_bottom"))):
            if options[name] not in allowed:
                options[name] = float(options[name])
        return options

    def export(self, directory):
        directory = Path(directory).resolve()
        directory.mkdir(parents=True, exist_ok=True)
        results = []
        for index, window in enumerate(self.windows.values(), 1):
            # Exclusive creation avoids overwriting previous runs.
            suffix = 0
            while True:
                name = f"window_{index}" + (f"_{suffix}" if suffix else "") + ".svg"
                path = directory / name
                try:
                    with path.open("x", encoding="utf-8") as stream:
                        stream.write(window.drawing().as_svg())
                    break
                except FileExistsError:
                    suffix += 1
            results.append({"window_id": index, "path": str(path)})
        return results


# The binding prints uncaught callback exceptions to stderr. Capture only at
# this boundary, preserving a failed result instead of silently claiming success.
for _name in vars(h.HDevOperatorBase):
    if _name.startswith("dev_"):
        setattr(SvgDisplay, _name, capture_error(getattr(SvgDisplay, _name)))
