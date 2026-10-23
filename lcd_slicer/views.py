from __future__ import annotations

import math
import numpy as np
from PySide6.QtCore import Qt, QPointF, QRectF, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygonF, QImage, QPixmap
from PySide6.QtWidgets import QWidget, QGraphicsView, QGraphicsScene, QGraphicsPathItem


class BuildView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(360, 350)
        self.models = []
        self.settings = None
        self.selected = 0
        self.yaw, self.tilt, self.zoom = -36.0, 58.0, 1.0
        self.pan = np.array([0.0, 0.0])
        self.last = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def reset_view(self, mode="iso"):
        self.yaw, self.tilt = (-36, 58) if mode == "iso" else ((0, 0) if mode == "top" else (0, 88))
        self.zoom = 1.0
        self.pan[:] = 0
        self.update()

    def project(self, points):
        p = np.asarray(points, dtype=float).copy()
        p -= [self.settings.width_mm / 2, self.settings.height_mm / 2, 0]
        yaw, tilt = np.radians([self.yaw, self.tilt])
        x = math.cos(yaw) * p[:, 0] - math.sin(yaw) * p[:, 1]
        y = math.sin(yaw) * p[:, 0] + math.cos(yaw) * p[:, 1]
        z = p[:, 2]
        scale = min(self.width() / (self.settings.width_mm * 1.35),
                    self.height() / (self.settings.height_mm + self.settings.width_mm * .48)) * self.zoom
        result = np.column_stack((x, y * math.cos(tilt) - z * math.sin(tilt))) * scale
        result += [self.width() / 2 + self.pan[0], self.height() * .57 + self.pan[1]]
        depth = y * math.sin(tilt) + z * math.cos(tilt)
        return result, depth

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#edf0f4"))
        if self.settings is None:
            return
        s = self.settings
        bed = np.array([[0, 0, 0], [s.width_mm, 0, 0], [s.width_mm, s.height_mm, 0], [0, s.height_mm, 0]])
        points, _ = self.project(bed)
        outline = QPolygonF([QPointF(*p) for p in points])
        shadow = QPolygonF([QPointF(p[0], p[1] + 9) for p in points])
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#d5dce5")); painter.drawPolygon(shadow)
        painter.setBrush(QColor("#fbfcfe")); painter.setPen(QPen(QColor("#b9c4d1"), 1))
        painter.drawPolygon(outline)
        step = 10 if max(s.width_mm, s.height_mm) < 600 else 50
        painter.setPen(QPen(QColor("#e0e5ed"), .8))
        for x in np.arange(step, s.width_mm, step)[:120]:
            p, _ = self.project([[x, 0, 0], [x, s.height_mm, 0]])
            painter.drawLine(QPointF(*p[0]), QPointF(*p[1]))
        for y in np.arange(step, s.height_mm, step)[:120]:
            p, _ = self.project([[0, y, 0], [s.width_mm, y, 0]])
            painter.drawLine(QPointF(*p[0]), QPointF(*p[1]))
        faces_to_draw = []
        yaw, tilt = np.radians([self.yaw, self.tilt])
        light = np.array([-.3, -.5, .8])
        for i, model in enumerate(self.models):
            if not model.enabled:
                continue
            vertices = model.world_vertices()
            stride = max(1, math.ceil(len(model.faces) / 24000))
            faces = model.faces[::stride]
            points, depths = self.project(vertices)
            tri = vertices[faces]
            normals = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
            normals /= np.maximum(np.linalg.norm(normals, axis=1)[:, None], 1e-10)
            shades = .66 + .34 * np.clip(normals @ light, -.5, 1)
            base = np.array([248, 136, 58]) if i == self.selected else np.array([112, 147, 175])
            for face, shade, depth in zip(faces, shades, depths[faces].mean(1)):
                color = np.clip(base * shade, 0, 255).astype(int)
                faces_to_draw.append((depth, points[face], QColor(*map(int, color))))
        for _, pts, color in sorted(faces_to_draw, key=lambda f: f[0]):
            painter.setBrush(color)
            painter.setPen(QPen(color, .65))
            painter.drawPolygon(QPolygonF([QPointF(*p) for p in pts]))
        origin, _ = self.project([[0, 0, 0], [min(20, s.width_mm), 0, 0], [0, min(20, s.height_mm), 0], [0, 0, 20]])
        for j, color, label in ((1, "#dd665a", "X"), (2, "#4baf8c", "Y"), (3, "#648fe1", "Z")):
            painter.setPen(QPen(QColor(color), 2))
            painter.drawLine(QPointF(*origin[0]), QPointF(*origin[j]))
            painter.drawText(QPointF(*(origin[j] + [4, -4])), label)
        painter.setPen(QColor("#8b96a5"))
        painter.drawText(QRectF(22, 20, self.width() - 44, 24), Qt.AlignmentFlag.AlignLeft,
                         "BUILD PLATE  /  打印平台")
        painter.drawText(QRectF(22, self.height() - 36, self.width() - 44, 20), Qt.AlignmentFlag.AlignLeft,
                         "左键旋转 · 右键平移 · 滚轮缩放")
        painter.drawText(QRectF(22, self.height() - 36, self.width() - 44, 20), Qt.AlignmentFlag.AlignRight,
                         f"{s.width_mm:g} × {s.height_mm:g} mm")
        if not self.models:
            painter.setPen(QColor("#66758a"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "将 STL / OBJ / PLY 拖入窗口\n或点击「导入模型」")

    def mousePressEvent(self, event):
        self.last = event.position()
        self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event):
        if self.last is None:
            return
        delta = event.position() - self.last
        self.last = event.position()
        if event.buttons() & Qt.MouseButton.RightButton or event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            self.pan += [delta.x(), delta.y()]
        else:
            self.yaw += delta.x() * .45
            self.tilt = min(89, max(0, self.tilt + delta.y() * .4))
        self.update()

    def mouseReleaseEvent(self, event):
        self.last = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def wheelEvent(self, event):
        self.zoom = min(8, max(.25, self.zoom * (1.12 if event.angleDelta().y() > 0 else 1 / 1.12)))
        self.update()


