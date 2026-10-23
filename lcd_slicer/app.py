from __future__ import annotations

import argparse
import json
from copy import deepcopy
from dataclasses import replace
from datetime import datetime
from pathlib import Path
import os
import sys
import threading
import traceback

from PySide6.QtCore import Qt, QThread, Signal, QTimer, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QFont, QFontDatabase, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel, QPushButton, QHBoxLayout, QVBoxLayout,
    QFormLayout, QFrame, QListWidget, QListWidgetItem, QDoubleSpinBox, QSpinBox,
    QComboBox, QCheckBox, QScrollArea, QStackedWidget, QSlider, QButtonGroup,
    QFileDialog, QMessageBox, QProgressBar, QSizePolicy, QSplitter,
)

from . import __version__
from .core import (Settings, Model, Stroke, Slicer, SliceError, Cancelled,
                   demo_model, load_model, layer_count, save_project, load_project, apply_strokes)
from .views import BuildView, MaskView


STYLE = """
QMainWindow, QWidget { background: #f5f6f8; color: #263347; font-family: 'Microsoft YaHei UI', 'Segoe UI'; font-size: 12px; }
QMenuBar { background: #ffffff; padding: 3px 12px; border-bottom: 1px solid #e5e8ed; }
QMenuBar::item:selected, QMenu::item:selected { background: #fff0e5; color: #c65b18; }
QMenu { background: white; padding: 6px; border: 1px solid #e1e5eb; }
QFrame#header { background: white; border-bottom: 1px solid #e0e5eb; }
QFrame#sidebar { background: white; border-right: 1px solid #e2e6ed; }
QFrame#rightbar { background: white; border-left: 1px solid #e2e6ed; }
QFrame#card { background: white; border: 1px solid #e2e7ed; border-radius: 9px; }
QLabel { background: transparent; }
QLabel#brand { font-size: 21px; font-weight: 700; color: #1d2c42; }
QLabel#mark { background: #f58238; color: white; font-size: 23px; font-weight: 700; border-radius: 9px; }
QLabel#muted { color: #8390a1; font-size: 11px; }
QLabel#title { color: #2b384c; font-size: 12px; font-weight: 700; }
QLabel#metric { color: #df6c29; font-size: 13px; font-weight: 600; }
QLabel#badge { color: #bd6024; background: #fff1e6; padding: 4px 9px; border-radius: 5px; font-size: 10px; font-weight: 700; }
QPushButton { background: white; border: 1px solid #dde3eb; border-radius: 6px; padding: 7px 12px; min-height: 17px; font-weight: 500; }
QPushButton:hover { background: #f6f8fb; border-color: #bcc8d7; }
QPushButton:pressed { background: #eaf0f7; }
QPushButton:disabled { color: #a9b0ba; background: #f5f6f8; border-color: #e8ebef; }
QPushButton#primary { background: #ed7a32; color: white; border: 1px solid #ed7a32; font-weight: 700; }
QPushButton#primary:hover { background: #dc6b27; }
QPushButton#primary:disabled { background: #f4bf9e; border-color: #f4bf9e; }
QPushButton#tab { border: none; background: transparent; color: #8590a0; padding: 11px 22px; }
QPushButton#tab:checked { color: #dc6b27; background: #fff0e4; }
QPushButton#small { padding: 4px 9px; min-height: 15px; font-size: 11px; }
QPushButton#small:checked { color: #d46928; background: #fff0e5; border-color: #f0bd99; }
QSpinBox, QDoubleSpinBox, QComboBox { background: #f8f9fb; border: 1px solid #e0e5ec; border-radius: 5px; padding: 5px 7px; min-height: 19px; selection-background-color: #f58238; }
QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus { border-color: #f29c63; background: white; }
QListWidget { background: white; border: none; outline: none; padding: 2px; }
QListWidget::item { padding: 12px 6px; margin: 2px 0; border: 1px solid transparent; border-radius: 6px; }
QListWidget::item:selected { background: #fff1e7; color: #c65e24; border-color: #f4d1b8; }
QCheckBox { spacing: 7px; background: transparent; }
QCheckBox::indicator { width: 14px; height: 14px; border: 1px solid #c8d1dd; border-radius: 3px; background: white; }
QCheckBox::indicator:checked { background: #ed7a32; border-color: #ed7a32; image: none; }
QScrollArea { background: transparent; border: none; }
QScrollBar:vertical { background: transparent; width: 7px; margin: 0; }
QScrollBar::handle:vertical { background: #ccd3dd; border-radius: 3px; min-height: 28px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QSlider::groove:horizontal { background: #dce3ec; height: 4px; border-radius: 2px; }
QSlider::sub-page:horizontal { background: #ef914f; border-radius: 2px; }
QSlider::handle:horizontal { background: #ed7a32; width: 13px; margin: -5px 0; border-radius: 6px; }
QProgressBar { border: none; background: #e9edf3; border-radius: 3px; height: 5px; text-align: center; }
QProgressBar::chunk { background: #ee823b; border-radius: 3px; }
QStatusBar { background: white; border-top: 1px solid #e2e7ed; color: #768398; }
QSplitter::handle { background: #e4e8ef; width: 1px; }
QToolTip { background: #263347; color: white; border: none; padding: 6px; }
"""


def label(text, name=None, wrap=False):
    w = QLabel(text)
    if name:
        w.setObjectName(name)
    w.setWordWrap(wrap)
    return w


def button(text, callback, name=None):
    w = QPushButton(text)
    if name:
        w.setObjectName(name)
    w.clicked.connect(callback)
    return w


def box_layout(orientation="v", margins=(0, 0, 0, 0), spacing=8):
    layout = QVBoxLayout() if orientation == "v" else QHBoxLayout()
    layout.setContentsMargins(*margins)
    layout.setSpacing(spacing)
    return layout


def card(title):
    w = QFrame()
    w.setObjectName("card")
    lay = box_layout(margins=(13, 13, 13, 13), spacing=11)
    w.setLayout(lay)
    lay.addWidget(label(title, "title"))
    return w, lay


