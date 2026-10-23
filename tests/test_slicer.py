from dataclasses import replace
import json
from pathlib import Path
import threading

import numpy as np
import pytest
from PIL import Image
import trimesh

from lcd_slicer.core import (Settings, Slicer, Stroke, SliceError, Cancelled,
                             from_mesh, demo_model, save_project, load_project, load_model)


def config(**kwargs):
    return replace(Settings(width_px=200, height_px=100, width_mm=40, height_mm=30, layer_mm=1), **kwargs)


def box(settings, size=(10, 6, 2)):
    return from_mesh(trimesh.creation.box(extents=size), "box", settings)


def test_pixel_centers_and_nonsquare_pitch():
    s = config()
    image, _ = Slicer([box(s)], s).render(0)
    ys, xs = np.nonzero(np.asarray(image))
    assert (xs.min(), xs.max(), ys.min(), ys.max()) == (75, 124, 40, 59)
    assert len(xs) == 50 * 20


def test_annular_hole_and_overlapping_objects_union():
    s = config(width_mm=50, height_mm=50, width_px=500, height_px=500)
    ring = from_mesh(trimesh.creation.annulus(r_min=5, r_max=12, height=2, sections=96), "ring", s)
    image, _ = Slicer([ring], s).render(0)
    assert image.getpixel((250, 250)) == 0
    assert image.getpixel((330, 250)) == 255
    assert image.getpixel((390, 250)) == 0
    actual_area = np.count_nonzero(image) * .1**2
    assert abs(actual_area - np.pi * (12**2 - 5**2)) < 1
    plug = box(s, (12, 12, 2))
    result, _ = Slicer([ring, plug], s).render(0)
    assert result.getpixel((250, 250)) == 255
    # Union retains the annulus outside the overlapping plug.
    assert result.getpixel((330, 250)) == 255


def test_transform_and_partial_last_layer():
    s = config(layer_mm=1)
    m = box(s, (10, 6, 2.1)); m.rz = 90; m.scale = 50
    slicer = Slicer([m], s)
    assert slicer.count == 2
    assert slicer.context(1).sample_z_mm == pytest.approx(1.025)
    image, _ = slicer.render(1)
    assert np.count_nonzero(image) > 0
    assert m.bounds[1] - m.bounds[0] == pytest.approx([3, 5, 1.05])


def test_export_matches_preview_plugin_mirror_and_manual_edits(tmp_path):
    plugin = tmp_path / "processor.py"
    plugin.write_text("def process(image, context):\n    image[4, 7] = 123\n    return image\n")
    s = config(plugin_path=str(plugin), mirror_x=True, invert=True)
    edits = {0: [Stroke([[12, 9]], 0, 80)]}
    slicer = Slicer([box(s)], s, edits)
    preview, _ = slicer.render(0)
    assert preview.getpixel((192, 4)) == 132
    assert preview.getpixel((12, 9)) == 80
    destination = tmp_path / "export"
    slicer.export(destination)
    with Image.open(destination / "layer_000001.png") as saved:
        assert saved.mode == "L" and saved.size == (200, 100)
        np.testing.assert_array_equal(saved, preview)
    job = json.loads((destination / "job.json").read_text(encoding="utf-8"))
    assert job["status"] == "complete" and job["written"] == 2
    with pytest.raises(SliceError): slicer.export(destination)


def test_high_resolution_png_and_antialias(tmp_path):
    s = Settings(layer_mm=10, antialias=2)
    slicer = Slicer([demo_model(s)], s)
    destination = tmp_path / "12k"
    slicer.export(destination)
    with Image.open(destination / "layer_000001.png") as image:
        assert image.size == (11520, 5120) and image.mode == "L"
        assert image.getpixel((5760, 2560)) == 0
        assert np.any((np.asarray(image) > 0) & (np.asarray(image) < 255))


def test_boundary_checks_cancel_and_broken_plugin(tmp_path):
    s = config()
    m = box(s); m.x = 0
    with pytest.raises(SliceError, match="超出"): Slicer([m], s)
    event = threading.Event(); event.set()
    with pytest.raises(Cancelled): Slicer([box(s)], s, cancel=event).export(tmp_path / "cancelled")
    assert not (tmp_path / "cancelled").exists()
    plugin = tmp_path / "wrong.py"; plugin.write_text("def process(image, context):\n    return image[:2]\n")
    with pytest.raises(SliceError, match="uint8"):
        Slicer([box(s)], replace(s, plugin_path=str(plugin))).export(tmp_path / "wrong")
    assert not (tmp_path / "wrong").exists()


def test_project_embeds_meshes_and_edits(tmp_path):
    s = config(); m = box(s); m.rz = 23
    edits = {1: [Stroke([[4, 5], [8, 9]], 2, 255)]}
    path = tmp_path / "saved.lcdproj"
    save_project(path, [m], s, edits)
    models, settings, loaded_edits = load_project(path)
    assert settings == s and loaded_edits == edits
    np.testing.assert_array_equal(models[0].faces, m.faces)
    before, _ = Slicer([m], s, edits).render(1)
    after, _ = Slicer(models, settings, loaded_edits).render(1)
    np.testing.assert_array_equal(before, after)


def test_stl_file_import_and_open_section_rejection(tmp_path):
    s = config(); mesh = trimesh.creation.box((10, 6, 2))
    path = tmp_path / "cube.stl"; mesh.export(path)
    model = load_model(str(path), s)
    assert model.watertight
    assert np.count_nonzero(Slicer([model], s).render(0)[0]) == 1000
    # Remove one vertical triangle so the mid-height contour cannot close.
    triangles = mesh.triangles
    vertical = np.ptp(triangles[:, :, 2], axis=1) > 0
    face_index = np.flatnonzero(vertical)[0]
    broken = trimesh.Trimesh(mesh.vertices, np.delete(mesh.faces, face_index, axis=0), process=False)
    with pytest.raises(SliceError, match="未闭合"):
        Slicer([from_mesh(broken, "open", s)], s).render(0)
