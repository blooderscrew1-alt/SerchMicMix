"""Widgets personalizados de Serch MicMix: switch, vumetro y tarjetas de dispositivo."""

from __future__ import annotations

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QPoint,
    QPropertyAnimation,
    QRect,
    QRectF,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import (
    QAbstractButton,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QPushButton,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from . import icons, theme


# --------------------------------------------------------------------------
# Iconos y utilidades
# --------------------------------------------------------------------------
def icon_label(name: str, size: int = 16, color: str = theme.TEXT) -> QLabel:
    """Etiqueta que muestra un icono vectorial del tema."""
    label = QLabel()
    pixmap = icons.make(name, size=size, color=color)
    label.setPixmap(pixmap)
    label.setFixedSize(size, size)
    return label


class FlowLayout(QLayout):
    """Disposicion que reparte los widgets en varias filas segun el ancho.

    Evita que la fila de acciones rapidas se salga de la ventana en pantallas
    pequenas o con fuentes grandes.
    """

    def __init__(self, parent=None, h_spacing: int = 8, v_spacing: int = 8) -> None:
        super().__init__(parent)
        self._items: list = []
        self._h = h_spacing
        self._v = v_spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item) -> None:  # noqa: N802
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):  # noqa: N802
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int):  # noqa: N802
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):  # noqa: N802
        return Qt.Orientations(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self._do_layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self) -> QSize:  # noqa: N802
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(margins.left() + margins.right(), margins.top() + margins.bottom())
        return size

    def _do_layout(self, rect: QRect, test_only: bool) -> int:
        margins = self.contentsMargins()
        eff = rect.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())
        x, y, line_height = eff.x(), eff.y(), 0
        for item in self._items:
            hint = item.sizeHint()
            next_x = x + hint.width() + self._h
            if next_x - self._h > eff.right() and line_height > 0:
                x = eff.x()
                y = y + line_height + self._v
                next_x = x + hint.width() + self._h
                line_height = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x = next_x
            line_height = max(line_height, hint.height())
        return y + line_height - rect.y() + margins.bottom()


# --------------------------------------------------------------------------
# Interruptor animado
# --------------------------------------------------------------------------
class ToggleSwitch(QAbstractButton):
    """Interruptor tipo iOS, animado y sin bordes nativos."""

    def __init__(self, parent=None, width: int = 46, height: int = 26) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self._w, self._h = width, height
        self.setFixedSize(width, height)
        self._knob = 0.0
        self._anim = QPropertyAnimation(self, b"knob", self)
        self._anim.setDuration(170)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self.toggled.connect(self._animate)

    def _get_knob(self) -> float:
        return self._knob

    def _set_knob(self, value: float) -> None:
        self._knob = float(value)
        self.update()

    knob = Property(float, _get_knob, _set_knob)

    def _animate(self, checked: bool) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._knob)
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()

    def setChecked(self, checked: bool) -> None:  # noqa: N802
        super().setChecked(checked)
        self._anim.stop()
        self._knob = 1.0 if checked else 0.0
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802, ARG002
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        t = self._knob
        r = QRectF(0.5, 0.5, self._w - 1, self._h - 1)
        radius = r.height() / 2

        path = QPainterPath()
        path.addRoundedRect(r, radius, radius)

        if t <= 0.01:
            p.fillPath(path, QColor(theme.BORDER))
        else:
            grad = QLinearGradient(r.topLeft(), r.topRight())
            grad.setColorAt(0.0, QColor(theme.ACCENT_DEEP))
            grad.setColorAt(1.0, QColor(theme.mix(theme.ACCENT, theme.ACCENT_2, t)))
            p.fillPath(path, grad)

        p.setPen(QPen(QColor(theme.mix(theme.BORDER, theme.ACCENT, t)), 1.0))
        p.drawPath(path)

        d = r.height() - 6
        x = r.left() + 3 + t * (r.width() - d - 6)
        knob = QRectF(x, r.top() + 3, d, d)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(theme.TEXT))
        p.drawEllipse(knob)