class MaskView(QGraphicsView):
    strokeFinished = Signal(object)
    pixelHovered = Signal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setBackgroundBrush(QColor("#202735"))
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setMouseTracking(True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.tool = "hand"
        self.radius = 1
        self.value = 255
        self.stroke_value = 255
        self.image_size = None
        self.path_item = None
        self.stroke_points = []
        self.pixmap_item = None
        self._first = True

    def set_image(self, image, fit=False):
        raw = image.tobytes()
        qimage = QImage(raw, image.width, image.height, image.width, QImage.Format.Format_Grayscale8).copy()
        pixmap = QPixmap.fromImage(qimage)
        if self.pixmap_item is None:
            self.pixmap_item = self.scene().addPixmap(pixmap)
        else:
            self.pixmap_item.setPixmap(pixmap)
        self.scene().setSceneRect(0, 0, image.width, image.height)
        self.image_size = image.size
        if fit or self._first:
            self.fit_image()
            self._first = False

    def clear_image(self):
        self.scene().clear()
        self.pixmap_item = None
        self.path_item = None
        self.image_size = None
        self._first = True

    def fit_image(self):
        if self.image_size:
            self.fitInView(self.sceneRect().adjusted(-20, -20, 20, 20), Qt.AspectRatioMode.KeepAspectRatio)

    def set_tool(self, tool):
        self.tool = tool
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag if tool == "hand" else QGraphicsView.DragMode.NoDrag)
        self.setCursor(Qt.CursorShape.OpenHandCursor if tool == "hand" else Qt.CursorShape.CrossCursor)

    def wheelEvent(self, event):
        scale = self.transform().m11()
        factor = 1.25 if event.angleDelta().y() > 0 else .8
        if .005 <= scale * factor <= 64:
            self.scale(factor, factor)

    def drawForeground(self, painter, rect):
        if self.image_size is None or self.transform().m11() < 9:
            return
        visible = rect.intersected(self.sceneRect())
        painter.setPen(QPen(QColor(120, 145, 180, 80), 0))
        for x in range(max(0, math.floor(visible.left())), min(self.image_size[0], math.ceil(visible.right())) + 1):
            painter.drawLine(QPointF(x, visible.top()), QPointF(x, visible.bottom()))
        for y in range(max(0, math.floor(visible.top())), min(self.image_size[1], math.ceil(visible.bottom())) + 1):
            painter.drawLine(QPointF(visible.left(), y), QPointF(visible.right(), y))

    def mousePressEvent(self, event):
        if self.tool != "hand" and self.image_size and event.button() == Qt.MouseButton.LeftButton:
            p = self.mapToScene(event.position().toPoint())
            if not self.sceneRect().contains(p):
                return
            self.stroke_points = [[int(p.x()), int(p.y())]]
            self.stroke_value = min(255, max(0, int(self.value))) if self.tool == "paint" else 0
            path = QPainterPath(QPointF(int(p.x()) + .5, int(p.y()) + .5))
            path.lineTo(QPointF(int(p.x()) + .501, int(p.y()) + .501))
            self.path_item = QGraphicsPathItem(path)
            gray = self.stroke_value
            pen = QPen(QColor(gray, gray, gray), 2 * self.radius + 1)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap); pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            self.path_item.setPen(pen)
            self.scene().addItem(self.path_item)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        p = self.mapToScene(event.position().toPoint())
        if self.image_size and self.sceneRect().contains(p):
            self.pixelHovered.emit(int(p.x()), int(p.y()))
        if self.path_item:
            # Clipping keeps accidentally long drags out of the saved project.
            x = min(self.image_size[0] - 1, max(0, int(p.x())))
            y = min(self.image_size[1] - 1, max(0, int(p.y())))
            if self.stroke_points[-1] != [x, y]:
                self.stroke_points.append([x, y])
                path = self.path_item.path()
                path.lineTo(x + .5, y + .5)
                self.path_item.setPath(path)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.path_item:
            self.scene().removeItem(self.path_item)
            self.path_item = None
            self.strokeFinished.emit({"points": self.stroke_points, "radius": self.radius,
                                      "value": self.stroke_value})
            self.stroke_points = []
            event.accept()
            return
        super().mouseReleaseEvent(event)
