from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable
import importlib.util
import io
import json
import math
import os
import threading
import uuid
import zipfile

import numpy as np
from PIL import Image, ImageDraw, ImageFilter
import trimesh
from shapely.geometry import LineString, Polygon, MultiPolygon, GeometryCollection
from shapely.ops import polygonize_full, unary_union


class SliceError(ValueError):
    pass


class Cancelled(Exception):
    pass


@dataclass
class Settings:
    width_px: int = 11520
    height_px: int = 5120
    width_mm: float = 218.88
    height_mm: float = 97.28
    max_z_mm: float = 200.0
    layer_mm: float = 0.05
    antialias: int = 1
    edge_px: int = 0
    gamma: float = 1.0
    mirror_x: bool = False
    mirror_y: bool = False
    invert: bool = False
    plugin_path: str = ""

    @property
    def pixel_mm(self):
        return self.width_mm / self.width_px, self.height_mm / self.height_px

    def validate(self):
        if not (1 <= self.width_px <= 65536 and 1 <= self.height_px <= 65536):
            raise SliceError("分辨率每个方向须在 1–65536 像素之间。")
        if self.width_px * self.height_px > 268_435_456:
            raise SliceError("当前版本每层最多支持 2.68 亿像素，请降低分辨率。")
        values = (self.width_mm, self.height_mm, self.max_z_mm, self.layer_mm, self.gamma)
        if not all(math.isfinite(v) and v > 0 for v in values):
            raise SliceError("打印尺寸、层厚和 Gamma 必须为有限正数。")
        if self.antialias not in (1, 2, 4):
            raise SliceError("抗锯齿仅支持 1、2、4 倍。")
        if not -20 <= self.edge_px <= 20:
            raise SliceError("边缘补偿须在 -20 到 20 像素之间。")


@dataclass
class Model:
    name: str
    vertices: np.ndarray
    faces: np.ndarray
    source: str = ""
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    rx: float = 0.0
    ry: float = 0.0
    rz: float = 0.0
    scale: float = 100.0
    enabled: bool = True

    def world_vertices(self):
        if not math.isfinite(self.scale) or self.scale <= 0:
            raise SliceError(f"{self.name}：缩放比例必须大于 0。")
        angles = np.radians([self.rx, self.ry, self.rz])
        matrix = trimesh.transformations.euler_matrix(*angles)[:3, :3]
        v = (np.asarray(self.vertices) * (self.scale / 100.0)) @ matrix.T
        v[:, 2] -= v[:, 2].min()
        v += [self.x, self.y, self.z]
        return v

    @property
    def bounds(self):
        v = self.world_vertices()
        return np.array([v.min(axis=0), v.max(axis=0)])

    @property
    def watertight(self):
        return trimesh.Trimesh(self.vertices, self.faces, process=False).is_watertight


def from_mesh(mesh: trimesh.Trimesh, name: str, settings: Settings, source=""):
    if not isinstance(mesh, trimesh.Trimesh) or len(mesh.faces) == 0:
        raise SliceError("文件中没有可切片的三角网格。")
    if not np.isfinite(mesh.vertices).all():
        raise SliceError("模型包含无效坐标。")
    vertices = np.array(mesh.vertices, dtype=np.float64)
    bounds = np.array([vertices.min(axis=0), vertices.max(axis=0)])
    vertices[:, :2] -= bounds[:, :2].mean(axis=0)
    vertices[:, 2] -= bounds[0, 2]
    return Model(name, vertices, np.asarray(mesh.faces, dtype=np.int64), source,
                 settings.width_mm / 2, settings.height_mm / 2)


def load_model(path: str, settings: Settings):
    mesh = trimesh.load(path, force="mesh", process=True)
    if isinstance(mesh, trimesh.Scene):
        mesh = mesh.to_mesh()
    return from_mesh(mesh, Path(path).name, settings, str(Path(path).resolve()))


def demo_model(settings: Settings):
    return from_mesh(trimesh.creation.annulus(r_min=9, r_max=20, height=10, sections=96),
                     "校准圆环 · Ø40 / Ø18 / 10 mm", settings)


def validate_scene(models: list[Model], settings: Settings):
    settings.validate()
    active = [m for m in models if m.enabled]
    if not active:
        raise SliceError("请先导入或启用至少一个模型。")
    for m in active:
        b = m.bounds
        if b[0, 0] < -1e-6 or b[0, 1] < -1e-6 or b[0, 2] < -1e-6 or \
                b[1, 0] > settings.width_mm + 1e-6 or \
                b[1, 1] > settings.height_mm + 1e-6 or b[1, 2] > settings.max_z_mm + 1e-6:
            raise SliceError(f"{m.name} 超出打印范围。请调整位置、缩放或打印面积。")
        if b[1, 2] - b[0, 2] <= 1e-9:
            raise SliceError(f"{m.name} 没有有效高度。")
    return active