# --------------------------------------------------------------------------
# Vumetro
# --------------------------------------------------------------------------
class LevelBar(QWidget):
    """Barra de nivel horizontal con pico y decaimiento suave."""

    def __init__(self, parent=None, height: int = 8) -> None:
        super().__init__(parent)
        self.setFixedHeight(height)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._display = 0.0
        self._peak = 0.0
        self._active = False
        self._height = height

    def set_level(self, value: float) -> None:
        value = max(0.0, min(1.0, float(value)))
        self._display = value if value > self._display else self._display * 0.86
        self._peak = max(value, self._peak * 0.965)
        self.update()

    def set_active(self, active: bool) -> None:
        if active != self._active:
            self._active = active
            self.update()

    def reset(self) -> None:
        self._display = 0.0
        self._peak = 0.0
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802, ARG002
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        r = QRectF(0, 0, w, h)
        radius = h / 2

        track = QPainterPath()
        track.addRoundedRect(r, radius, radius)
        p.fillPath(track, QColor(theme.BG_ALT))

        if not self._active or self._display <= 0.002:
            p.setPen(QPen(QColor(theme.BORDER_SOFT), 1))
            p.drawPath(track)
            return

        fill_w = max(h, w * self._display)
        fill = QPainterPath()
        fill.addRoundedRect(QRectF(0, 0, fill_w, h), radius, radius)
        grad = QLinearGradient(0, 0, w, 0)
        grad.setColorAt(0.0, QColor(theme.ACCENT_DEEP))
        grad.setColorAt(0.55, QColor(theme.ACCENT))
        grad.setColorAt(1.0, QColor(theme.ACCENT_2))
        p.fillPath(fill, grad)

        if self._peak > 0.01:
            x = min(w - 2, w * self._peak)
            p.setPen(QPen(QColor(theme.TEXT), 1.6))
            p.drawLine(int(x), 1, int(x), int(h) - 1)


# --------------------------------------------------------------------------
# Etiquetas de ayuda
# --------------------------------------------------------------------------
class ElidedLabel(QLabel):
    """QLabel que recorta el texto con puntos suspensivos."""

    def __init__(self, text: str = "", parent=None) -> None:
        super().__init__(text, parent)
        self._full = text
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

    def setText(self, text: str) -> None:  # noqa: N802
        self._full = text or ""
        super().setText(self._full)
        self._apply_elide()

    def fullText(self) -> str:  # noqa: N802
        return self._full

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._apply_elide()

    def _apply_elide(self) -> None:
        metrics = QFontMetrics(self.font())
        width = max(20, self.width())
        super().setText(metrics.elidedText(self._full, Qt.ElideRight, width))

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(40, super().minimumSizeHint().height())


