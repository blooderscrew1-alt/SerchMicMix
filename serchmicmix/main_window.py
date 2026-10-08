"""Ventana principal de serchmicmix."""

from __future__ import annotations

import threading

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import (
    QAction,
    QColor,
    QFont,
    QIcon,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QTextBrowser,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import APP_TITLE, devices as dev_mod
from . import icons, theme, vbcable
from .config import Config, config_dir
from .engine import AudioEngine
from .install_dialog import InstallDialog
from .widgets import DeviceCard, FlowLayout, PriorityRow, ToggleSwitch, icon_label

PRESETS = [
    ("mic_to_pc", "mic", "Micrófono al PC",
     "Manda tus micrófonos al cable virtual: Discord, OBS, Zoom o juegos lo escuchan como «CABLE Output»."),
    ("monitor", "speaker", "Escuchar mi micrófono",
     "Reproduce los micrófonos en tus altavoces o auriculares reales."),
    ("music", "music", "Música a las bocinas",
     "Toma lo que suena por el cable virtual y lo manda a tus altavoces."),
    ("all", "sliders", "Mezclar todo",
     "Enciende todas las entradas y todas las salidas a la vez."),
    ("stop", "stop", "Detener todo",
     "Apaga todas las entradas y salidas."),
]


def make_logo(size: int = 64) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    r = size
    path = QPainterPath()
    path.addRoundedRect(1, 1, r - 2, r - 2, r * 0.28, r * 0.28)
    grad = QLinearGradient(0, 0, r, r)
    grad.setColorAt(0.0, QColor(theme.ACCENT))
    grad.setColorAt(1.0, QColor(theme.ACCENT_2))
    p.fillPath(path, grad)

    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#0A0D16"))
    bars = [0.30, 0.55, 0.82, 0.50, 0.68, 0.34]
    bw = r * 0.075
    gap = (r - len(bars) * bw) / (len(bars) + 1)
    for i, h in enumerate(bars):
        bh = (r - 2) * h * 0.62
        x = gap + i * (bw + gap)
        y = (r - bh) / 2
        bar = QPainterPath()
        bar.addRoundedRect(x, y, bw, bh, bw / 2, bw / 2)
        p.fillPath(bar, QColor("#0A0D16"))
    p.end()
    return pm


class MainWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.config = Config()

        self.setObjectName("Root")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setWindowTitle("Serch MicMix — Mezclador de audio")
        self.setWindowIcon(QIcon(make_logo(128)))
        self.resize(
            int(self.config.get("window", "w", default=1180)),
            int(self.config.get("window", "h", default=760)),
        )
        self.setMinimumSize(QSize(940, 620))

        self.engine = AudioEngine(self.config)

        self.inputs: list[dev_mod.DeviceInfo] = []
        self.outputs: list[dev_mod.DeviceInfo] = []
        self.input_cards: dict[str, DeviceCard] = {}
        self.output_cards: dict[str, DeviceCard] = {}
        self.vb_status = vbcable.VBStatus(False)
        self._scan_result = None
        self._scanning = False
        self._master_muted = False
        self.priority_rows: dict[str, PriorityRow] = {}
        self._device_sig: tuple | None = None
        self._watch_result = None
        self._watch_busy = False

        self._build_ui()
        self._build_timer()

        # Primer escaneo en segundo plano.
        QTimer.singleShot(80, lambda: self._start_scan(hard=True))

    # -------------------------------------------------------------------- UI
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_header())
        self.banner = self._build_banner()
        root.addWidget(self.banner)
        root.addWidget(self._build_presets())

        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(16, 6, 16, 10)
        body_layout.setSpacing(14)
        body_layout.addWidget(self._build_panel("input"), 1)
        body_layout.addWidget(self._build_panel("output"), 1)
        root.addWidget(body, 1)

        root.addWidget(self._build_footer())

    # ---------------------------------------------------------------- header
    def _build_header(self) -> QWidget:
        header = QFrame()
        header.setObjectName("Header")
        header.setFixedHeight(66)
        lay = QHBoxLayout(header)
        lay.setContentsMargins(18, 0, 18, 0)
        lay.setSpacing(12)

        logo = QLabel()
        logo.setPixmap(make_logo(34))
        logo.setFixedSize(34, 34)
        lay.addWidget(logo)

        titles = QVBoxLayout()
        titles.setSpacing(0)
        t = QLabel(APP_TITLE)
        t.setObjectName("AppTitle")
        s = QLabel("Mezclador de micrófonos y salidas")
        s.setObjectName("Micro")
        titles.addWidget(t)
        titles.addWidget(s)
        lay.addLayout(titles)

        lay.addStretch(1)

        self.vb_pill = QPushButton("Comprobando…")
        self.vb_pill.setObjectName("Chip")
        self.vb_pill.setCursor(Qt.PointingHandCursor)
        self.vb_pill.clicked.connect(self._on_vb_pill)
        lay.addWidget(self.vb_pill)

        self.refresh_btn = QPushButton(" Actualizar")
        self.refresh_btn.setIcon(icons.icon(icons.make("refresh", size=16, color=theme.TEXT)))
        self.refresh_btn.setIconSize(QSize(16, 16))
        self.refresh_btn.setToolTip("Volver a buscar dispositivos de audio conectados")
        self.refresh_btn.clicked.connect(lambda: self._start_scan(hard=False))
        lay.addWidget(self.refresh_btn)

        self.help_btn = QPushButton("?")
        self.help_btn.setObjectName("Ghost")
        self.help_btn.setFixedWidth(36)
        self.help_btn.setToolTip("Cómo se usa Serch MicMix")
        self.help_btn.clicked.connect(self._show_help)
        lay.addWidget(self.help_btn)

        self.menu_btn = QToolButton()
        self.menu_btn.setText("⋮")
        self.menu_btn.setObjectName("Ghost")
        self.menu_btn.setPopupMode(QToolButton.InstantPopup)
        self.menu_btn.setCursor(Qt.PointingHandCursor)
        self.menu_btn.setFixedWidth(36)
        self.menu_btn.setMenu(self._build_menu())
        lay.addWidget(self.menu_btn)
        return header

    def _build_menu(self) -> QMenu:
        menu = QMenu(self)

        self.act_all_apis = QAction("Mostrar todos los controladores", self)
        self.act_all_apis.setCheckable(True)
        self.act_all_apis.setChecked(bool(self.config.get("show_all_apis", default=False)))
        self.act_all_apis.triggered.connect(self._toggle_all_apis)
        menu.addAction(self.act_all_apis)

        self.act_limiter = QAction("Limitador de salida (evita distorsión)", self)
        self.act_limiter.setCheckable(True)
        self.act_limiter.setChecked(bool(self.config.get("limiter", default=True)))
        self.act_limiter.triggered.connect(lambda on: self.engine.set_limiter(on))
        menu.addAction(self.act_limiter)

        menu.addSeparator()
        act_reset = QAction("Reiniciar motor y recargar dispositivos", self)
        act_reset.triggered.connect(self._hard_refresh)
        menu.addAction(act_reset)

        act_folder = QAction("Abrir carpeta de configuración", self)
        act_folder.triggered.connect(lambda: self._open_folder(config_dir()))
        menu.addAction(act_folder)

        menu.addSeparator()
        act_about = QAction("Acerca de Serch MicMix", self)
        act_about.triggered.connect(self._about)
        menu.addAction(act_about)
        return menu

    def _build_banner(self) -> QWidget:
        banner = QFrame()
        banner.setObjectName("Banner")
        banner.setStyleSheet(
            f"#Banner {{ background: {theme.rgba(theme.WARNING, 0.10)};"
            f" border-bottom: 1px solid {theme.rgba(theme.WARNING, 0.25)}; }}"
        )
        lay = QHBoxLayout(banner)
        lay.setContentsMargins(18, 10, 18, 10)
        lay.setSpacing(12)

        icon = QLabel()
        icon.setPixmap(icons.make("headphones", size=20, color=theme.WARNING))
        icon.setFixedSize(20, 20)
        lay.addWidget(icon)

        text = QLabel(
            "VB-Cable no está instalado. Es un cable de audio virtual gratuito que permite "
            "enviar tu micrófono o tu música a otros programas (OBS, Discord, Zoom…)."
        )
        text.setWordWrap(True)
        text.setObjectName("Subtle")
        lay.addWidget(text, 1)

        install = QPushButton("Instalar VB-Cable")
        install.setObjectName("Primary")
        install.clicked.connect(self._install_vbcable)
        lay.addWidget(install)

        info = QPushButton("Más información")
        info.clicked.connect(vbcable.open_page)
        lay.addWidget(info)
        banner.setVisible(False)
        return banner

    def _build_presets(self) -> QWidget:
        wrap = QWidget()
        outer = QHBoxLayout(wrap)
        outer.setContentsMargins(18, 12, 18, 4)
        outer.setSpacing(10)

        label = QLabel("ACCIONES RÁPIDAS")
        label.setObjectName("PanelTitle")
        outer.addWidget(label, 0, Qt.AlignTop)

        row = QWidget()
        flow = FlowLayout(row, h_spacing=8, v_spacing=8)
        self.preset_buttons = []
        for key, icon_name, text, tip in PRESETS:
            btn = QPushButton(text)
            btn.setObjectName("Chip")
            btn.setCursor(Qt.PointingHandCursor)
            btn.setToolTip(tip)
            btn.setIcon(icons.icon(icons.make(icon_name, size=16, color=theme.TEXT)))
            btn.setIconSize(QSize(16, 16))
            btn.clicked.connect(lambda _=False, k=key: self._apply_preset(k))
            flow.addWidget(btn)
            self.preset_buttons.append(btn)
        outer.addWidget(row, 1)
        return wrap

    def _build_panel(self, role: str) -> QWidget:
        panel = QWidget()
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        if role == "input":
            title = "MICRÓFONOS Y ENTRADAS"
            hint = "Toca una tarjeta para encenderla o apagarla."
            icon_name = "mic"
        else:
            title = "SALIDAS / BOCINAS"
            hint = "Toca una tarjeta para activar o desactivar esa salida."
            icon_name = "speaker"

        head_row = QHBoxLayout()
        head_row.setSpacing(8)
        head_row.addWidget(icon_label(icon_name, 16, theme.ACCENT_2 if role == "input" else theme.INFO))
        head = QLabel(title)
        head.setObjectName("PanelTitle")
        head_row.addWidget(head)
        head_row.addStretch(1)

        if role == "output":
            prio_label = QLabel("Prioridad automática")
            prio_label.setObjectName("Micro")
            head_row.addWidget(prio_label)
            self.prio_toggle = ToggleSwitch(width=40, height=22)
            self.prio_toggle.setToolTip(
                "Solo suena la primera salida de la lista que esté disponible.\n"
                "Si la principal se apaga o se desconecta, pasa sola a la siguiente."
            )
            self.prio_toggle.setChecked(bool(self.config.get("priority", "enabled", default=False)))
            self.prio_toggle.toggled.connect(self._on_priority_toggled)
            head_row.addWidget(self.prio_toggle)

        lay.addLayout(head_row)
        self.prio_hint = QLabel(hint)
        self.prio_hint.setObjectName("Micro")
        self.prio_hint.setWordWrap(True)
        lay.addWidget(self.prio_hint)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        inner_layout = QVBoxLayout(inner)
        inner_layout.setContentsMargins(0, 4, 8, 12)
        inner_layout.setSpacing(10)

        empty_text = "No se encontraron dispositivos.\nConecta uno y pulsa «Actualizar»."

        if role == "input":
            empty = self._empty_label(empty_text)
            inner_layout.addWidget(empty)
            inner_layout.addStretch(1)
            self.input_layout = inner_layout
            self.input_empty = empty
        else:
            # --- pagina normal: todas las salidas ---
            self.outputs_page = QWidget()
            out_layout = QVBoxLayout(self.outputs_page)
            out_layout.setContentsMargins(0, 0, 0, 0)
            out_layout.setSpacing(10)
            self.output_empty = self._empty_label(empty_text)
            out_layout.addWidget(self.output_empty)
            self.output_layout = out_layout
            out_layout.addStretch(1)
            inner_layout.addWidget(self.outputs_page)

            # --- pagina de prioridad: lista ordenable ---
            self.priority_page = QWidget()
            prio_layout = QVBoxLayout(self.priority_page)
            prio_layout.setContentsMargins(0, 0, 0, 0)
            prio_layout.setSpacing(8)

            self.priority_layout = QVBoxLayout()
            self.priority_layout.setSpacing(8)
            prio_layout.addLayout(self.priority_layout)

            self.priority_empty = self._empty_label(
                "La lista está vacía.\nAñade las salidas por orden: la de arriba suena primero."
            )
            self.priority_layout.addWidget(self.priority_empty)

            add_row = QHBoxLayout()
            self.add_output_btn = QPushButton("  Añadir salida")
            self.add_output_btn.setObjectName("Chip")
            self.add_output_btn.setIcon(icons.icon(icons.make("speaker", size=15, color=theme.TEXT)))
            self.add_output_btn.setIconSize(QSize(15, 15))
            self.add_output_btn.setCursor(Qt.PointingHandCursor)
            self.add_output_btn.clicked.connect(self._show_add_output_menu)
            add_row.addWidget(self.add_output_btn)

            self.priority_all_btn = QPushButton("  Añadir todas")
            self.priority_all_btn.setObjectName("Chip")
            self.priority_all_btn.setCursor(Qt.PointingHandCursor)
            self.priority_all_btn.clicked.connect(self._priority_add_all)
            add_row.addWidget(self.priority_all_btn)
            add_row.addStretch(1)
            prio_layout.addLayout(add_row)

            note = QLabel(
                "Solo suena la primera de la lista que esté conectada. Usa ↑ ↓ para "
                "cambiar el orden: la de más arriba es siempre la principal."
            )
            note.setObjectName("Micro")
            note.setWordWrap(True)
            prio_layout.addWidget(note)
            prio_layout.addStretch(1)

            inner_layout.addWidget(self.priority_page)
            inner_layout.addStretch(1)
            self.priority_page.setVisible(False)

        scroll.setWidget(inner)
        lay.addWidget(scroll, 1)

        if role == "output":
            self._refresh_priority_pages()
        return panel

    def _empty_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("Subtle")
        label.setAlignment(Qt.AlignCenter)
        label.setWordWrap(True)
        label.setMinimumHeight(120)
        return label

    def _build_footer(self) -> QWidget:
        footer = QFrame()
        footer.setObjectName("Footer")
        footer.setFixedHeight(62)
        lay = QHBoxLayout(footer)
        lay.setContentsMargins(18, 0, 18, 0)
        lay.setSpacing(14)

        self.status_label = QLabel("Iniciando…")
        self.status_label.setObjectName("Micro")
        lay.addWidget(self.status_label)

        lay.addStretch(1)

        self.mute_btn = QPushButton(" Silenciar todo")
        self.mute_btn.setCheckable(True)
        self.mute_btn.setIcon(icons.icon(icons.make("speaker", size=16, color=theme.TEXT, muted=True)))
        self.mute_btn.setIconSize(QSize(16, 16))
        self.mute_btn.setToolTip("Silencia todo sin apagar los dispositivos")
        self.mute_btn.clicked.connect(self._toggle_master_mute)
        lay.addWidget(self.mute_btn)

        vol_label = QLabel("Mezcla")
        vol_label.setObjectName("Micro")
        lay.addWidget(vol_label)

        self.master_slider = QSlider(Qt.Horizontal)
        self.master_slider.setRange(0, 150)
        self.master_slider.setFixedWidth(180)
        self.master_slider.setValue(int(float(self.config.get("master_gain", default=0.9)) * 100))
        self.master_slider.valueChanged.connect(self._on_master)
        lay.addWidget(self.master_slider)

        self.master_value = QLabel(f"{self.master_slider.value()}%")
        self.master_value.setObjectName("Micro")
        self.master_value.setFixedWidth(40)
        lay.addWidget(self.master_value)
        return footer

    # ----------------------------------------------------------------- timer
    def _build_timer(self) -> None:
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

        # Vigilancia de dispositivos: detecta una bocina Bluetooth que se
        # enciende o se apaga sin cortar el audio que este sonando.
        self._watch_timer = QTimer(self)
        self._watch_timer.setInterval(2500)
        self._watch_timer.timeout.connect(self._watch_devices)
        self._watch_timer.start()

    # ---------------------------------------------------------------- escaneo
    def _start_scan(self, hard: bool = False) -> None:
        if self._scanning:
            return
        self._scanning = True
        self.refresh_btn.setEnabled(False)
        if self._scan_result is None:
            self.status_label.setText("Buscando dispositivos de audio…")

        engine_busy = bool(self.engine.stats.get("running"))
        show_all = bool(self.config.get("show_all_apis", default=False))

        def work() -> None:
            try:
                if hard and not engine_busy:
                    dev_mod.refresh_portaudio()
                ins, outs = dev_mod.build_registry(show_all=show_all)
                self._scan_result = ("ok", ins, outs)
            except Exception as exc:
                self._scan_result = ("err", f"{type(exc).__name__}: {exc}", None)

        threading.Thread(target=work, name="SerchMicMix-Scan", daemon=True).start()

    def _consume_scan(self) -> None:
        result, self._scan_result = self._scan_result, None
        if result is None:
            return
        self._scanning = False
        self.refresh_btn.setEnabled(True)
        if result[0] != "ok":
            self.status_label.setText(f"Error al buscar dispositivos: {result[1]}")
            return
        self._apply_devices(result[1], result[2])

    def _apply_devices(self, inputs, outputs) -> None:
        def sort_key(dev):
            return (
                0 if dev.is_default else 1,
                0 if not dev.virtual else 1,
                dev_mod.norm(dev.name),
            )

        self.inputs = sorted(inputs, key=sort_key)
        self.outputs = sorted(outputs, key=sort_key)
        self.engine.sync_devices(self.inputs, self.outputs)

        self._sync_cards(self.inputs, self.input_cards, self.input_layout, "input")
        self._sync_cards(self.outputs, self.output_cards, self.output_layout, "output")

        self.input_empty.setVisible(not self.inputs)
        self.output_empty.setVisible(not self.outputs)

        self._auto_append_priority()
        self._rebuild_priority_list()
        self._update_vb_status()
        self.status_label.setText(
            f"{len(self.inputs)} entradas · {len(self.outputs)} salidas · "
            f"{self.engine.stats.get('master_rate') or '—'} Hz"
        )

    def _sync_cards(self, devices, cards: dict, layout, role: str) -> None:
        wanted = {d.key: d for d in devices}
        for key in list(cards):
            if key not in wanted:
                card = cards.pop(key)
                layout.removeWidget(card)
                card.setParent(None)
                card.deleteLater()

        for index, dev in enumerate(devices):
            card = cards.get(dev.key)
            if card is None:
                card = self._make_card(dev, role)
                cards[dev.key] = card
            # Colocar en el orden correcto (antes del stretch final).
            layout.insertWidget(index, card)

    def _make_card(self, dev: dev_mod.DeviceInfo, role: str) -> DeviceCard:
        if dev.virtual:
            accent = theme.ACCENT_2
            kind = "Cable virtual"
        elif role == "input":
            accent = theme.ACCENT
            kind = "Micrófono"
        else:
            accent = theme.INFO
            kind = "Altavoz"
        subtitle = f"{kind} · {dev.hostapi} · {int(dev.default_sr)} Hz"

        card = DeviceCard(dev.key, dev.name, subtitle, role, accent)
        card.toggled.connect(lambda key, on: self._on_card_toggle(key, on))
        card.gain_changed.connect(self._on_card_gain)
        if role == "input":
            card.solo_changed.connect(self._on_card_solo)
        else:
            card.source_changed.connect(self._on_card_source)

        stored = (
            self.config.get("inputs", dev.key, default={})
            if role == "input"
            else self.config.get("outputs", dev.key, default={})
        ) or {}
        card.set_state(
            enabled=bool(stored.get("enabled", False)),
            muted=bool(stored.get("muted", False)),
            gain=float(stored.get("gain", 1.0)),
            solo=bool(stored.get("solo", False)),
            sources=stored.get("sources"),
        )
        return card

    # --------------------------------------------------------------- eventos
    def _on_card_toggle(self, key: str, enabled: bool) -> None:
        if self._master_muted:
            self._set_master_mute(False)
            for other in list(self.input_cards) + list(self.output_cards):
                if other != key:
                    if other in self.input_cards:
                        self.engine.set_input(other, muted=False)
                    else:
                        self.engine.set_output(other, muted=False)
        if key in self.input_cards:
            self.engine.set_input(key, enabled=enabled, muted=False)
        else:
            self.engine.set_output(key, enabled=enabled, muted=False)

    def _set_master_mute(self, muted: bool) -> None:
        self._master_muted = bool(muted)
        self.mute_btn.blockSignals(True)
        self.mute_btn.setChecked(self._master_muted)
        self.mute_btn.blockSignals(False)
        self.mute_btn.setText(" Quitar silencio" if self._master_muted else " Silenciar todo")
        self.mute_btn.setIcon(
            icons.icon(icons.make("speaker", size=16, color=theme.TEXT, muted=self._master_muted))
        )

    def _on_card_gain(self, key: str, value: float) -> None:
        if key in self.input_cards:
            self.engine.set_input(key, gain=value)
        else:
            self.engine.set_output(key, gain=value)

    def _on_card_solo(self, key: str, on: bool) -> None:
        self.engine.set_input(key, solo=on)

    def _on_card_source(self, key: str, name: str, on: bool) -> None:
        self.engine.set_output(key, sources={name: on})

    def _on_master(self, value: int) -> None:
        self.master_value.setText(f"{value}%")
        self.engine.set_master(value / 100.0)

    def _toggle_master_mute(self) -> None:
        muted = self.mute_btn.isChecked()
        self._set_master_mute(muted)
        for key in self.input_cards:
            self.engine.set_input(key, muted=muted)
        for key in self.output_cards:
            self.engine.set_output(key, muted=muted)

    def _toggle_all_apis(self, on: bool) -> None:
        self.config.set("show_all_apis", value=bool(on))
        self._start_scan(hard=False)

    # ------------------------------------------------------------ prioridad
    def _priority_config(self) -> dict:
        data = self.config.get("priority", default={}) or {}
        return {
            "enabled": bool(data.get("enabled", False)),
            "order": [str(k) for k in (data.get("order") or [])],
            "names": {str(k): str(v) for k, v in (data.get("names") or {}).items()},
            "removed": [str(k) for k in (data.get("removed") or [])],
        }

    def _save_priority(self, data: dict) -> None:
        self.config.set("priority", value=data)
        self.engine.set_priority_mode(bool(data["enabled"]))
        self.engine.set_priority_order(data["order"])
        self._refresh_priority_pages()

    def _find_output(self, key: str):
        for dev in self.outputs:
            if dev.key == key:
                return dev
        return None

    def _on_priority_toggled(self, on: bool) -> None:
        data = self._priority_config()
        data["enabled"] = bool(on)
        if on and not data["order"]:
            # Primera vez: se toma el orden actual de las salidas.
            data["order"] = [d.key for d in self.outputs]
            data["names"] = {d.key: d.name for d in self.outputs}
            data["removed"] = []
        self._save_priority(data)
        self._rebuild_priority_list()

    def _refresh_priority_pages(self) -> None:
        if not hasattr(self, "priority_page"):
            return
        enabled = self.prio_toggle.isChecked()
        self.outputs_page.setVisible(not enabled)
        self.priority_page.setVisible(enabled)
        self.prio_hint.setText(
            "Solo suena la primera salida de la lista que esté disponible. "
            "Si la principal se apaga, se pasa sola a la siguiente."
            if enabled
            else "Toca una tarjeta para activar o desactivar esa salida."
        )

    def _priority_add(self, key: str) -> None:
        data = self._priority_config()
        if key in data["order"]:
            return
        data["order"].append(key)
        data["removed"] = [k for k in data["removed"] if k != key]
        dev = self._find_output(key)
        if dev is not None:
            data["names"][key] = dev.name
        self._save_priority(data)
        self._rebuild_priority_list()

    def _priority_add_all(self) -> None:
        data = self._priority_config()
        for dev in self.outputs:
            if dev.key not in data["order"]:
                data["order"].append(dev.key)
            data["names"][dev.key] = dev.name
        data["removed"] = []
        self._save_priority(data)
        self._rebuild_priority_list()

    def _priority_move(self, key: str, delta: int) -> None:
        data = self._priority_config()
        order = data["order"]
        if key not in order:
            return
        i = order.index(key)
        j = max(0, min(len(order) - 1, i + delta))
        if i == j:
            return
        order.insert(j, order.pop(i))
        self._save_priority(data)
        self._rebuild_priority_list()

    def _priority_remove(self, key: str) -> None:
        data = self._priority_config()
        data["order"] = [k for k in data["order"] if k != key]
        if key not in data["removed"]:
            data["removed"].append(key)
        data["names"].pop(key, None)
        self._save_priority(data)
        self._rebuild_priority_list()

    def _show_add_output_menu(self) -> None:
        data = self._priority_config()
        menu = QMenu(self)
        pending = [d for d in self.outputs if d.key not in data["order"]]
        if not pending:
            act = QAction("Ya están todas en la lista", self)
            act.setEnabled(False)
            menu.addAction(act)
        else:
            for dev in pending:
                act = QAction(dev.name, self)
                act.triggered.connect(lambda _=False, k=dev.key: self._priority_add(k))
                menu.addAction(act)
        menu.exec(self.add_output_btn.mapToGlobal(self.add_output_btn.rect().bottomLeft()))

    def _auto_append_priority(self) -> None:
        """Anade al final las salidas nuevas que aparezcan.

        Se respetan las que el usuario haya quitado a proposito, y se guardan
        los nombres para poder seguir mostrando un dispositivo que ahora mismo
        no esta conectado (una bocina Bluetooth apagada).
        """
        data = self._priority_config()
        if not data["order"] and not data["enabled"]:
            return
        changed = False
        for dev in self.outputs:
            if data["names"].get(dev.key) != dev.name:
                data["names"][dev.key] = dev.name
                changed = True
            if dev.key in data["order"] or dev.key in data["removed"]:
                continue
            data["order"].append(dev.key)
            changed = True
        if changed:
            self._save_priority(data)

    def _rebuild_priority_list(self) -> None:
        if not hasattr(self, "priority_layout"):
            return
        data = self._priority_config()
        order = data["order"]
        names = data["names"]

        for row in self.priority_rows.values():
            self.priority_layout.removeWidget(row)
            row.setParent(None)
            row.deleteLater()
        self.priority_rows = {}

        self.priority_empty.setVisible(not order)
        total = len(order)
        for index, key in enumerate(order):
            dev = self._find_output(key)
            name = dev.name if dev is not None else names.get(key, key)
            subtitle = "Conectada" if dev is not None else "Sin conectar"
            row = PriorityRow(key, index + 1, name, subtitle)
            row.move_requested.connect(self._priority_move)
            row.remove_requested.connect(self._priority_remove)
            row.set_position(index + 1, total)
            if dev is None:
                row.set_status("absent", "Sin conectar — se usará cuando aparezca")
            self.priority_layout.addWidget(row)
            self.priority_rows[key] = row

    # -------------------------------------------------------- vigilancia dev
    def _watch_devices(self) -> None:
        """Comprueba si han conectado o desconectado algo, sin cortar el audio."""
        if self._watch_busy or self._scanning:
            return
        self._watch_busy = True

        def work() -> None:
            try:
                self._watch_result = dev_mod.poll_devices()
            except Exception:
                self._watch_result = ()

        threading.Thread(target=work, name="SerchMicMix-Watch", daemon=True).start()

    def _consume_watch(self) -> None:
        if self._watch_result is None:
            return
        sig, self._watch_result = self._watch_result, None
        self._watch_busy = False
        if not sig:
            return
        if self._device_sig and sig != self._device_sig:
            self._device_sig = sig
            self._start_scan(hard=False)
        else:
            self._device_sig = sig

    def _hard_refresh(self) -> None:
        self.status_label.setText("Reiniciando el motor de audio…")
        self.engine.disable_all(persist=False)
        self._device_sig = None

        def later() -> None:
            try:
                dev_mod.refresh_portaudio()
            except Exception:
                pass
            self._scanning = False
            self._start_scan(hard=False)

        QTimer.singleShot(900, later)

    # ------------------------------------------------------------- VB-Cable
    def _update_vb_status(self) -> None:
        self.vb_status = vbcable.detect(self.outputs, self.inputs)
        if self.vb_status.installed:
            self.vb_pill.setText("●  VB-Cable listo")
            self.vb_pill.setStyleSheet(
                f"color: {theme.SUCCESS}; border: 1px solid {theme.SUCCESS};"
                "border-radius: 14px; padding: 6px 14px; font-size: 12px;"
            )
            self.vb_pill.setToolTip(
                f"Salida: {self.vb_status.render_name}\nEntrada: {self.vb_status.capture_name}"
            )
            self.banner.setVisible(False)
        else:
            self.vb_pill.setText("○  Instalar VB-Cable")
            self.vb_pill.setStyleSheet(
                f"color: {theme.WARNING}; border: 1px solid {theme.WARNING};"
                "border-radius: 14px; padding: 6px 14px; font-size: 12px;"
            )
            self.vb_pill.setToolTip(self.vb_status.detail)
            self.banner.setVisible(True)

    def _on_vb_pill(self) -> None:
        if self.vb_status.installed:
            QMessageBox.information(
                self,
                "VB-Cable",
                "VB-Cable está instalado y funcionando.\n\n"
                f"Salida virtual: {self.vb_status.render_name}\n"
                f"Entrada virtual: {self.vb_status.capture_name}\n\n"
                "Para enviar audio a otros programas, activa una salida llamada "
                "«CABLE Input» y selecciona «CABLE Output» como micrófono en la otra app.",
            )
        else:
            self._install_vbcable()

    def _install_vbcable(self) -> None:
        dialog = InstallDialog(self)
        dialog.exec()
        if dialog.finished_ok:
            self._hard_refresh()
        else:
            self._start_scan(hard=False)

    # ----------------------------------------------------------------- ayuda
    def _show_help(self) -> None:
        self._make_help_dialog().exec()

    def _make_help_dialog(self) -> QDialog:
        dlg = QDialog(self)
        dlg.setWindowTitle("Cómo se usa Serch MicMix")
        dlg.resize(640, 560)
        lay = QVBoxLayout(dlg)
        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)
        browser.setStyleSheet(
            f"background: {theme.SURFACE}; border: 1px solid {theme.BORDER};"
            f"border-radius: 12px; padding: 14px; color: {theme.TEXT};"
        )
        browser.setHtml(
            f"""
            <h2 style="color:{theme.ACCENT_2}">Serch MicMix en 30 segundos</h2>
            <p><b>1. Enciende un micrófono.</b> Toca su tarjeta en la columna
            izquierda. Se ilumina y verás el nivel de sonido moverse. Tócala otra
            vez para apagarlo.</p>

            <p><b>2. Enciende una salida.</b> Toca una tarjeta de la columna
            derecha (tus altavoces, auriculares o «CABLE Input»). El audio se
            escuchará ahí.</p>

            <p><b>3. Ajusta el volumen</b> con el deslizador de cada tarjeta y la
            <i>Mezcla</i> general abajo a la derecha.</p>

            <h3 style="color:{theme.ACCENT}">¿Para qué sirve VB-Cable?</h3>
            <p>VB-Cable es un cable virtual gratuito. Un extremo (<b>CABLE Input</b>)
            se comporta como unos altavoces y el otro (<b>CABLE Output</b>) como un
            micrófono. Así puedes:</p>
            <ul>
              <li><b>Mandar tu micrófono a Discord, OBS o Zoom:</b> activa tu
              micrófono y activa la salida «CABLE Input». En la otra aplicación
              elige «CABLE Output» como micrófono.</li>
              <li><b>Mandar la música de tu PC a tus altavoces o al cable:</b> pon
              el reproductor en «CABLE Input» y activa aquí la entrada
              «CABLE Output».</li>
            </ul>

            <h3 style="color:{theme.ACCENT}">Prioridad automática de salidas</h3>
            <p>Es la opción pensada para <b>bocinas Bluetooth</b>. Actívala con el
            interruptor que hay arriba a la derecha, encima de las salidas.</p>
            <ul>
              <li>Solo suena <b>una</b> salida: la <b>primera de la lista</b> que esté
              disponible.</li>
              <li>Si la principal se apaga, se queda sin batería o se desconecta,
              Serch MicMix <b>pasa sola a la siguiente</b> de la lista.</li>
              <li>Cuando la principal vuelve, <b>recupera el mando</b> ella sola.</li>
              <li>Con las flechas <b>↑ ↓</b> cambias el orden: la de más arriba es
              siempre la principal. Con <b>×</b> la quitas de la lista.</li>
              <li>Un dispositivo apagado sigue en su puesto y se muestra como
              <i>No disponible</i>, listo para cuando vuelva.</li>
            </ul>
            <p style="color:{theme.TEXT_DIM}">Ejemplo típico: 1º Bocinas Bluetooth,
            2º Altavoces del monitor, 3º CABLE Input. Al encender las Bluetooth suena
            por ellas; si las apagas, el audio pasa solo a los altavoces.</p>

            <h3 style="color:{theme.ACCENT}">Consejos</h3>
            <ul>
              <li>Botones <b>Mic</b> y <b>Música</b> de cada salida: eligen qué
              fuentes suenan por ahí.</li>
              <li><b>Solo</b>: escucha únicamente ese micrófono.</li>
              <li><b>Silenciar todo</b>: corta el sonido sin apagar nada.</li>
              <li>Los dispositivos se vigilan solos: si enciendes una bocina
              Bluetooth, aparece sin que pulses nada. Si algo no sale, pulsa
              <b>Actualizar</b> o usa <b>⋮ → Reiniciar motor</b>.</li>
              <li>Las <b>acciones rápidas</b> desactivan la prioridad automática,
              porque eligen las salidas a mano.</li>
            </ul>

            <p style="color:{theme.TEXT_DIM}">Los auriculares con micrófono suelen
            aparecer dos veces: una como entrada y otra como salida. Es normal.</p>
            """
        )
        lay.addWidget(browser)
        btn = QPushButton("Entendido")
        btn.setObjectName("Primary")
        btn.clicked.connect(dlg.accept)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(btn)
        lay.addLayout(row)
        return dlg

    def _about(self) -> None:
        QMessageBox.about(
            self,
            "Acerca de Serch MicMix",
            "<b>Serch MicMix</b> — mezclador de audio sencillo para Windows.<br><br>"
            "Detecta automáticamente cualquier tarjeta de sonido, permite encender "
            "y apagar micrófonos con un toque y repartir el audio entre varias "
            "salidas a la vez.<br><br>"
            "VB-Cable es un producto gratuito de VB-Audio (vb-audio.com) que "
            "Serch MicMix puede descargar e instalar por ti.",
        )

    def _open_folder(self, path) -> None:
        import os

        try:
            os.startfile(str(path))  # noqa: S606
        except Exception:
            pass

    # --------------------------------------------------------------- presets
    def _apply_preset(self, kind: str) -> None:
        # Las acciones rapidas eligen salidas a mano, asi que se desactiva la
        # prioridad automatica para que se vea exactamente lo que hacen.
        if self.prio_toggle.isChecked():
            self.prio_toggle.setChecked(False)
            self._on_priority_toggled(False)

        cable_out = next((d for d in self.outputs if d.is_cable_endpoint), None)
        cable_in = next((d for d in self.inputs if d.is_cable_endpoint), None)
        default_out = next((d for d in self.outputs if d.is_default and not d.virtual), None)
        if default_out is None:
            default_out = next((d for d in self.outputs if not d.virtual), None)

        if kind == "mic_to_pc":
            if cable_out is None:
                self._ask_install_vb()
                return
            for dev in self.inputs:
                if not dev.virtual:
                    self.engine.set_input(dev.key, enabled=True, muted=False)
            self.engine.set_output(cable_out.key, enabled=True, muted=False)
        elif kind == "monitor":
            for dev in self.inputs:
                if not dev.virtual:
                    self.engine.set_input(dev.key, enabled=True, muted=False)
            if default_out is not None:
                self.engine.set_output(default_out.key, enabled=True, muted=False)
        elif kind == "music":
            if cable_in is None:
                self._ask_install_vb()
                return
            self.engine.set_input(cable_in.key, enabled=True, muted=False)
            if default_out is not None:
                self.engine.set_output(default_out.key, enabled=True, muted=False)
        elif kind == "all":
            for dev in self.inputs:
                self.engine.set_input(dev.key, enabled=True, muted=False)
            for dev in self.outputs:
                self.engine.set_output(dev.key, enabled=True, muted=False)
        elif kind == "stop":
            self.engine.disable_all()
        self._set_master_mute(False)

    def _ask_install_vb(self) -> None:
        res = QMessageBox.question(
            self,
            "VB-Cable necesario",
            "Esta acción necesita VB-Cable, que todavía no está instalado.\n\n"
            "¿Quieres descargarlo e instalarlo ahora?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if res == QMessageBox.Yes:
            self._install_vbcable()

    # ------------------------------------------------------------------ tick
    def _tick(self) -> None:
        self._consume_scan()
        self._consume_watch()
        snap = self.engine.snapshot()

        for key, card in self.input_cards.items():
            state = snap["inputs"].get(key)
            if state is None:
                continue
            card.set_state(
                state["enabled"],
                state["muted"],
                state["gain"],
                solo=state["solo"],
                level=state["level"],
                error=state["error"],
            )
        for key, card in self.output_cards.items():
            state = snap["outputs"].get(key)
            if state is None:
                continue
            card.set_state(
                state["enabled"],
                state["muted"],
                state["gain"],
                sources=state["sources"],
                level=state["level"],
                error=state["error"],
            )

        priority = snap.get("priority") or {}
        if priority.get("enabled"):
            active = priority.get("active")
            for key, row in self.priority_rows.items():
                state = snap["outputs"].get(key)
                if state is None:
                    row.set_status("absent", "Sin conectar — se usará cuando aparezca")
                elif key == active:
                    if state["open"]:
                        row.set_status("active", f"Sonando ahora · {state['rate']} Hz")
                    else:
                        row.set_status("connecting", state["error"] or "Abriendo la salida…")
                else:
                    row.set_status("wait", "En espera")

        stats = snap["stats"]
        rate = stats.get("master_rate") or 0
        load = stats.get("load") or 0.0

        if priority.get("enabled"):
            self.status_label.setText(self._priority_status_text(snap, priority))
            return

        if stats.get("inputs_open", 0) and not stats.get("outputs_open", 0):
            self.status_label.setText(
                "⚠  Hay entradas encendidas pero ninguna salida: activa una tarjeta "
                "de la derecha para escuchar el audio."
            )
            return
        parts = []
        if rate:
            parts.append(f"{rate} Hz")
        parts.append(f"{stats.get('inputs_open', 0)} entradas activas")
        parts.append(f"{stats.get('outputs_open', 0)} salidas activas")
        if load:
            parts.append(f"carga {load:.1f} ms/bloque")
        if stats.get("last_error"):
            parts.append("⚠ " + stats["last_error"])
        self.status_label.setText("  ·  ".join(parts))

    def _priority_status_text(self, snap: dict, priority: dict) -> str:
        active = priority.get("active")
        order = priority.get("order") or []
        if active is None:
            return (
                "⚠  Prioridad automática: ninguna salida de la lista está disponible. "
                "Enciende una bocina o añade otra salida."
            )
        row = self.priority_rows.get(active)
        name = row.title.fullText() if row is not None else active.split("::")[-1]
        position = order.index(active) + 1 if active in order else 0
        state = snap["outputs"].get(active) or {}
        head = f"Prioridad automática · salida {position} de {len(order)}"
        if position > 1:
            head += "  (la principal no está disponible)"
        detail = f"{name} · {state.get('rate', '')} Hz" if state.get("open") else f"{name} (conectando…)"
        return f"{head}  →  {detail}"

    # ---------------------------------------------------------------- cierre
    def closeEvent(self, event) -> None:  # noqa: N802
        try:
            self.config.set("window", "w", value=self.width(), save=False)
            self.config.set("window", "h", value=self.height())
        except Exception:
            pass
        try:
            self._timer.stop()
        except Exception:
            pass
        try:
            self.engine.shutdown()
        except Exception:
            pass
        super().closeEvent(event)
