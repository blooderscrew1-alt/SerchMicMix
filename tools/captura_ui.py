"""Herramienta de desarrollo: renderiza la ventana a un PNG.

Sirve para revisar el aspecto de la interfaz sin depender de una pantalla.

    python tools/captura_ui.py salida.png [--offscreen] [--acciones]

Con ``--acciones`` enciende algunos dispositivos para ver el estado "activo".
"""

from __future__ import annotations

import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

ARGS = [a for a in sys.argv[1:] if not a.startswith("--")]
FLAGS = {a for a in sys.argv[1:] if a.startswith("--")}
OUT = ARGS[0] if ARGS else os.path.join(BASE, "tools", "captura.png")

WIDTH, HEIGHT = 1240, 800
for _flag in FLAGS:
    if _flag.startswith("--w="):
        WIDTH = int(_flag.split("=", 1)[1])
    elif _flag.startswith("--h="):
        HEIGHT = int(_flag.split("=", 1)[1])

if "--offscreen" in FLAGS:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtGui import QFont, QIcon  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from audiomix import theme  # noqa: E402
from audiomix.main_window import MainWindow, make_logo  # noqa: E402


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    font = QFont()
    font.setFamilies(theme.FONT_STACK)
    font.setPointSize(10)
    app.setFont(font)
    app.setStyleSheet(theme.qss())

    window = MainWindow()
    window.setWindowIcon(QIcon(make_logo(128)))
    window.resize(WIDTH, HEIGHT)
    window.show()

    steps = []
    delay = 4200

    if "--acciones" in FLAGS:

        def enable_some() -> None:
            ins = [d for d in window.inputs if not d.virtual][:1]
            outs = [d for d in window.outputs if not d.virtual][:2]
            for d in ins:
                window._on_card_toggle(d.key, True)
            for d in outs:
                window._on_card_toggle(d.key, True)
            if ins:
                card = window.input_cards.get(ins[0].key)
                if card:
                    card.slider.setValue(85)
                    card.set_state(True, False, 0.85, level=0.62)
            if outs:
                card = window.output_cards.get(outs[0].key)
                if card:
                    card.set_state(True, False, 1.0, level=0.74)

        steps.append((3200, enable_some))
        delay = 5200

    if "--prioridad" in FLAGS:

        def enable_priority() -> None:
            window.prio_toggle.setChecked(True)
            window._on_priority_toggled(True)
            if len(window.priority_rows) > 1:
                # Se baja la principal un puesto para que se vea el estado
                # "en espera" en la primera fila y la activa en la segunda.
                window._priority_remove(list(window.priority_rows)[0])

        steps.append((3400, enable_priority))
        delay = 6200

    def capture() -> None:
        for _ in range(6):
            app.processEvents()
        pixmap = window.grab()
        os.makedirs(os.path.dirname(os.path.abspath(OUT)), exist_ok=True)
        ok = pixmap.save(OUT)
        print(f"captura: {OUT} -> {'OK' if ok else 'ERROR'} ({pixmap.width()}x{pixmap.height()})")
        app.quit()

    steps.append((delay, capture))
    for when, fn in steps:
        QTimer.singleShot(when, fn)

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