class ParameterSpinBox(QSpinBox):
    def wheelEvent(self, event):
        event.ignore()


class ParameterDoubleSpinBox(QDoubleSpinBox):
    def wheelEvent(self, event):
        event.ignore()


class ParameterComboBox(QComboBox):
    def wheelEvent(self, event):
        event.ignore()


class ParameterSlider(QSlider):
    def wheelEvent(self, event):
        event.ignore()


class PreciseSpinBox(ParameterDoubleSpinBox):
    """Keep numeric precision without padding every displayed value with zeros."""
    def textFromValue(self, value):
        text = self.locale().toString(value, "f", self.decimals())
        decimal = self.locale().decimalPoint()
        return text.rstrip("0").rstrip(decimal) if decimal in text else text


class Job(QThread):
    result = Signal(object)
    failed = Signal(str)
    progress = Signal(int, str)

    def __init__(self, task, parent=None):
        super().__init__(parent)
        self.task = task
        self.cancel = threading.Event()

    def run(self):
        try:
            self.result.emit(self.task(self))
        except Cancelled as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            self.failed.emit(str(exc) or traceback.format_exc())


class MainWindow(QMainWindow):
    def __init__(self, empty=False):
        super().__init__()
        self.settings = Settings()
        self.models: list[Model] = [] if empty else [demo_model(self.settings)]
        self.edits: dict[int, list[Stroke]] = {}
        self.project_path = None
        self.dirty = False
        self.worker = None
        self.current_image = None
        self.rendered_index = None
        self._updating = False
        self._closing = False
        self.setWindowTitle(f"LumaSlice v{__version__} · LCD 切片工作台[*]")
        self.resize(1460, 920)
        self.setMinimumSize(1080, 680)
        self.setAcceptDrops(True)
        self.debounce = QTimer(self)
        self.debounce.setSingleShot(True)
        self.debounce.setInterval(350)
        self.debounce.timeout.connect(self.preview)
        self.build_menu()
        self.build_ui()
        self.refresh_models()
        self.sync_settings()
        self.refresh_scene()
        self.statusBar().showMessage("已就绪 · 当前为内置校准圆环，可删除后导入自己的模型")

    def build_menu(self):
        menu = self.menuBar().addMenu("文件")
        actions = [("新建项目", "Ctrl+N", self.new_project), ("导入模型…", "Ctrl+O", self.import_dialog),
                   ("打开项目…", "Ctrl+Shift+O", self.open_dialog), ("保存项目", "Ctrl+S", self.save),
                   ("项目另存为…", "Ctrl+Shift+S", lambda: self.save(True))]
        for text, key, fn in actions:
            action = QAction(text, self)
            action.setShortcut(QKeySequence(key)); action.triggered.connect(fn)
            menu.addAction(action)
        menu.addSeparator()
        menu.addAction("退出", self.close)
        view = self.menuBar().addMenu("视图")
        view.addAction("三维平台", lambda: self.switch_tab(0))
        view.addAction("切片预览", lambda: self.switch_tab(1))
        view.addAction("适应窗口", self.fit_current)
        help_menu = self.menuBar().addMenu("帮助")
        help_menu.addAction("使用说明", self.show_help)
        help_menu.addAction("关于 LumaSlice", lambda: QMessageBox.about(self, "关于 LumaSlice",
            f"LumaSlice {__version__}\n独立 LCD PNG 切片工具\n\n本地计算，无需联网。\n参照常见切片软件的工作流程独立实现。\n\n当前版本不自动生成支撑、排液孔或打印机控制文件。"))

    def build_ui(self):
        root = QWidget(); self.setCentralWidget(root)
        layout = box_layout(spacing=0); root.setLayout(layout)
        header = QFrame(); header.setObjectName("header")
        top = box_layout("h", (22, 13, 22, 13), 12); header.setLayout(top)
        mark = label("L", "mark"); mark.setFixedSize(38, 38); mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        top.addWidget(mark)
        brand = box_layout(spacing=0); brand.addWidget(label("LumaSlice", "brand")); brand.addWidget(label("LCD 切片工作台", "muted"))
        top.addLayout(brand); top.addSpacing(12); top.addWidget(label("PNG WORKFLOW", "badge"))
        top.addStretch()
        self.import_btn = button("＋  导入模型", self.import_dialog, "primary"); top.addWidget(self.import_btn)
        self.open_btn = button("打开项目", self.open_dialog); top.addWidget(self.open_btn)
        self.save_btn = button("保存项目", self.save); top.addWidget(self.save_btn)
        layout.addWidget(header)
        self.content = QSplitter(Qt.Orientation.Horizontal)
        self.content.setChildrenCollapsible(False)
        self.content.addWidget(self.build_left())
        self.content.addWidget(self.build_center())
        self.content.addWidget(self.build_right())
        self.content.setStretchFactor(0, 0); self.content.setStretchFactor(1, 1); self.content.setStretchFactor(2, 0)
        self.content.setSizes([242, 860, 330])
        layout.addWidget(self.content, 1)
        self.progress = QProgressBar(); self.progress.setTextVisible(False); self.progress.setFixedHeight(4); self.progress.hide()
        layout.addWidget(self.progress)
        self.cancel_btn = button("取消任务", self.cancel_job, "small"); self.cancel_btn.hide()
        self.statusBar().addPermanentWidget(self.cancel_btn)
        self.statusBar().addPermanentWidget(label(f"v{__version__}  ·  本地运行", "muted"))

    def build_left(self):
        sidebar = QFrame(); sidebar.setObjectName("sidebar"); sidebar.setMinimumWidth(215); sidebar.setMaximumWidth(310)
        lay = box_layout(margins=(14, 18, 14, 14), spacing=12); sidebar.setLayout(lay)
        row = box_layout("h"); row.addWidget(label("场景对象", "title")); row.addStretch()
        row.addWidget(button("示例", self.add_demo, "small")); lay.addLayout(row)
        self.objects = QListWidget(); self.objects.setMinimumHeight(110); self.objects.setMaximumHeight(205)
        self.objects.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.objects.currentRowChanged.connect(self.select_model); self.objects.itemChanged.connect(self.toggle_model)
        lay.addWidget(self.objects, 1)
        row = box_layout("h", spacing=6)
        row.addWidget(button("居中", self.center_model, "small"))
        row.addWidget(button("复制", self.duplicate_model, "small"))
        row.addWidget(button("移除", self.remove_model, "small")); lay.addLayout(row)
        self.mesh_info = label("", "muted", True); lay.addWidget(self.mesh_info)
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        container = QWidget(); trans = box_layout(spacing=11); container.setLayout(trans); scroll.setWidget(container)
        trans.addWidget(label("对象变换", "title"))
        self.transforms = {}
        form = QFormLayout(); form.setSpacing(8); form.setContentsMargins(0, 0, 0, 0)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        for key, text, suffix, low, high, default in [
            ("x", "X 位置", " mm", -9999, 9999, 0), ("y", "Y 位置", " mm", -9999, 9999, 0),
            ("z", "Z 抬升", " mm", 0, 9999, 0), ("rx", "X 旋转", " °", -360, 360, 0),
            ("ry", "Y 旋转", " °", -360, 360, 0), ("rz", "Z 旋转", " °", -360, 360, 0),
            ("scale", "等比缩放", " %", .001, 100000, 100)]:
            spin = ParameterDoubleSpinBox(); spin.setRange(low, high); spin.setDecimals(3 if key == "scale" else 2)
            spin.setSuffix(suffix); spin.setValue(default); spin.setKeyboardTracking(False)
            spin.valueChanged.connect(lambda value, k=key: self.transform_changed(k, value))
            self.transforms[key] = spin; form.addRow(text, spin)
        trans.addLayout(form)
        trans.addWidget(label("旋转后自动落到平台；Z 为额外抬升量。", "muted", True))
        trans.addStretch(); lay.addWidget(scroll, 2)
        tip = label("01  导入并摆放模型\n02  设置屏幕与打印尺寸\n03  预览并导出 PNG", "muted")
        tip.setStyleSheet("line-height: 150%; padding-top: 10px; border-top: 1px solid #e9ecf1;")
        lay.addWidget(tip)
        return sidebar

    def build_center(self):
        center = QWidget(); lay = box_layout(margins=(16, 15, 16, 14), spacing=12); center.setLayout(lay)
        row = box_layout("h", spacing=0)
        group = QButtonGroup(self); group.setExclusive(True)
        self.tab_buttons = []
        for i, text in enumerate(("01  模型准备", "02  切片预览")):
            tab = button(text, lambda checked=False, ix=i: self.switch_tab(ix), "tab")
            tab.setCheckable(True); group.addButton(tab); self.tab_buttons.append(tab); row.addWidget(tab)
        self.tab_buttons[0].setChecked(True)
        row.addStretch(); row.addWidget(button("适应窗口", self.fit_current, "small"))
        lay.addLayout(row)
        self.pages = QStackedWidget()
        prepare = QWidget(); pl = box_layout(spacing=0); prepare.setLayout(pl)
        self.build_view = BuildView(); pl.addWidget(self.build_view, 1)
        views = box_layout("h", (0, 9, 0, 0), 6)
        for mode, text in (("iso", "等轴视图"), ("top", "俯视图"), ("front", "正视图")):
            views.addWidget(button(text, lambda checked=False, m=mode: self.build_view.reset_view(m), "small"))
        views.addStretch(); views.addWidget(label("单位：毫米", "muted")); pl.addLayout(views)
        self.pages.addWidget(prepare)
        preview_page = QWidget(); pr = box_layout(spacing=10); preview_page.setLayout(pr)
        tools = box_layout("h", spacing=6)
        self.tool_group = QButtonGroup(self); self.tool_group.setExclusive(True)
        self.tool_buttons = {}
        for key, text in (("hand", "平移"), ("paint", "画笔"), ("erase", "擦黑")):
            b = button(text, lambda checked=False, t=key: self.mask_view.set_tool(t), "small")
            b.setCheckable(True); self.tool_group.addButton(b); b.setChecked(key == "hand"); tools.addWidget(b)
            self.tool_buttons[key] = b
        tools.addStretch(); tools.addWidget(button("撤销笔迹", self.undo_stroke, "small"))
        tools.addWidget(button("保存此层", self.save_layer, "small")); pr.addLayout(tools)
        brush_options = box_layout("h", spacing=8)
        brush_options.addWidget(label("半径", "muted"))
        self.brush = ParameterSpinBox(); self.brush.setRange(0, 100); self.brush.setValue(1); self.brush.setSuffix(" px")
        self.brush.setFixedWidth(85); self.brush.valueChanged.connect(lambda v: setattr(self.mask_view, "radius", v)); brush_options.addWidget(self.brush)
        brush_options.addWidget(label("画笔灰度", "muted"))
        self.brush_gray = ParameterSpinBox(); self.brush_gray.setRange(0, 255); self.brush_gray.setValue(255)
        self.brush_gray.setFixedWidth(75); self.brush_gray.setKeyboardTracking(False)
        self.brush_gray.setToolTip("0 为黑色，255 为白色；画笔以设定灰度覆盖像素，擦黑工具始终为 0。")
        self.brush_gray.valueChanged.connect(self.brush_gray_changed); brush_options.addWidget(self.brush_gray)
        self.gray_swatch = QLabel(); self.gray_swatch.setFixedSize(22, 22); brush_options.addWidget(self.gray_swatch)
        brush_options.addWidget(label("0 黑 · 255 白", "muted")); brush_options.addStretch(); pr.addLayout(brush_options)
        self.mask_view = MaskView(); self.mask_view.strokeFinished.connect(self.add_stroke)
        self.brush_gray_changed(self.brush_gray.value())
        self.mask_view.pixelHovered.connect(self.pixel_hovered); pr.addWidget(self.mask_view, 1)
        self.pixel_label = label("滚轮放大可检查单个像素 · 半径 0 = 单像素 · 手绘仅作用于当前层", "muted")
        pr.addWidget(self.pixel_label)
        self.pages.addWidget(preview_page); lay.addWidget(self.pages, 1)
        layer_card, layer_lay = card("切片层")
        controls = box_layout("h", spacing=10)
        self.layer_spin = ParameterSpinBox(); self.layer_spin.setRange(1, 200); self.layer_spin.setPrefix("第 "); self.layer_spin.setSuffix(" 层")
        self.layer_spin.setFixedWidth(115); self.layer_spin.setKeyboardTracking(False)
        self.slider = ParameterSlider(Qt.Orientation.Horizontal); self.slider.setRange(1, 200)
        self.slider.valueChanged.connect(self.slider_changed); self.layer_spin.valueChanged.connect(self.slider.setValue)
        controls.addWidget(self.layer_spin); controls.addWidget(self.slider, 1)
        self.layer_label = label("", "muted"); controls.addWidget(self.layer_label)
        layer_lay.addLayout(controls)
        self.scene_message = label("", "muted", True); layer_lay.addWidget(self.scene_message)
        lay.addWidget(layer_card)
        return center

    def build_right(self):
        sidebar = QFrame(); sidebar.setObjectName("rightbar"); sidebar.setMinimumWidth(300); sidebar.setMaximumWidth(380)
        lay = box_layout(margins=(15, 18, 15, 14), spacing=12); sidebar.setLayout(lay)
        title = box_layout("h"); title.addWidget(label("打印与图像", "title")); title.addStretch(); title.addWidget(label("LCD / MSLA", "badge")); lay.addLayout(title)
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        content = QWidget(); panel = box_layout(spacing=13); content.setLayout(panel); scroll.setWidget(content)
        self.controls = {}
        c, l = card("屏幕分辨率")
        preset = ParameterComboBox(); preset.addItems(["自定义分辨率", "11520 × 5120 · 12K", "7680 × 4320 · 8K", "3840 × 2160 · 4K", "2560 × 1440"])
        preset.setCurrentIndex(1); preset.activated.connect(self.use_preset); l.addWidget(preset); self.preset = preset
        form = QFormLayout(); form.setContentsMargins(0, 0, 0, 0); form.setSpacing(8)
        for key, text in (("width_px", "宽度 X"), ("height_px", "高度 Y")):
            spin = ParameterSpinBox(); spin.setRange(1, 65536); spin.setSuffix(" px"); spin.setKeyboardTracking(False)
            spin.valueChanged.connect(self.settings_changed); self.controls[key] = spin; form.addRow(text, spin)
        self.pixel_controls = {}
        for axis in ("x", "y"):
            spin = PreciseSpinBox(); spin.setDecimals(6); spin.setRange(.000001, 10000000)
            spin.setSingleStep(.1); spin.setSuffix(" μm"); spin.setKeyboardTracking(False)
            spin.setToolTip("直接修改单个像素的物理尺寸；保持像素数量不变，自动更新对应方向的打印尺寸。")
            spin.valueChanged.connect(lambda value, a=axis: self.pixel_size_changed(a, value))
            self.pixel_controls[axis] = spin
            form.addRow("单像素 " + axis.upper(), spin)
        l.addLayout(form)
        l.addWidget(label("修改单像素尺寸 → 更新打印面积\n修改分辨率或打印面积 → 重算单像素尺寸", "muted", True))
        self.memory_label = label("", "muted"); l.addWidget(self.memory_label); panel.addWidget(c)
        c, l = card("打印范围")
        form = QFormLayout(); form.setContentsMargins(0, 0, 0, 0); form.setSpacing(8)
        for key, text, low, high, decimals in (("width_mm", "宽度 X", .001, 10000, 3), ("height_mm", "深度 Y", .001, 10000, 3),
                                               ("max_z_mm", "最大高度 Z", .001, 10000, 3), ("layer_mm", "层厚", .001, 10, 3)):
            spin = PreciseSpinBox() if key in ("width_mm", "height_mm") else ParameterDoubleSpinBox()
            spin.setRange(low, high); spin.setDecimals(9 if key in ("width_mm", "height_mm") else decimals); spin.setSuffix(" mm")
            spin.setSingleStep(.01 if key == "layer_mm" else 1); spin.setKeyboardTracking(False)
            spin.valueChanged.connect(self.settings_changed); self.controls[key] = spin; form.addRow(text, spin)
        l.addLayout(form); self.pitch_label = label("", "metric"); l.addWidget(self.pitch_label); panel.addWidget(c)
        c, l = card("图像与像素处理")
        form = QFormLayout(); form.setSpacing(8); form.setContentsMargins(0, 0, 0, 0)
        aa = ParameterComboBox(); aa.addItems(["关闭 · 纯黑白", "2× · 灰度边缘", "4× · 灰度边缘"])
        aa.currentIndexChanged.connect(self.settings_changed); self.controls["antialias"] = aa; form.addRow("抗锯齿", aa)
        edge = ParameterSpinBox(); edge.setRange(-20, 20); edge.setSuffix(" px"); edge.setKeyboardTracking(False)
        edge.setToolTip("正值扩张白色，负值收缩白色；采用方形邻域，X/Y 物理补偿量随像素尺寸变化。")
        edge.valueChanged.connect(self.settings_changed); self.controls["edge_px"] = edge; form.addRow("边缘补偿", edge)
        gamma = ParameterDoubleSpinBox(); gamma.setRange(.1, 5); gamma.setDecimals(2); gamma.setSingleStep(.05); gamma.setKeyboardTracking(False)
        gamma.valueChanged.connect(self.settings_changed); self.controls["gamma"] = gamma; form.addRow("灰度 Gamma", gamma)
        l.addLayout(form)
        row = box_layout("h", spacing=8)
        for key, text in (("mirror_x", "镜像 X"), ("mirror_y", "镜像 Y"), ("invert", "反相")):
            cb = QCheckBox(text); cb.toggled.connect(self.settings_changed); self.controls[key] = cb; row.addWidget(cb)
        l.addLayout(row)
        self.plugin_label = label("自定义处理：未加载", "muted", True); l.addWidget(self.plugin_label)
        row = box_layout("h", spacing=6); row.addWidget(button("加载处理插件…", self.load_plugin, "small")); row.addWidget(button("清除", self.clear_plugin, "small")); l.addLayout(row)
        panel.addWidget(c); panel.addStretch(); lay.addWidget(scroll, 1)
        self.summary = label("", "muted", True); lay.addWidget(self.summary)
        self.preview_btn = button("生成当前层预览", self.preview); lay.addWidget(self.preview_btn)
        self.export_btn = button("切片并导出 PNG  →", self.export_png, "primary"); self.export_btn.setMinimumHeight(28); lay.addWidget(self.export_btn)
        lay.addWidget(label("8-bit PNG · 白色曝光 / 黑色关闭\n导出尺寸始终为设定的原始像素数", "muted", True))
        return sidebar

    def sync_settings(self):
        self._updating = True
        for key, w in self.controls.items():
            value = getattr(self.settings, key)
            if isinstance(w, QComboBox): w.setCurrentIndex((1, 2, 4).index(value))
            elif isinstance(w, QCheckBox): w.setChecked(value)
            else: w.setValue(value)
        self._updating = False
        resolutions = [(0, 0), (11520, 5120), (7680, 4320), (3840, 2160), (2560, 1440)]
        resolution = (self.settings.width_px, self.settings.height_px)
        self.preset.setCurrentIndex(resolutions.index(resolution) if resolution in resolutions else 0)
        self.plugin_label.setText("自定义处理：" + (Path(self.settings.plugin_path).name if self.settings.plugin_path else "未加载"))
        self.refresh_scene()

    def settings_changed(self, *_):
        if self._updating:
            return
        for key, w in self.controls.items():
            if isinstance(w, QComboBox): value = (1, 2, 4)[w.currentIndex()]
            elif isinstance(w, QCheckBox): value = w.isChecked()
            else: value = w.value()
            setattr(self.settings, key, value)
        self.preset.blockSignals(True); self.preset.setCurrentIndex(0); self.preset.blockSignals(False)
        self.invalidate()

    def pixel_size_changed(self, axis, micrometers):
        if self._updating:
            return
        count_key, size_key = ("width_px", "width_mm") if axis == "x" else ("height_px", "height_mm")
        millimeters = micrometers * getattr(self.settings, count_key) / 1000.0
        setattr(self.settings, size_key, millimeters)
        control = self.controls[size_key]
        previous = control.blockSignals(True)
        control.setValue(millimeters)
        control.blockSignals(previous)
        self.invalidate()

    def use_preset(self, index):
        presets = {1: (11520, 5120), 2: (7680, 4320), 3: (3840, 2160), 4: (2560, 1440)}
        if index in presets:
            self.settings.width_px, self.settings.height_px = presets[index]
            self.sync_settings(); self.invalidate()

    def invalidate(self):
        self.dirty = True
        self.current_image = None; self.rendered_index = None
        self.mask_view.clear_image()
        self.refresh_scene()
        self.setWindowModified(True)
        if self.edits:
            self.statusBar().showMessage("参数已变更；手绘笔迹仍保留在原层号与像素坐标。")
        else:
            self.statusBar().showMessage("场景已更新 · 点击预览以重新生成图片")

    def refresh_scene(self):
        s = self.settings
        self.build_view.models = self.models; self.build_view.settings = s
        self.build_view.selected = self.objects.currentRow(); self.build_view.update()
        px, py = s.pixel_mm
        # Pixel pitch is derived from area/resolution and is also directly editable.
        # Updating either representation must not recursively change the other.
        for axis, pitch, count_key, size_key in (("x", px, "width_px", "width_mm"),
                                                ("y", py, "height_px", "height_mm")):
            spin = self.pixel_controls[axis]
            previous = spin.blockSignals(True)
            count = getattr(s, count_key)
            size_control = self.controls[size_key]
            spin.setRange(max(.000001, size_control.minimum() * 1000 / count),
                          size_control.maximum() * 1000 / count)
            spin.setValue(pitch * 1000)
            spin.blockSignals(previous)
        self.pitch_label.setText(f"像素 X {px * 1000:.3f} / Y {py * 1000:.3f} μm")
        self.memory_label.setText(f"{s.width_px * s.height_px / 1e6:.2f} MP  ·  灰度原图 {s.width_px * s.height_px / 1024**2:.1f} MiB / 层")
        try:
            count = layer_count(self.models, s)
            self.scene_message.setText(f"{sum(m.enabled for m in self.models)} 个启用对象  ·  共 {count:,} 层  ·  采样于每层中间高度")
            self.scene_message.setStyleSheet("color: #78869a;")
        except SliceError as exc:
            count = 1
            self.scene_message.setText(str(exc)); self.scene_message.setStyleSheet("color: #cc6339;")
        self.slider.blockSignals(True); self.slider.setMaximum(count); self.slider.blockSignals(False)
        self.layer_spin.blockSignals(True); self.layer_spin.setMaximum(count); self.layer_spin.setValue(self.slider.value()); self.layer_spin.blockSignals(False)
        self.update_layer_label()
        self.summary.setText(f"{s.width_px:,} × {s.height_px:,} px  /  {count:,} 层\n{len(self.edits)} 层包含手绘笔迹" if self.edits else
                             f"{s.width_px:,} × {s.height_px:,} px  /  {count:,} 层\n{('抗锯齿关闭' if s.antialias == 1 else str(s.antialias) + '× 抗锯齿')} · 像素补偿 {s.edge_px:+d} px")

    def refresh_models(self, selected=None):
        row = self.objects.currentRow() if selected is None else selected
        self.objects.blockSignals(True); self.objects.clear()
        for model in self.models:
            item = QListWidgetItem(model.name)
            item.setToolTip(model.source or "内置校准模型")
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if model.enabled else Qt.CheckState.Unchecked)
            self.objects.addItem(item)
        if self.models: self.objects.setCurrentRow(max(0, min(row, len(self.models) - 1)))
        self.objects.blockSignals(False); self.select_model(self.objects.currentRow())

    def selected_model(self):
        row = self.objects.currentRow()
        return self.models[row] if 0 <= row < len(self.models) else None

    def select_model(self, row):
        model = self.selected_model()
        self._updating = True
        for key, spin in self.transforms.items():
            spin.setEnabled(model is not None)
            if model: spin.setValue(getattr(model, key))
        self._updating = False
        if model:
            size = model.bounds[1] - model.bounds[0]
            watertight = model.watertight
            self.mesh_info.setText(f"{size[0]:.2f} × {size[1]:.2f} × {size[2]:.2f} mm\n{len(model.faces):,} 三角面 · " + ("闭合网格" if watertight else "网格未闭合，请先检查"))
        else:
            self.mesh_info.setText("未选中对象")
        self.build_view.selected = row; self.build_view.update()

    def transform_changed(self, key, value):
        if self._updating: return
        model = self.selected_model()
        if model:
            setattr(model, key, value); self.invalidate(); self.select_model(self.objects.currentRow())

    def toggle_model(self, item):
        row = self.objects.row(item)
        self.models[row].enabled = item.checkState() == Qt.CheckState.Checked
        self.invalidate()

    def center_model(self):
        model = self.selected_model()
        if model:
            b = model.bounds; center = b[:, :2].mean(axis=0)
            model.x += self.settings.width_mm / 2 - center[0]
            model.y += self.settings.height_mm / 2 - center[1]
            self.invalidate(); self.select_model(self.objects.currentRow())

    def duplicate_model(self):
        model = self.selected_model()
        if model:
            clone = replace(model, name=model.name + " 副本", x=model.x + 5, y=model.y + 5)
            self.models.append(clone); self.refresh_models(len(self.models) - 1); self.invalidate()

    def remove_model(self):
        row = self.objects.currentRow()
        if 0 <= row < len(self.models):
            self.models.pop(row); self.refresh_models(row); self.invalidate()

    def add_demo(self):
        self.models.append(demo_model(self.settings)); self.refresh_models(len(self.models) - 1); self.invalidate()

    def slider_changed(self, value):
        self.layer_spin.blockSignals(True); self.layer_spin.setValue(value); self.layer_spin.blockSignals(False)
        self.update_layer_label()
        self.current_image = None; self.rendered_index = None
        self.mask_view.clear_image()
        if self.pages.currentIndex() == 1:
            self.debounce.start()

    def update_layer_label(self):
        self.layer_label.setText(f"/ {self.slider.maximum():,}    Z ≤ {self.slider.value() * self.settings.layer_mm:.3f} mm")

    def switch_tab(self, index):
        if self.worker: return
        self.pages.setCurrentIndex(index); self.tab_buttons[index].setChecked(True)
        if index == 1 and self.current_image is None and self.models:
            self.preview()

    def fit_current(self):
        if self.pages.currentIndex() == 0: self.build_view.reset_view()
        else: self.mask_view.fit_image()

    def snapshot(self):
        return [replace(m) for m in self.models], replace(self.settings), deepcopy(self.edits)

    def start_job(self, task, done, message):
        if self.worker: return
        self.debounce.stop()
        self.content.setEnabled(False)
        self.menuBar().setEnabled(False)
        for b in (self.import_btn, self.open_btn, self.save_btn): b.setEnabled(False)
        self.cancel_btn.show(); self.cancel_btn.setEnabled(True)
        self.progress.setRange(0, 0); self.progress.show()
        self.statusBar().showMessage(message)
        worker = Job(task, self); self.worker = worker
        worker.result.connect(done); worker.failed.connect(self.job_failed)
        worker.progress.connect(self.job_progress); worker.finished.connect(self.job_finished)
        worker.start()

    def job_finished(self):
        worker = self.worker; self.worker = None
        if worker: worker.deleteLater()
        self.content.setEnabled(True); self.menuBar().setEnabled(True)
        for b in (self.import_btn, self.open_btn, self.save_btn): b.setEnabled(True)
        self.cancel_btn.hide(); self.progress.hide()
        if self._closing: self.close()

    def job_progress(self, value, message):
        self.progress.setRange(0, 1000); self.progress.setValue(value)
        self.statusBar().showMessage(message)

    def job_failed(self, message):
        self.statusBar().showMessage(message)
        if not message.startswith("已取消"):
            QMessageBox.warning(self, "任务未完成", message)

    def cancel_job(self):
        if self.worker:
            self.worker.cancel.set(); self.cancel_btn.setEnabled(False)
            self.statusBar().showMessage("正在取消，将在当前操作完成后停止…")

    def preview(self):
        if self.worker: return
        models, settings, edits = self.snapshot(); index = self.slider.value() - 1
        def task(job): return Slicer(models, settings, edits, job.cancel).render(index)
        def done(result):
            image, context = result
            self.current_image = image; self.rendered_index = index
            self.pages.setCurrentIndex(1); self.tab_buttons[1].setChecked(True)
            self.mask_view.set_image(image)
            self.statusBar().showMessage(f"第 {index + 1} 层已生成 · 采样 Z = {context.sample_z_mm:.5f} mm · {image.width} × {image.height} px")
        self.start_job(task, done, "正在计算截面与像素图片…")

    def brush_gray_changed(self, value):
        self.mask_view.value = value
        self.gray_swatch.setStyleSheet(f"background: rgb({value}, {value}, {value}); border: 1px solid #bbc5d3; border-radius: 4px;")

    def add_stroke(self, value):
        if self.current_image is None or self.rendered_index != self.slider.value() - 1: return
        stroke = Stroke(**value)
        self.edits.setdefault(self.rendered_index, []).append(stroke)
        apply_strokes(self.current_image, [stroke]); self.mask_view.set_image(self.current_image)
        self.dirty = True; self.refresh_scene()
        self.statusBar().showMessage("像素笔迹已记录；完整导出与项目保存均包含本次修改。")

    def undo_stroke(self):
        index = self.slider.value() - 1
        if self.edits.get(index):
            self.edits[index].pop()
            if not self.edits[index]: self.edits.pop(index)
            self.dirty = True; self.refresh_scene(); self.preview()

    def pixel_hovered(self, x, y):
        if self.current_image is not None:
            value = self.current_image.getpixel((x, y))
            self.pixel_label.setText(f"X {x:,}  /  Y {y:,} px    ·    灰度 {value}    ·    缩放 {self.mask_view.transform().m11() * 100:.1f}%")

    def save_layer(self):
        if self.current_image is None:
            QMessageBox.information(self, "尚无切片", "请先生成当前层预览。"); return
        path, _ = QFileDialog.getSaveFileName(self, "保存当前层 PNG", f"layer_{self.rendered_index + 1:06d}.png", "PNG (*.png)")
        if path:
            try:
                self.current_image.save(path, format="PNG")
                self.statusBar().showMessage(f"当前层已保存：{path}")
            except Exception as exc: QMessageBox.warning(self, "保存失败", str(exc))

    def export_png(self):
        if self.worker: return
        try:
            layer_count(self.models, self.settings)
        except SliceError as exc:
            QMessageBox.warning(self, "无法切片", str(exc)); return
        parent = QFileDialog.getExistingDirectory(self, "选择 PNG 导出位置（将创建独立任务文件夹）")
        if not parent: return
        dest = Path(parent) / ("LumaSlice_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f"))
        models, settings, edits = self.snapshot()
        def task(job):
            slicer = Slicer(models, settings, edits, job.cancel)
            return slicer.export(dest, lambda i, n: job.progress.emit(int(i / n * 1000), f"正在导出 {i:,} / {n:,} 层…"))
        def done(result):
            self.statusBar().showMessage(f"PNG 图片已导出到：{result}")
            dialog = QMessageBox(self); dialog.setWindowTitle("导出完成")
            dialog.setText(f"PNG 图片序列已导出。\n\n{result}")
            open_button = dialog.addButton("打开文件夹", QMessageBox.ButtonRole.ActionRole)
            dialog.addButton("完成", QMessageBox.ButtonRole.AcceptRole)
            dialog.exec()
            if dialog.clickedButton() == open_button: QDesktopServices.openUrl(QUrl.fromLocalFile(str(result)))
        self.start_job(task, done, "正在准备导出任务…")

    def import_dialog(self):
        if self.worker: return
        paths, _ = QFileDialog.getOpenFileNames(self, "导入模型（尺寸单位为毫米）", "", "网格文件 (*.stl *.obj *.ply);;所有文件 (*)")
        if paths: self.import_paths(paths)

    def import_paths(self, paths):
        settings = replace(self.settings)
        def task(job):
            result = []
            for p in paths:
                if job.cancel.is_set(): raise Cancelled("已取消模型导入。")
                result.append(load_model(p, settings))
            return result
        def done(models):
            self.models.extend(models); self.refresh_models(len(self.models) - 1); self.invalidate()
            self.statusBar().showMessage(f"已导入 {len(models)} 个模型 · 按毫米读取")
        self.start_job(task, done, "正在读取与检查模型…")

    def load_plugin(self):
        path, _ = QFileDialog.getOpenFileName(self, "加载你信任的像素处理插件", "", "Python 处理插件 (*.py)")
        if path:
            self.settings.plugin_path = path; self.sync_settings(); self.invalidate()

    def clear_plugin(self):
        self.settings.plugin_path = ""; self.sync_settings(); self.invalidate()

    def confirm_discard(self):
        if not self.dirty: return True
        answer = QMessageBox.question(self, "保存项目", "当前项目有未保存的修改。", QMessageBox.StandardButton.Save |
                                      QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel)
        if answer == QMessageBox.StandardButton.Save: return self.save()
        return answer == QMessageBox.StandardButton.Discard

    def new_project(self):
        if self.worker or not self.confirm_discard(): return
        self.debounce.stop(); self.models = []; self.edits = {}; self.project_path = None
        self.settings = Settings(); self.refresh_models(); self.sync_settings(); self.setWindowModified(False)
        self.current_image = None; self.rendered_index = None; self.mask_view.clear_image(); self.dirty = False
        self.pages.setCurrentIndex(0); self.tab_buttons[0].setChecked(True)
        self.statusBar().showMessage("新项目 · 导入一个 STL 模型以开始")

    def open_dialog(self):
        if self.worker or not self.confirm_discard(): return
        path, _ = QFileDialog.getOpenFileName(self, "打开 LumaSlice 项目", "", "LumaSlice 项目 (*.lcdproj)")
        if path: self.open_project(path)

    def open_project(self, path):
        try:
            models, settings, edits = load_project(path)
            self.debounce.stop(); self.models, self.settings, self.edits = models, settings, edits
            self.project_path = path; self.current_image = None; self.rendered_index = None; self.mask_view.clear_image()
            self.refresh_models(); self.sync_settings(); self.dirty = False; self.setWindowModified(False)
            self.pages.setCurrentIndex(0); self.tab_buttons[0].setChecked(True)
            self.statusBar().showMessage(f"项目已打开：{path}")
        except Exception as exc: QMessageBox.warning(self, "无法打开项目", str(exc))

    def save(self, save_as=False):
        if self.worker: return False
        path = self.project_path
        if save_as or not path:
            path, _ = QFileDialog.getSaveFileName(self, "保存项目（包含模型、设置与像素笔迹）", path or "未命名.lcdproj", "LumaSlice 项目 (*.lcdproj)")
        if not path: return False
        if not path.lower().endswith(".lcdproj"): path += ".lcdproj"
        try:
            save_project(path, self.models, self.settings, self.edits)
            self.project_path = path; self.dirty = False; self.setWindowModified(False)
            self.statusBar().showMessage(f"项目已保存：{path}")
            return True
        except Exception as exc:
            QMessageBox.warning(self, "保存失败", str(exc)); return False

    def dragEnterEvent(self, event):
        if not self.worker and event.mimeData().hasUrls(): event.acceptProposedAction()

    def dropEvent(self, event):
        if self.worker: return
        paths = [u.toLocalFile() for u in event.mimeData().urls()]
        if len(paths) == 1 and paths[0].lower().endswith(".lcdproj"):
            if self.confirm_discard(): self.open_project(paths[0])
        else:
            meshes = [p for p in paths if Path(p).suffix.lower() in (".stl", ".obj", ".ply")]
            if meshes: self.import_paths(meshes)
        event.acceptProposedAction()

    def show_help(self):
        QMessageBox.information(self, "使用说明", "1. 导入 STL / OBJ / PLY，模型按毫米读取。\n"
            "2. 设置分辨率、打印宽深和层厚；用居中、旋转、缩放调整模型。\n"
            "单像素 X/Y 尺寸可直接输入（μm），修改后保持分辨率并更新打印面积。\n"
            "3. 点击生成预览，滚轮放大检查像素；画笔可设置 0–255 灰度，擦黑固定为 0，仅修改当前层。\n"
            "参数输入框、下拉框与层号均不会因滚轮改变；可输入、按键或点击箭头调整。\n"
            "4. 切片并导出，生成原尺寸 8-bit PNG 与 job.json。\n\n"
            "图片左上角为 (0,0)，世界坐标原点在平台左下。\n"
            "边缘补偿为方形像素邻域；正值扩大白色，负值收缩。\n"
            "插件 process(image, context) 接收二维 uint8 数组。\n"
            "处理顺序：抗锯齿 → 边缘补偿 → Gamma → 插件 → 镜像/反相 → 手绘。\n"
            "参数变化后，手绘保留原层号与像素坐标；建议先另存项目。\n\n"
            "当前版本不生成支撑、排液孔和打印机控制文件。\n"
            "可先在其他建模工具中处理这些结构，再导入本软件。")

    def closeEvent(self, event):
        if self.worker:
            answer = QMessageBox.question(self, "任务运行中", "取消当前任务并关闭软件？")
            if answer == QMessageBox.StandardButton.Yes:
                self._closing = True; self.cancel_job()
            event.ignore(); return
        if not self.confirm_discard(): event.ignore(); return
        self.debounce.stop(); event.accept()


