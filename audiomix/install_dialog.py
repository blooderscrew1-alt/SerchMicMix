"""Dialogo de descarga e instalacion de VB-Cable."""

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from . import theme, vbcable

STEPS = [
    ("buscar", "Buscar la ultima version en vb-audio.com"),
    ("descargar", "Descargar el paquete oficial"),
    ("extraer", "Descomprimir los archivos"),
    ("instalar", "Instalar el controlador (permisos de administrador)"),
    ("verificar", "Comprobar que Windows detecta el cable"),
]


class InstallDialog(QDialog):
    """Guiado paso a paso, con hilo aparte para no congelar la ventana."""

    def __init__(self, parent=None, auto_start: bool = True) -> None:
        super().__init__(parent)
        self.setWindowTitle("Instalar VB-Cable")
        self.setModal(True)
        self.setMinimumWidth(560)
        self.setStyleSheet(theme.qss())

        self.step_labels: dict[str, QLabel] = {}
        self._state: dict = {"status": "idle", "message": "", "step": "", "result": None}
        self._lock = threading.Lock()
        self.finished_ok = False

        self._build()
        self._timer = QTimer(self)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._poll)
        if auto_start:
            self._timer.start()
            self._thread = threading.Thread(target=self._worker, daemon=True)
            self._thread.start()
        else:
            self._thread = None

    # ------------------------------------------------------------------ UI
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 20)
        root.setSpacing(14)

        title = QLabel("Instalando el cable de audio virtual")
        title.setObjectName("AppTitle")
        root.addWidget(title)

        subtitle = QLabel(
            "AudioMix descargara VB-Cable desde la web oficial de VB-Audio y lo "
            "instalara en este equipo. Es un controlador gratuito de VB-Audio; "
            "Windows pedira permiso de administrador."
        )
        subtitle.setWordWrap(True)
        subtitle.setObjectName("Subtle")
        root.addWidget(subtitle)

        for key, text in STEPS:
            row = QLabel(f"○  {text}")
            row.setObjectName("Subtle")
            self.step_labels[key] = row
            root.addWidget(row)

        self.bar = QProgressBar()
        self.bar.setRange(0, 0)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(8)
        root.addWidget(self.bar)

        self.status = QLabel("Preparando...")
        self.status.setWordWrap(True)
        self.status.setObjectName("Micro")
        root.addWidget(self.status)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.page_btn = QPushButton("Abrir pagina oficial")
        self.page_btn.clicked.connect(vbcable.open_page)
        buttons.addWidget(self.page_btn)

        self.manual_btn = QPushButton("Instalador oficial")
        self.manual_btn.setToolTip("Abre el instalador de VB-Audio por si el modo automatico no basta")
        self.manual_btn.clicked.connect(self._open_manual)
        self.manual_btn.setEnabled(False)
        buttons.addWidget(self.manual_btn)

        self.close_btn = QPushButton("Cerrar")
        self.close_btn.setObjectName("Primary")
        self.close_btn.clicked.connect(self.accept)
        buttons.addWidget(self.close_btn)
        root.addLayout(buttons)

    # -------------------------------------------------------------- estado
    def _mark(self, key: str, state: str) -> None:
        icons = {"run": "◐", "ok": "●", "err": "●", "idle": "○"}
        colors = {"run": theme.ACCENT, "ok": theme.SUCCESS, "err": theme.DANGER, "idle": theme.TEXT_MUTE}
        label = self.step_labels.get(key)
        if not label:
            return
        text = label.text().split("  ", 1)[-1]
        label.setText(f"{icons.get(state, '○')}  {text}")
        label.setStyleSheet(f"color: {colors.get(state, theme.TEXT_DIM)}; font-size: 12px;")

    def _set_step(self, step: str, state: str) -> None:
        order = [key for key, _text in STEPS]
        if step not in order:
            return
        idx = order.index(step)
        for i, key in enumerate(order):
            if i < idx:
                self._mark(key, "ok")
            elif i == idx:
                self._mark(key, state)

    # ------------------------------------------------------------- worker
    def _worker(self) -> None:
        def progress(msg: str) -> None:
            with self._lock:
                self._state["message"] = msg
                low = msg.lower()
                if "buscando" in low:
                    step = "buscar"
                elif "descargando" in low:
                    step = "descargar"
                elif "descomprim" in low:
                    step = "extraer"
                elif "instalando" in low or "permiso" in low:
                    step = "instalar"
                else:
                    step = "verificar"
                self._state["step"] = step

        try:
            res = vbcable.run_full_install(progress=progress)
        except Exception as exc:
            res = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

        with self._lock:
            self._state["status"] = "done"
            self._state["result"] = res
            self._state["step"] = "verificar"

    def _poll(self) -> None:
        with self._lock:
            status = self._state["status"]
            message = self._state["message"]
            step = self._state["step"]

        if message:
            self.status.setText(message)
        if step and self._state.get("status") != "done":
            self._set_step(step, "run")

        if status != "done":
            return

        self._timer.stop()
        result = self._state.get("result") or {}
        self.status.setText("Comprobando que Windows detecta el cable virtual...")
        self._mark("verificar", "run")
        self.bar.setRange(0, 1)
        self.bar.setValue(1)
        self.manual_btn.setEnabled(True)

        # Verificar con espera (bloquea poco: pocos segundos).
        status_vb = vbcable.wait_for_endpoints(timeout=20.0)
        if status_vb.installed:
            self._mark("verificar", "ok")
            self.finished_ok = True
            self.status.setStyleSheet(f"color: {theme.SUCCESS}; font-size: 12px;")
            self.status.setText(
                "Listo. VB-Cable esta instalado y funcionando.\n"
                f"Salida virtual: {status_vb.render_name}\n"
                f"Entrada virtual: {status_vb.capture_name}"
            )
        else:
            self._mark("verificar", "err")
            detail = result.get("error") or result.get("message") or status_vb.detail
            self.manual_btn.setEnabled(True)
            self.status.setStyleSheet(f"color: {theme.WARNING}; font-size: 12px;")
            self.status.setText(
                "La instalacion automatica no ha terminado de registrar el cable.\n\n"
                "Pulsa 'Instalador oficial': se abrira la ventana de VB-Audio y solo "
                "tienes que pulsar el boton 'Install Driver'. Despues cierra esta "
                "ventana y usa 'Volver a detectar' en AudioMix.\n\n"
                f"Detalle: {detail}"
            )

    def _open_manual(self) -> None:
        folder = vbcable.install_dir()
        res = vbcable.launch_official_setup(folder)
        if not res.get("ok"):
            self.status.setText(res.get("error", "No se pudo abrir el instalador."))
        else:
            self.status.setStyleSheet(f"color: {theme.INFO}; font-size: 12px;")
            self.status.setText(res.get("message", ""))

    def closeEvent(self, event) -> None:  # noqa: N802
        self._timer.stop()
        super().closeEvent(event)