# --------------------------------------------------------------------------
# Tarjeta de dispositivo
# --------------------------------------------------------------------------
class DeviceCard(QFrame):
    """Tarjeta clicable: un toque activa, otro toque silencia."""

    toggled = Signal(str, bool)
    gain_changed = Signal(str, float)
    solo_changed = Signal(str, bool)
    source_changed = Signal(str, str, bool)
    state_changed = Signal(str, bool, bool)  # key, enabled, muted

    def __init__(self, key: str, title: str, subtitle: str, role: str, accent: str = theme.ACCENT, parent=None) -> None:
        super().__init__(parent)
        self.key = key
        self.role = role
        self.accent = accent
        self._enabled = False
        self._muted = False
        self._hover = 0.0
        self._state = 0.0
        self._warn = False
        self._anim_target = 0.0
        self._chip_sig: tuple | None = None

        self.setObjectName("DeviceCard")
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(112)

        self._anim = QPropertyAnimation(self, b"state", self)
        self._anim.setDuration(220)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._hover_anim = QPropertyAnimation(self, b"hover", self)
        self._hover_anim.setDuration(150)
        self._hover_anim.setEasingCurve(QEasingCurve.OutCubic)

        self._build(title, subtitle)

    # ------------------------------------------------------------ propiedades
    def _get_state(self) -> float:
        return self._state

    def _set_state(self, value: float) -> None:
        self._state = float(value)
        self.update()

    state = Property(float, _get_state, _set_state)

    def _get_hover(self) -> float:
        return self._hover

    def _set_hover(self, value: float) -> None:
        self._hover = float(value)
        self.update()

    hover = Property(float, _get_hover, _set_hover)

    # ------------------------------------------------------------------ UI
    def _build(self, title: str, subtitle: str) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 13, 16, 13)
        root.setSpacing(9)

        top = QHBoxLayout()
        top.setSpacing(10)
        self.dot = QLabel()
        self.dot.setFixedSize(9, 9)
        top.addWidget(self.dot)

        texts = QVBoxLayout()
        texts.setSpacing(1)
        self.title_label = ElidedLabel(title)
        self.title_label.setObjectName("CardTitle")
        font = QFont()
        font.setPointSize(10)
        font.setWeight(QFont.DemiBold)
        self.title_label.setFont(font)
        self.sub_label = ElidedLabel(subtitle)
        self.sub_label.setObjectName("Micro")
        texts.addWidget(self.title_label)
        texts.addWidget(self.sub_label)
        top.addLayout(texts, 1)

        self.chip = QLabel("APAGADO")
        self.chip.setAlignment(Qt.AlignCenter)
        self.chip.setMinimumWidth(84)
        top.addWidget(self.chip, 0, Qt.AlignTop)
        root.addLayout(top)

        self.level = LevelBar(self)
        root.addWidget(self.level)

        bottom = QHBoxLayout()
        bottom.setSpacing(10)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 150)
        self.slider.setValue(100)
        self.slider.setFixedHeight(18)
        self.slider.setToolTip("Volumen de este dispositivo")
        self.slider.valueChanged.connect(self._on_slider)
        bottom.addWidget(self.slider, 1)

        self.gain_label = QLabel("100%")
        self.gain_label.setObjectName("Micro")
        self.gain_label.setFixedWidth(38)
        self.gain_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        bottom.addWidget(self.gain_label)

        self.extra_buttons: list[QPushButton] = []
        if self.role == "input":
            self.solo_btn = self._mini_button("Solo", "Escuchar solo este dispositivo")
            self.solo_btn.setCheckable(True)
            self.solo_btn.toggled.connect(lambda on: self.solo_changed.emit(self.key, on))
            bottom.addWidget(self.solo_btn)
        else:
            self.mic_btn = self._mini_button("Mic", "Que los microfonos suenen en esta salida")
            self.mic_btn.setCheckable(True)
            self.mic_btn.setChecked(True)
            self.mic_btn.toggled.connect(lambda on: self.source_changed.emit(self.key, "mic", on))
            bottom.addWidget(self.mic_btn)
            self.music_btn = self._mini_button("Musica", "Que el audio del sistema suene en esta salida")
            self.music_btn.setCheckable(True)
            self.music_btn.setChecked(True)
            self.music_btn.toggled.connect(lambda on: self.source_changed.emit(self.key, "music", on))
            bottom.addWidget(self.music_btn)

        root.addLayout(bottom)
        self._refresh_chip()

    def _mini_button(self, text: str, tip: str) -> QPushButton:
        btn = QPushButton(text)
        btn.setObjectName("Mini")
        btn.setCheckable(True)
        btn.setToolTip(tip)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setFocusPolicy(Qt.NoFocus)
        return btn

    # --------------------------------------------------------------- estado
    def set_state(self, enabled: bool, muted: bool, gain: float, solo: bool = False,
                  sources: dict | None = None, level: float = 0.0, error: str = "",
                  subtitle: str | None = None) -> None:
        changed = (enabled != self._enabled) or (muted != self._muted)
        self._enabled, self._muted = enabled, muted
        self._warn = bool(error)

        target = 1.0 if (enabled and not muted) else 0.0
        if abs(self._anim_target - target) > 0.001:
            self._anim_target = target
            self._anim.stop()
            self._anim.setStartValue(self._state)
            self._anim.setEndValue(target)
            self._anim.start()

        self.level.set_active(enabled and not muted)
        self.level.set_level(level)

        if abs(self.slider.value() - int(gain * 100)) > 1:
            self.slider.blockSignals(True)
            self.slider.setValue(int(round(gain * 100)))
            self.slider.blockSignals(False)
        text = f"{int(round(gain * 100))}%"
        if self.gain_label.text() != text:
            self.gain_label.setText(text)

        if self.role == "input":
            if self.solo_btn.isChecked() != solo:
                self.solo_btn.blockSignals(True)
                self.solo_btn.setChecked(solo)
                self.solo_btn.blockSignals(False)
        elif sources is not None:
            for btn, name in ((self.mic_btn, "mic"), (self.music_btn, "music")):
                want = bool(sources.get(name, True))
                if btn.isChecked() != want:
                    btn.blockSignals(True)
                    btn.setChecked(want)
                    btn.blockSignals(False)

        if error:
            if self.sub_label.fullText() != error:
                self.sub_label.setText(error)
                self.sub_label.setStyleSheet(f"color: {theme.DANGER};")
        elif subtitle is not None and self.sub_label.fullText() != subtitle:
            self.sub_label.setText(subtitle)
            self.sub_label.setStyleSheet("")

        self._refresh_chip()
        if changed:
            self.state_changed.emit(self.key, enabled, muted)

    def _refresh_chip(self) -> None:
        if not self._enabled:
            text, color = "APAGADO", theme.TEXT_MUTE
        elif self._muted:
            text, color = "SILENCIADO", theme.WARNING
        else:
            text, color = "ACTIVO", theme.SUCCESS
        signature = (text, color)
        if getattr(self, "_chip_sig", None) == signature:
            return
        self._chip_sig = signature
        self.chip.setText(text)
        self.chip.setStyleSheet(
            f"color: {color}; font-size: 10px; font-weight: 700; letter-spacing: 1px;"
            f"border: 1px solid {color}; border-radius: 10px; padding: 2px 9px;"
        )
        self.dot.setStyleSheet(f"background: {color}; border-radius: 4px;")

    def mark_missing(self, subtitle: str) -> None:
        if self._chip_sig == ("NO DISPONIBLE", theme.DANGER):
            return
        self._chip_sig = ("NO DISPONIBLE", theme.DANGER)
        self.sub_label.setText(subtitle)
        self.sub_label.setStyleSheet(f"color: {theme.DANGER};")
        self.chip.setText("NO DISPONIBLE")
        self.chip.setStyleSheet(
            f"color: {theme.DANGER}; font-size: 10px; font-weight: 700;"
            f"border: 1px solid {theme.DANGER}; border-radius: 10px; padding: 2px 9px;"
        )
        self.dot.setStyleSheet(f"background: {theme.DANGER}; border-radius: 4px;")

    # ------------------------------------------------------------- eventos
    def _on_slider(self, value: int) -> None:
        self.gain_label.setText(f"{value}%")
        self.gain_changed.emit(self.key, value / 100.0)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.toggled.emit(self.key, not self._enabled)
            event.accept()
            return
        super().mousePressEvent(event)

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._hover)
        self._hover_anim.setEndValue(1.0)
        self._hover_anim.start()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._hover)
        self._hover_anim.setEndValue(0.0)
        self._hover_anim.start()
        super().leaveEvent(event)

    # -------------------------------------------------------------- pintado
    def paintEvent(self, event) -> None:  # noqa: N802, ARG002
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        t = self._state
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)

        base = theme.mix(theme.CARD, theme.CARD_ON, t)
        if self._hover > 0.01:
            base = theme.mix(base, theme.CARD_HOVER, self._hover * 0.75)
        path = QPainterPath()
        path.addRoundedRect(rect, 15, 15)
        p.fillPath(path, QColor(base))

        if t > 0.01:
            grad = QLinearGradient(rect.topLeft(), rect.topRight())
            grad.setColorAt(0.0, QColor(theme.rgba(self.accent, 0.16 * t)))
            grad.setColorAt(0.55, QColor(theme.rgba(self.accent, 0.0)))
            clip = QPainterPath()
            clip.addRoundedRect(rect, 15, 15)
            p.save()
            p.setClipPath(clip)
            p.fillRect(rect, grad)
            p.restore()

        border = theme.mix(theme.BORDER, self.accent, t)
        if self._warn:
            border = theme.DANGER
        p.setPen(QPen(QColor(border), 1.2))
        p.drawPath(path)

        if t > 0.02:
            bar = QRectF(rect.left() + 1.5, rect.top() + 12, 3.0, rect.height() - 24)
            bar_path = QPainterPath()
            bar_path.addRoundedRect(bar, 1.5, 1.5)
            p.fillPath(bar_path, QColor(theme.rgba(self.accent, t)))