def layer_count(models, settings):
    active = validate_scene(models, settings)
    height = max(m.bounds[1, 2] for m in active)
    count = int(math.ceil(height / settings.layer_mm - 1e-10))
    if count > 1_000_000:
        raise SliceError("总层数超过 100 万，请增大层厚。")
    return max(1, count)


@dataclass(frozen=True)
class LayerContext:
    layer_index: int
    sample_z_mm: float
    layer_top_mm: float
    layer_height_mm: float
    resolution: tuple[int, int]
    build_size_mm: tuple[float, float]
    pixel_size_mm: tuple[float, float]


@dataclass
class Stroke:
    points: list[list[float]]
    radius: int = 1
    value: int = 255


def polygons(geom):
    if isinstance(geom, Polygon):
        yield geom
    elif isinstance(geom, (MultiPolygon, GeometryCollection)):
        for g in geom.geoms:
            yield from polygons(g)


class Slicer:
    """Model section -> solid union -> pixel-center raster -> processing -> edits.

    Image origin: upper left. World origin: lower left. Samples lie at layer
    midplanes; the last layer is sampled midway through its occupied Z interval.
    Arrays are allocated one layer at a time, never for an entire build.
    """
    def __init__(self, models: list[Model], settings: Settings,
                 edits: dict[int, list[Stroke]] | None = None,
                 cancel: threading.Event | None = None):
        self.models = validate_scene(models, settings)
        self.settings = settings
        self.count = layer_count(models, settings)
        self.top = max(m.bounds[1, 2] for m in self.models)
        self.triangles = [m.world_vertices()[m.faces] for m in self.models]
        self.z_ranges = [(t[:, :, 2].min(1), t[:, :, 2].max(1)) for t in self.triangles]
        self.edits = edits or {}
        self.cancel = cancel or threading.Event()
        self.plugin = None
        if settings.plugin_path:
            path = Path(settings.plugin_path)
            if not path.is_file():
                raise SliceError(f"找不到处理插件：{path}")
            spec = importlib.util.spec_from_file_location("lumaslice_user_processor_" + uuid.uuid4().hex, path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            self.plugin = getattr(module, "process", None)
            if not callable(self.plugin):
                raise SliceError("处理插件须提供 process(image, context) 函数。")

    def check_cancel(self):
        if self.cancel.is_set():
            raise Cancelled("已取消；完整导出目录未生成。")

    def context(self, index):
        if not 0 <= index < self.count:
            raise SliceError("层号超出范围。")
        lower = index * self.settings.layer_mm
        upper = min((index + 1) * self.settings.layer_mm, self.top)
        return LayerContext(index, (lower + upper) / 2, upper,
                            self.settings.layer_mm,
                            (self.settings.width_px, self.settings.height_px),
                            (self.settings.width_mm, self.settings.height_mm), self.settings.pixel_mm)

    def section(self, z):
        regions = []
        for model, all_tri, (zmin, zmax) in zip(self.models, self.triangles, self.z_ranges):
            self.check_cancel()
            tri = all_tri[(zmin <= z) & (zmax > z)]
            if not len(tri):
                continue
            # Half-open edge convention eliminates double intersections at vertices.
            segments = np.empty((len(tri), 2, 2), dtype=np.float64)
            counts = np.zeros(len(tri), dtype=np.int32)
            for a, b in ((0, 1), (1, 2), (2, 0)):
                za, zb = tri[:, a, 2], tri[:, b, 2]
                cross = ((za <= z) & (zb > z)) | ((zb <= z) & (za > z))
                ix = np.flatnonzero(cross)
                if len(ix):
                    fraction = (z - za[ix]) / (zb[ix] - za[ix])
                    p = tri[ix, a, :2] + fraction[:, None] * (tri[ix, b, :2] - tri[ix, a, :2])
                    segments[ix, counts[ix]] = p
                    counts[ix] += 1
            segments = segments[counts == 2]
            segments = np.round(segments, 7)
            segments = segments[np.linalg.norm(segments[:, 1] - segments[:, 0], axis=1) > 1e-9]
            if not len(segments):
                continue
            # Identical facets must not turn a valid outline into an even parity hole.
            flat = np.sort(segments.view([("x", "f8"), ("y", "f8")]).reshape(-1, 2), axis=1)
            _, unique = np.unique(flat, axis=0, return_index=True)
            segments = segments[np.sort(unique)]
            faces, cuts, dangles, invalid = polygonize_full([LineString(s) for s in segments])
            if not cuts.is_empty or not dangles.is_empty or not invalid.is_empty:
                raise SliceError(f"{model.name} 在 Z={z:.5f} mm 的截面未闭合；请修复网格后重新导入。")
            # polygonize also returns disks inside holes. Classify each cell against
            # the original segments rather than filling every polygon indiscriminately.
            for p in faces.geoms:
                point = p.representative_point()
                x, y = point.x, point.y
                a, b = segments[:, 0], segments[:, 1]
                mask = ((a[:, 1] > y) != (b[:, 1] > y))
                aa, bb = a[mask], b[mask]
                intersections = aa[:, 0] + (y - aa[:, 1]) * (bb[:, 0] - aa[:, 0]) / (bb[:, 1] - aa[:, 1])
                if np.count_nonzero(intersections > x) % 2:
                    regions.append(p)
        return unary_union(regions) if regions else GeometryCollection()

    def rasterize(self, geom):
        s = self.settings
        image = Image.new("L", (s.width_px, s.height_px), 0)
        if geom.is_empty:
            return image
        factor = s.antialias
        px, py = s.pixel_mm
        xmin, ymin, xmax, ymax = geom.bounds
        left = max(0, int(math.floor(xmin / px)) - 2)
        right = min(s.width_px, int(math.ceil(xmax / px)) + 2)
        top = max(0, int(math.floor(s.height_px - ymax / py)) - 2)
        bottom = min(s.height_px, int(math.ceil(s.height_px - ymin / py)) + 2)
        width, height = right - left, bottom - top
        if width <= 0 or height <= 0:
            return image
        if width * height * factor * factor > 300_000_000:
            raise SliceError("当前抗锯齿区域占用内存过大，请降低抗锯齿倍数或分辨率。")
        mask = np.zeros((height * factor, width * factor), dtype=np.uint8)
        for polygon in polygons(geom):
            rings = [polygon.exterior, *polygon.interiors]
            starts, ends = [], []
            for ring in rings:
                points = np.asarray(ring.coords).copy()
                points[:, 0] = (points[:, 0] / px - left) * factor
                points[:, 1] = (s.height_px - points[:, 1] / py - top) * factor
                starts.append(points[:-1]); ends.append(points[1:])
            a, b = np.concatenate(starts), np.concatenate(ends)
            row0 = max(0, int(np.floor(min(a[:, 1].min(), b[:, 1].min()))))
            row1 = min(len(mask), int(np.ceil(max(a[:, 1].max(), b[:, 1].max()))))
            for row in range(row0, row1):
                if row % 128 == 0:
                    self.check_cancel()
                y = row + 0.5
                crossing = (a[:, 1] > y) != (b[:, 1] > y)
                aa, bb = a[crossing], b[crossing]
                x = np.sort(aa[:, 0] + (y - aa[:, 1]) * (bb[:, 0] - aa[:, 0]) / (bb[:, 1] - aa[:, 1]))
                for start, end in zip(x[::2], x[1::2]):
                    lo = max(0, int(math.ceil(start - 0.5 - 1e-9)))
                    hi = min(mask.shape[1], int(math.ceil(end - 0.5 - 1e-9)))
                    mask[row, lo:hi] = 255
        crop = Image.fromarray(mask)
        if factor > 1:
            crop = crop.resize((width, height), Image.Resampling.BOX)
        image.paste(crop, (left, top))
        return image

    def render(self, index: int):
        self.check_cancel()
        context = self.context(index)
        image = self.rasterize(self.section(context.sample_z_mm))
        s = self.settings
        if s.edge_px:
            size = 2 * abs(s.edge_px) + 1
            image = image.filter(ImageFilter.MaxFilter(size) if s.edge_px > 0 else ImageFilter.MinFilter(size))
        if s.gamma != 1:
            lut = [round(255 * ((i / 255) ** (1 / s.gamma))) for i in range(256)]
            image = image.point(lut)
        if self.plugin:
            self.check_cancel()
            output = self.plugin(np.asarray(image).copy(), context)
            if not isinstance(output, np.ndarray) or output.dtype != np.uint8 or \
                    output.shape != (s.height_px, s.width_px):
                raise SliceError("插件输出必须为同尺寸的二维 uint8 NumPy 数组。")
            image = Image.fromarray(np.ascontiguousarray(output))
        if s.mirror_x:
            image = image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        if s.mirror_y:
            image = image.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
        if s.invert:
            image = image.point(lambda x: 255 - x)
        apply_strokes(image, self.edits.get(index, []))
        self.check_cancel()
        return image, context

    def export(self, destination: str | Path, progress: Callable | None = None):
        dest = Path(destination).resolve()
        if dest.exists():
            raise SliceError("导出目录已存在。请选择一个新的目录名，以免覆盖图片。")
        dest.parent.mkdir(parents=True, exist_ok=True)
        stage = dest.parent / ("." + dest.name + ".partial-" + uuid.uuid4().hex[:8])
        stage.mkdir()
        metadata = {"format": "LumaSlice PNG stack", "version": 1, "status": "incomplete",
                    "settings": asdict(self.settings), "layer_count": self.count, "written": 0,
                    "image_mode": "L", "bit_depth": 8, "origin": "upper-left",
                    "world_origin": "lower-left", "pixel_size_mm": self.settings.pixel_mm,
                    "slice_sampling": "midplane; last layer clamped to model top",
                    "processing_order": ["raster", "square_edge_filter", "gamma", "plugin", "mirror", "invert", "manual_edits"],
                    "models": [m.name for m in self.models], "layers": []}
        try:
            for i in range(self.count):
                self.check_cancel()
                image, ctx = self.render(i)
                name = f"layer_{i + 1:06d}.png"
                image.save(stage / name, compress_level=3)
                metadata["written"] = i + 1
                metadata["layers"].append({"file": name, "sample_z_mm": ctx.sample_z_mm,
                                           "layer_top_mm": ctx.layer_top_mm})
                if progress:
                    progress(i + 1, self.count)
            self.check_cancel()
            metadata["status"] = "complete"
            (stage / "job.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
            # rename (not replace) refuses an existing target on Windows.
            if dest.exists():
                raise SliceError("目标目录在导出期间被创建，未覆盖已有内容。")
            stage.rename(dest)
            return dest
        except Exception as exc:
            metadata["status"] = "cancelled" if isinstance(exc, Cancelled) else "failed"
            metadata["error"] = str(exc)
            (stage / "job.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
            raise


def apply_strokes(image, strokes):
    draw = ImageDraw.Draw(image)
    for stroke in strokes:
        points = [tuple(map(float, p)) for p in stroke.points]
        radius, value = max(0, int(stroke.radius)), int(stroke.value)
        if len(points) > 1:
            draw.line(points, fill=value, width=2 * radius + 1)
        for x, y in points:
            # Integer indices explicitly address pixels; radius 0 edits one pixel.
            x, y = int(x), int(y)
            if radius == 0:
                draw.point((x, y), fill=value)
            else:
                draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=value)


def save_project(path, models, settings, edits):
    path = Path(path)
    state = {"format": "LumaSlice", "version": 1, "settings": asdict(settings),
             "models": [], "edits": {str(k): [asdict(s) for s in v] for k, v in edits.items()}}
    temporary = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex[:8])
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for i, m in enumerate(models):
                state["models"].append({k: getattr(m, k) for k in m.__dataclass_fields__ if k not in ("vertices", "faces")})
                buffer = io.BytesIO()
                np.savez_compressed(buffer, vertices=m.vertices, faces=m.faces)
                archive.writestr(f"mesh_{i}.npz", buffer.getvalue())
            archive.writestr("project.json", json.dumps(state, ensure_ascii=False, indent=2))
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def load_project(path):
    with zipfile.ZipFile(path) as archive:
        state = json.loads(archive.read("project.json"))
        if state.get("format") != "LumaSlice" or state.get("version") != 1:
            raise SliceError("不支持的项目格式。")
        settings = Settings(**state["settings"])
        settings.validate()
        models = []
        for i, item in enumerate(state["models"]):
            with np.load(io.BytesIO(archive.read(f"mesh_{i}.npz")), allow_pickle=False) as mesh:
                v, f = mesh["vertices"].copy(), mesh["faces"].copy()
                if v.ndim != 2 or v.shape[1] != 3 or not np.isfinite(v).all() or \
                        f.ndim != 2 or f.shape[1] != 3 or not np.issubdtype(f.dtype, np.integer) or \
                        not len(v) or not len(f) or f.min() < 0 or f.max() >= len(v):
                    raise SliceError("项目包含无效网格。")
                models.append(Model(vertices=v, faces=f, **item))
        edits = {int(k): [Stroke(**s) for s in v] for k, v in state.get("edits", {}).items()}
        return models, settings, edits
