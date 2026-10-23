import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import time
import numpy as np
import pytest
import trimesh
from PySide6.QtWidgets import QApplication
from PySide6.QtWidgets import QAbstractSpinBox, QComboBox, QSlider
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PIL import Image
from lcd_slicer.app import MainWindow, STYLE
from lcd_slicer.core import Settings, Stroke, Slicer, from_mesh, save_project, load_project


def test_desktop_preview_and_pixel_edits(tmp_path):
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(STYLE)
    window = MainWindow()
    window.settings.width_px = 600
    window.settings.height_px = 250
    window.sync_settings()
    window.show()
    window.preview()
    deadline = time.monotonic() + 30
    while window.worker is not None and time.monotonic() < deadline:
        app.processEvents(); time.sleep(.01)
    assert window.worker is None
    assert window.current_image is not None
    assert window.current_image.size == (600, 250)
    window.add_stroke({"points": [[10, 15]], "radius": 0, "value": 255})
    assert window.current_image.getpixel((10, 15)) == 255
    models, settings, edits = window.snapshot()
    image, _ = Slicer(models, settings, edits).render(0)
    np.testing.assert_array_equal(image, window.current_image)
    path = tmp_path / "ui.lcdproj"
    save_project(path, models, settings, edits)
    window.open_project(str(path))
    assert window.edits[0][0] == Stroke([[10, 15]], 0, 255)
    window.dirty = False
    window.close(); app.processEvents()


def wheel_event(widget, delta=120):
    return QWheelEvent(QPointF(12, 12), QPointF(widget.mapToGlobal(QPoint(12, 12))),
                       QPoint(), QPoint(0, delta), Qt.MouseButton.NoButton,
                       Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)


def test_wheel_cannot_change_parameters_even_when_focused():
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.show(); app.processEvents()
    controls = window.findChildren(QAbstractSpinBox) + window.findChildren(QComboBox) + window.findChildren(QSlider)
    assert window.brush_gray in controls and window.pixel_controls["x"] in controls
    for control in controls:
        control.setFocus(); app.processEvents()
        value = control.currentIndex() if isinstance(control, QComboBox) else control.value()
        for delta in (120, -120):
            QApplication.sendEvent(control, wheel_event(control, delta))
            app.processEvents()
            current = control.currentIndex() if isinstance(control, QComboBox) else control.value()
            assert current == value
    assert not window.dirty
    # The requested change preserves intentional keyboard edits and view zoom.
    resolution = window.controls["width_px"]
    resolution.setFocus(); QTest.keyClick(resolution, Qt.Key.Key_Up)
    assert resolution.value() == 11521
    before = window.build_view.zoom
    QApplication.sendEvent(window.build_view, wheel_event(window.build_view))
    assert window.build_view.zoom > before
    window.dirty = False
    window.close(); app.processEvents()


def test_grayscale_brush_mouse_stroke_preview_export_and_reopen(tmp_path):
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.settings.width_px = 200; window.settings.height_px = 100; window.settings.layer_mm = 10
    window.sync_settings(); window.show(); app.processEvents(); window.preview()
    deadline = time.monotonic() + 30
    while window.worker is not None and time.monotonic() < deadline:
        app.processEvents(); time.sleep(.01)
    assert window.current_image is not None
    window.brush.setValue(0); window.brush_gray.setValue(128)
    window.tool_buttons["paint"].click()
    point = window.mask_view.mapFromScene(QPointF(10.5, 15.5))
    QTest.mousePress(window.mask_view.viewport(), Qt.MouseButton.LeftButton, pos=point)
    assert window.mask_view.path_item.pen().color().getRgb() == (128, 128, 128, 255)
    QTest.mouseRelease(window.mask_view.viewport(), Qt.MouseButton.LeftButton, pos=point)
    assert window.edits[0][-1].value == 128
    painted = window.edits[0][-1].points[0]
    assert window.current_image.getpixel(tuple(painted)) == 128
    window.brush_gray.setValue(64)
    second = window.mask_view.mapFromScene(QPointF(25.5, 15.5))
    QTest.mouseClick(window.mask_view.viewport(), Qt.MouseButton.LeftButton, pos=second)
    assert window.edits[0][-1].value == 64
    window.tool_buttons["erase"].click()
    erase = window.mask_view.mapFromScene(QPointF(35.5, 15.5))
    QTest.mouseClick(window.mask_view.viewport(), Qt.MouseButton.LeftButton, pos=erase)
    assert window.edits[0][-1].value == 0
    assert window.brush_gray.value() == 64
    models, settings, edits = window.snapshot()
    output = tmp_path / "gray"
    Slicer(models, settings, edits).export(output)
    with Image.open(output / "layer_000001.png") as saved:
        np.testing.assert_array_equal(saved, window.current_image)
        assert saved.getpixel(tuple(painted)) == 128
    path = tmp_path / "gray.lcdproj"
    save_project(path, models, settings, edits)
    window.open_project(str(path))
    assert [stroke.value for stroke in window.edits[0]] == [128, 64, 0]
    image, _ = Slicer(window.models, window.settings, window.edits).render(0)
    with Image.open(output / "layer_000001.png") as saved:
        np.testing.assert_array_equal(image, saved)
    before = window.mask_view.transform().m11()
    window.mask_view.wheelEvent(wheel_event(window.mask_view))
    assert window.mask_view.transform().m11() > before
    window.dirty = False
    window.close(); app.processEvents()


def test_editable_pixel_pitch_controls_physical_raster_and_roundtrip(tmp_path):
    app = QApplication.instance() or QApplication([])
    window = MainWindow(empty=True)
    window.settings = Settings(width_px=200, height_px=100, width_mm=40, height_mm=30, layer_mm=1)
    window.sync_settings()
    assert window.pixel_controls["x"].value() == 200
    assert window.pixel_controls["y"].value() == 300
    window.pixel_controls["x"].setValue(100)
    window.pixel_controls["y"].setValue(150)
    assert (window.settings.width_px, window.settings.height_px) == (200, 100)
    assert (window.settings.width_mm, window.settings.height_mm) == (20, 15)
    model = from_mesh(trimesh.creation.box((10, 6, 1)), "test", window.settings)
    window.models = [model]
    image, context = Slicer(window.models, window.settings).render(0)
    assert np.count_nonzero(image) == 100 * 40
    assert context.pixel_size_mm == pytest.approx((.1, .15))
    window.controls["width_px"].setValue(400)
    assert window.settings.width_mm == 20
    assert window.pixel_controls["x"].value() == 50
    window.controls["height_mm"].setValue(20)
    assert window.pixel_controls["y"].value() == 200
    # A fractional micron input must survive unrelated setting changes and saving.
    window.pixel_controls["x"].setValue(19.123456)
    expected_width = 400 * 19.123456 / 1000
    window.controls["gamma"].setValue(1.1)
    assert window.settings.width_mm == pytest.approx(expected_width, abs=1e-9)
    path = tmp_path / "pitch.lcdproj"
    save_project(path, window.models, window.settings, {})
    window.open_project(str(path))
    assert window.pixel_controls["x"].value() == pytest.approx(19.123456, abs=1e-6)
    assert window.pixel_controls["y"].value() == 200
    window.dirty = False
    window.close(); app.processEvents()
