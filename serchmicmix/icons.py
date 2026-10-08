"""Iconos vectoriales dibujados con QPainter.

Se dibujan a mano en lugar de usar emoji o ficheros de imagen porque asi:

* se ven igual en cualquier PC, idioma y escala de pantalla (DPI),
* no dependen de que exista una fuente de emoji concreta,
* heredan el color del tema.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

from . import theme


def _canvas(size: int, dpr: int = 2):
    pm = QPixmap(int(size * dpr), int(size * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    return pm, p


def _pen(color: str, size: int, width: float = 0.085) -> QPen:
    pen = QPen(QColor(color), max(1.0, size * width))
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    return pen


# --------------------------------------------------------------------------
def mic_pixmap(size: int = 18, color: str = theme.TEXT) -> QPixmap:
    pm, p = _canvas(size)
    s = size
    p.setPen(_pen(color, s, 0.085))
    p.setBrush(Qt.NoBrush)
    w = s * 0.30
    p.drawRoundedRect(QRectF((s - w) / 2, s * 0.07, w, s * 0.50), w / 2, w / 2)
    p.drawArc(QRectF(s * 0.20, s * 0.28, s * 0.60, s * 0.44), 180 * 16, 180 * 16)
    p.drawLine(QPointF(s / 2, s * 0.72), QPointF(s / 2, s * 0.90))
    p.drawLine(QPointF(s * 0.33, s * 0.90), QPointF(s * 0.67, s * 0.90))
    p.end()
    return pm


def speaker_pixmap(size: int = 18, color: str = theme.TEXT, muted: bool = False) -> QPixmap:
    pm, p = _canvas(size)
    s = size
    body = QPainterPath()
    body.moveTo(s * 0.10, s * 0.36)
    body.lineTo(s * 0.28, s * 0.36)
    body.lineTo(s * 0.48, s * 0.16)
    body.lineTo(s * 0.48, s * 0.84)
    body.lineTo(s * 0.28, s * 0.64)
    body.lineTo(s * 0.10, s * 0.64)
    body.closeSubpath()
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(color))
    p.drawPath(body)

    p.setBrush(Qt.NoBrush)
    p.setPen(_pen(color, s, 0.085))
    if muted:
        p.drawLine(QPointF(s * 0.60, s * 0.36), QPointF(s * 0.88, s * 0.64))
        p.drawLine(QPointF(s * 0.88, s * 0.36), QPointF(s * 0.60, s * 0.64))
    else:
        p.drawArc(QRectF(s * 0.42, s * 0.30, s * 0.34, s * 0.40), -60 * 16, 120 * 16)
        p.drawArc(QRectF(s * 0.42, s * 0.18, s * 0.55, s * 0.64), -55 * 16, 110 * 16)
    p.end()
    return pm


def music_pixmap(size: int = 18, color: str = theme.TEXT) -> QPixmap:
    pm, p = _canvas(size)
    s = size
    p.setPen(_pen(color, s, 0.085))
    p.setBrush(QColor(color))
    r = s * 0.13
    p.drawEllipse(QRectF(s * 0.14, s * 0.62, r * 2, r * 1.7))
    p.drawEllipse(QRectF(s * 0.56, s * 0.50, r * 2, r * 1.7))
    p.setBrush(Qt.NoBrush)
    p.drawLine(QPointF(s * 0.14 + r * 2, s * 0.70), QPointF(s * 0.14 + r * 2, s * 0.20))
    p.drawLine(QPointF(s * 0.56 + r * 2, s * 0.58), QPointF(s * 0.56 + r * 2, s * 0.14))
    p.drawLine(QPointF(s * 0.14 + r * 2, s * 0.20), QPointF(s * 0.56 + r * 2, s * 0.14))
    p.end()
    return pm


def sliders_pixmap(size: int = 18, color: str = theme.TEXT) -> QPixmap:
    pm, p = _canvas(size)
    s = size
    p.setPen(_pen(color, s, 0.075))
    rows = ((0.24, 0.36), (0.50, 0.68), (0.76, 0.46))
    for y, kx in rows:
        p.drawLine(QPointF(s * 0.14, s * y), QPointF(s * 0.86, s * y))
        p.setBrush(QColor(color))
        p.drawEllipse(QPointF(s * kx, s * y), s * 0.10, s * 0.10)
        p.setBrush(Qt.NoBrush)
    p.end()
    return pm


def stop_pixmap(size: int = 18, color: str = theme.TEXT) -> QPixmap:
    pm, p = _canvas(size)
    s = size
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(color))
    path = QPainterPath()
    path.addRoundedRect(QRectF(s * 0.18, s * 0.18, s * 0.64, s * 0.64), s * 0.16, s * 0.16)
    p.drawPath(path)
    p.end()
    return pm


def plug_pixmap(size: int = 18, color: str = theme.TEXT) -> QPixmap:
    pm, p = _canvas(size)
    s = size
    p.setPen(_pen(color, s, 0.085))
    p.setBrush(Qt.NoBrush)
    path = QPainterPath()
    path.moveTo(s * 0.60, s * 0.14)
    path.lineTo(s * 0.86, s * 0.40)
    path.lineTo(s * 0.62, s * 0.64)
    path.lineTo(s * 0.50, s * 0.52)
    path.lineTo(s * 0.38, s * 0.64)
    path.lineTo(s * 0.36, s * 0.86)
    path.lineTo(s * 0.14, s * 0.64)
    p.drawPath(path)
    p.drawLine(QPointF(s * 0.60, s * 0.14), QPointF(s * 0.72, s * 0.02))
    p.end()
    return pm


def refresh_pixmap(size: int = 18, color: str = theme.TEXT) -> QPixmap:
    pm, p = _canvas(size)
    s = size
    p.setPen(_pen(color, s, 0.085))
    p.setBrush(Qt.NoBrush)
    p.drawArc(QRectF(s * 0.16, s * 0.16, s * 0.68, s * 0.68), 40 * 16, 280 * 16)
    head = QPainterPath()
    head.moveTo(s * 0.86, s * 0.18)
    head.lineTo(s * 0.90, s * 0.46)
    head.lineTo(s * 0.62, s * 0.38)
    head.closeSubpath()
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(color))
    p.drawPath(head)
    p.end()
    return pm


def headphones_pixmap(size: int = 18, color: str = theme.TEXT) -> QPixmap:
    pm, p = _canvas(size)
    s = size
    p.setPen(_pen(color, s, 0.09))
    p.setBrush(Qt.NoBrush)
    p.drawArc(QRectF(s * 0.14, s * 0.16, s * 0.72, s * 0.68), 0, 180 * 16)
    p.setBrush(QColor(color))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(QRectF(s * 0.12, s * 0.48, s * 0.16, s * 0.34), s * 0.07, s * 0.07)
    p.drawRoundedRect(QRectF(s * 0.72, s * 0.48, s * 0.16, s * 0.34), s * 0.07, s * 0.07)
    p.end()
    return pm


def arrow_pixmap(size: int = 16, color: str = theme.TEXT, up: bool = True) -> QPixmap:
    """Flecha (chevron) hacia arriba o hacia abajo."""
    pm, p = _canvas(size)
    s = size
    p.setPen(_pen(color, s, 0.12))
    p.setBrush(Qt.NoBrush)
    y1, y2 = (0.64, 0.36) if up else (0.36, 0.64)
    p.drawLine(QPointF(s * 0.26, s * y1), QPointF(s * 0.50, s * y2))
    p.drawLine(QPointF(s * 0.50, s * y2), QPointF(s * 0.74, s * y1))
    p.end()
    return pm


def close_pixmap(size: int = 16, color: str = theme.TEXT) -> QPixmap:
    """Aspa para quitar un elemento."""
    pm, p = _canvas(size)
    s = size
    p.setPen(_pen(color, s, 0.12))
    p.drawLine(QPointF(s * 0.28, s * 0.28), QPointF(s * 0.72, s * 0.72))
    p.drawLine(QPointF(s * 0.72, s * 0.28), QPointF(s * 0.28, s * 0.72))
    p.end()
    return pm


def star_pixmap(size: int = 16, color: str = theme.TEXT) -> QPixmap:
    """Estrella: marca la salida principal."""
    pm, p = _canvas(size)
    s = size
    path = QPainterPath()
    cx, cy, r = s * 0.5, s * 0.52, s * 0.40
    inner = r * 0.44
    for i in range(10):
        ang = math.radians(-90 + i * 36)
        rad = r if i % 2 == 0 else inner
        x = cx + rad * math.cos(ang)
        y = cy + rad * math.sin(ang)
        if i == 0:
            path.moveTo(x, y)
        else:
            path.lineTo(x, y)
    path.closeSubpath()
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(color))
    p.drawPath(path)
    p.end()
    return pm


# --------------------------------------------------------------------------
def icon(pixmap: QPixmap) -> QIcon:
    return QIcon(pixmap)


ICON_BUILDERS = {
    "mic": mic_pixmap,
    "speaker": speaker_pixmap,
    "music": music_pixmap,
    "sliders": sliders_pixmap,
    "stop": stop_pixmap,
    "plug": plug_pixmap,
    "refresh": refresh_pixmap,
    "headphones": headphones_pixmap,
    "up": lambda size=16, color=theme.TEXT: arrow_pixmap(size, color, up=True),
    "down": lambda size=16, color=theme.TEXT: arrow_pixmap(size, color, up=False),
    "close": close_pixmap,
    "star": star_pixmap,
}


def make(name: str, size: int = 18, color: str = theme.TEXT, **kwargs) -> QPixmap:
    builder = ICON_BUILDERS.get(name)
    if builder is None:
        return QPixmap()
    return builder(size=size, color=color, **kwargs)