# --------------------------------------------------------------------------
# Fila de la lista de prioridad
# --------------------------------------------------------------------------
class PriorityRow(QFrame):
    """Una salida dentro de la cadena de prioridad.

    La fila de arriba es siempre la principal. Los botones permiten subirla o
    bajarla de puesto, o quitarla de la lista.
    """

    move_requested = Signal(str, int)  # clave, desplazamiento (-1 sube, +1 baja)
    remove_requested = Signal(str)

    STATUS = {
        "active": ("ACTIVA", theme.SUCCESS),
        "connecting": ("CONECTANDO", theme.ACCENT),
        "wait": ("EN ESPERA", theme.TEXT_MUTE),
        "absent": ("NO DISPONIBLE", theme.WARNING),
        "error": ("ERROR", theme.DANGER),
    }

    def __init__(self, key: str, position: int, name: str, subtitle: str, parent=None) -> None:
        super().__init__(parent)
        self.key = key
        self.position = position
        self._status = "wait"
        self._hover = 0.0
        self._sig: tuple | None = None

        self.setObjectName("PriorityRow")
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.setMinimumHeight(62)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        root = QHBoxLayout(self)
        root.setContentsMargins(12, 9, 12, 9)
        root.setSpacing(10)

        self.badge = QLabel(str(position))
        self.badge.setFixedSize(26, 26)
        self.badge.setAlignment(Qt.AlignCenter)
        root.addWidget(self.badge)

        texts = QVBoxLayout()
        texts.setSpacing(1)
        self.title = ElidedLabel(name)
        self.title.setObjectName("CardTitle")
        self.subtitle = ElidedLabel(subtitle)
        self.subtitle.setObjectName("Micro")
        texts.addWidget(self.title)
        texts.addWidget(self.subtitle)
        root.addLayout(texts, 1)

        self.chip = QLabel("EN ESPERA")
        self.chip.setAlignment(Qt.AlignCenter)
        self.chip.setMinimumWidth(96)
        root.addWidget(self.chip)

        self.up_btn = self._arrow("up", "Subir en la lista (más prioridad)")
        self.up_btn.clicked.connect(lambda: self.move_requested.emit(self.key, -1))
        root.addWidget(self.up_btn)

        self.down_btn = self._arrow("down", "Bajar en la lista (menos prioridad)")
        self.down_btn.clicked.connect(lambda: self.move_requested.emit(self.key, 1))
        root.addWidget(self.down_btn)

        self.remove_btn = self._arrow("close", "Quitar de la lista de prioridad")
        self.remove_btn.clicked.connect(lambda: self.remove_requested.emit(self.key))
        root.addWidget(self.remove_btn)

        self.set_status("wait")

    def _arrow(self, icon_name: str, tip: str) -> QPushButton:
        btn = QPushButton()
        btn.setObjectName("Mini")
        btn.setFixedSize(28, 28)
        btn.setIcon(icons.icon(icons.make(icon_name, size=14, color=theme.TEXT_DIM)))
        btn.setIconSize(QSize(14, 14))
        btn.setToolTip(tip)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setFocusPolicy(Qt.NoFocus)
        return btn

    # ------------------------------------------------------------- estado
    def set_position(self, position: int, total: int) -> None:
        self.position = position
        self.badge.setText(str(position))
        self.up_btn.setEnabled(position > 1)
        self.down_btn.setEnabled(position < total)

    def set_name(self, name: str) -> None:
        self.title.setText(name)

    def set_status(self, status: str, subtitle: str | None = None) -> None:
        self._status = status
        text, color = self.STATUS.get(status, self.STATUS["wait"])
        if subtitle is not None:
            self.subtitle.setText(subtitle)

        signature = (status, text, subtitle, self.position == 1)
        if signature == self._sig:
            return
        self._sig = signature

        self.chip.setText(text)
        self.chip.setStyleSheet(
            f"color: {color}; font-size: 10px; font-weight: 700; letter-spacing: 1px;"
            f"border: 1px solid {color}; border-radius: 10px; padding: 3px 10px;"
        )

        if self.position == 1:
            badge_style = (
                f"background: {theme.rgba(theme.ACCENT, 0.9)}; color: #0A0D16;"
                "border-radius: 13px; font-weight: 800; font-size: 12px;"
            )
        elif status == "active":
            badge_style = (
                f"background: {theme.rgba(theme.SUCCESS, 0.9)}; color: #0A0D16;"
                "border-radius: 13px; font-weight: 800; font-size: 12px;"
            )
        else:
            badge_style = (
                f"background: {theme.SURFACE}; color: {theme.TEXT_DIM};"
                f"border: 1px solid {theme.BORDER};"
                "border-radius: 13px; font-weight: 700; font-size: 12px;"
            )
        self.badge.setStyleSheet(badge_style)
        self.update()

    def _get_hover(self) -> float:
        return self._hover

    def _set_hover(self, value: float) -> None:
        self._hover = float(value)
        self.update()

    hover = Property(float, _get_hover, _set_hover)

    def enterEvent(self, event) -> None:  # noqa: N802
        self._set_hover(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._set_hover(0.0)
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802, ARG002
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        active = self._status in ("active", "connecting")
        primary = self.position == 1

        base = theme.mix(theme.CARD, theme.CARD_ON, 1.0 if active else 0.0)
        if self._hover > 0.01:
            base = theme.mix(base, theme.CARD_HOVER, self._hover * 0.6)
        path = QPainterPath()
        path.addRoundedRect(rect, 13, 13)
        p.fillPath(path, QColor(base))

        accent = theme.SUCCESS if active else theme.ACCENT
        if primary and not active:
            p.setPen(QPen(QColor(theme.rgba(theme.ACCENT, 0.55)), 1.2, Qt.DashLine))
        elif active:
            p.setPen(QPen(QColor(accent), 1.4))
        else:
            p.setPen(QPen(QColor(theme.BORDER), 1.1))
        p.drawPath(path)