def main():
    parser = argparse.ArgumentParser(description="LumaSlice LCD PNG slicer")
    parser.add_argument("project", nargs="?")
    parser.add_argument("--empty", action="store_true")
    parser.add_argument("--screenshot", help=argparse.SUPPRESS)
    parser.add_argument("--verify-build", help=argparse.SUPPRESS)
    args = parser.parse_args()
    app = QApplication(sys.argv[:1]); app.setApplicationName("LumaSlice"); app.setOrganizationName("LumaSlice")
    # Offscreen renderers may not enumerate the Windows font registry. Load the
    # fonts already installed on this Windows system; do not redistribute them.
    if sys.platform == "win32":
        for name in ("msyh.ttc", "msyhbd.ttc", "segoeui.ttf"):
            font_path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / name
            if font_path.is_file(): QFontDatabase.addApplicationFont(str(font_path))
    app.setFont(QFont("Microsoft YaHei UI", 9)); app.setStyle("Fusion"); app.setStyleSheet(STYLE)
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    icon = base / "assets" / "lumaslice.ico"
    if icon.is_file(): app.setWindowIcon(QIcon(str(icon)))
    window = MainWindow(empty=args.empty)
    if args.project: window.open_project(args.project)
    window.show()
    if args.verify_build:
        output = Path(args.verify_build); output.mkdir(parents=True, exist_ok=True)
        window.settings.layer_mm = 5
        window.settings.antialias = 2
        window.settings.plugin_path = str(Path(sys.executable).resolve().parent / "plugins" / "identity.py") if getattr(sys, "frozen", False) else str(base / "plugins" / "identity.py")
        window.sync_settings()
        window.pixel_controls["x"].setValue(20)
        window.pixel_controls["y"].setValue(21)
        def verify():
            if window.worker is not None:
                QTimer.singleShot(50, verify); return
            try:
                if window.current_image is None: raise RuntimeError("GUI preview did not produce an image")
                window.brush_gray.setValue(128)
                window.add_stroke({"points": [[20, 25]], "radius": 0, "value": window.mask_view.value})
                models, settings, edits = window.snapshot()
                dest = Slicer(models, settings, edits).export(output / "png")
                from PIL import Image
                import numpy as np
                with Image.open(dest / "layer_000001.png") as image:
                    assert image.size == (11520, 5120) and image.mode == "L"
                    assert image.getpixel((20, 25)) == 128
                    np.testing.assert_array_equal(image, window.current_image)
                save_project(output / "roundtrip.lcdproj", models, settings, edits)
                window.open_project(output / "roundtrip.lcdproj")
                assert window.pixel_controls["x"].value() == 20
                assert window.pixel_controls["y"].value() == 21
                window.pages.setCurrentIndex(1); window.tab_buttons[1].setChecked(True)
                image, _ = Slicer(window.models, window.settings, window.edits).render(0)
                window.mask_view.set_image(image, fit=True)
                window.grab().save(str(output / "preview.png"))
                report = {"ok": True, "version": __version__, "frozen": bool(getattr(sys, "frozen", False)), "resolution": [11520, 5120],
                          "pixel_pitch_um": [20, 21], "build_size_mm": [window.settings.width_mm, window.settings.height_mm],
                          "layers": 2, "plugin": "identity", "manual_pixel": [20, 25, image.getpixel((20, 25))],
                          "brush_grayscale": True,
                          "preview_equals_export": True, "project_roundtrip": True}
            except Exception:
                report = {"ok": False, "error": traceback.format_exc()}
            (output / "verification.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
            window.dirty = False; app.quit()
        QTimer.singleShot(200, window.preview)
        QTimer.singleShot(300, verify)
    elif args.screenshot:
        def capture():
            window.grab().save(args.screenshot)
            app.quit()
        QTimer.singleShot(800, capture)
    sys.exit(app.exec())
