"""Prueba de humo de la interfaz: recorre todos los caminos interactivos.

No necesita pantalla (usa el plugin "offscreen") y no instala nada.

    python tools\\humo_ui.py
"""

from __future__ import annotations

import os
import sys
import time
import traceback

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QFont  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from audiomix import theme  # noqa: E402
from audiomix.install_dialog import InstallDialog  # noqa: E402
from audiomix.main_window import MainWindow  # noqa: E402

PROBLEMS: list[str] = []


def step(name: str, fn) -> None:
    try:
        fn()
        print(f"[OK  ] {name}")
    except Exception as exc:  # noqa: BLE001
        print(f"[FALLA] {name}: {type(exc).__name__}: {exc}")
        traceback.print_exc()
        PROBLEMS.append(name)


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    font = QFont()
    font.setFamilies(theme.FONT_STACK)
    app.setFont(font)
    app.setStyleSheet(theme.qss())

    def pump(ms: int) -> None:
        end = time.time() + ms / 1000.0
        while time.time() < end:
            app.processEvents()
            time.sleep(0.008)

    window = MainWindow()
    window.resize(1200, 760)
    window.show()
    pump(3500)

    print(f"       entradas detectadas: {len(window.inputs)}")
    print(f"       salidas detectadas:  {len(window.outputs)}")
    print(f"       VB-Cable instalado:  {window.vb_status.installed}")

    step("hay tarjetas creadas", lambda: (
        _assert(bool(window.inputs) and bool(window.output_cards) and bool(window.input_cards),
                "no se crearon tarjetas")))

    if not window.inputs or not window.outputs:
        print("[SALTA] el resto de pruebas necesita dispositivos de audio")
        return 1 if PROBLEMS else 0

    ikey = window.inputs[0].key
    okey = window.outputs[0].key

    def toggle_input():
        window._on_card_toggle(ikey, True)
        pump(700)
        snap = window.engine.snapshot()
        _assert(snap["inputs"][ikey]["enabled"], "la entrada no se activo")
        _assert(snap["inputs"][ikey]["open"], "el stream de entrada no se abrio: "
                + str(snap["inputs"][ikey]["error"]))
        window._on_card_toggle(ikey, False)
        pump(600)
        _assert(not window.engine.snapshot()["inputs"][ikey]["enabled"], "la entrada no se apago")

    step("encender/apagar una entrada (clic en la tarjeta)", toggle_input)

    def toggle_output():
        window._on_card_toggle(okey, True)
        pump(900)
        snap = window.engine.snapshot()
        _assert(snap["outputs"][okey]["open"], "el stream de salida no se abrio: "
                + str(snap["outputs"][okey]["error"]))
        window._on_card_toggle(okey, False)
        pump(600)
        _assert(not window.engine.snapshot()["outputs"][okey]["enabled"], "la salida no se apago")

    step("encender/apagar una salida", toggle_output)

    step("mover el volumen de una tarjeta", lambda: (
        window._on_card_gain(ikey, 0.5), pump(150),
        _assert(abs(window.engine.snapshot()["inputs"][ikey]["gain"] - 0.5) < 1e-6, "ganancia no aplicada"),
        window._on_card_gain(ikey, 1.0), pump(150)))

    step("boton Solo", lambda: (
        window._on_card_solo(ikey, True), pump(120),
        _assert(window.engine.snapshot()["inputs"][ikey]["solo"], "solo no activado"),
        window._on_card_solo(ikey, False), pump(120)))

    step("filtros Mic/Musica de la salida", lambda: (
        window._on_card_source(okey, "music", False), pump(120),
        _assert(window.engine.snapshot()["outputs"][okey]["sources"]["music"] is False, "filtro no aplicado"),
        window._on_card_source(okey, "music", True), pump(120)))

    # En esta prueba no queremos dialogos modales: simulamos la respuesta y
    # comprobamos aparte que la peticion se hace cuando falta VB-Cable.
    asked: list[bool] = []
    window._ask_install_vb = lambda: asked.append(True)  # type: ignore[method-assign]

    for preset in ("monitor", "music", "mic_to_pc", "all", "stop"):
        step(f"accion rapida «{preset}»", lambda p=preset: (window._apply_preset(p), pump(400)))

    if not window.vb_status.installed:
        step("las acciones que necesitan el cable avisan al usuario", lambda: _assert(
            len(asked) >= 2, f"solo se pidio instalar {len(asked)} veces"))

    step("silenciar todo / quitar silencio", lambda: (
        window.mute_btn.setChecked(True), window._toggle_master_mute(), pump(400),
        window.mute_btn.setChecked(False), window._toggle_master_mute(), pump(400)))

    step("mezcla maestra", lambda: (
        window.master_slider.setValue(60), pump(200),
        _assert(abs(window.engine.master_gain - 0.6) < 1e-6, "mezcla maestra no aplicada"),
        window.master_slider.setValue(90), pump(120)))

    step("volver a buscar dispositivos", lambda: (window._start_scan(hard=False), pump(3000)))

    step("reiniciar el motor de audio", lambda: (window._hard_refresh(), pump(3500)))

    # ---------------------------------------------------------- prioridad
    step("activar la prioridad automatica", lambda: (
        window.prio_toggle.setChecked(True), window._on_priority_toggled(True), pump(1200),
        _assert(window.engine.priority_mode, "el motor no activo el modo prioridad"),
        _assert(window.priority_page.isVisible() and not window.outputs_page.isVisible(),
                "no se cambio a la vista de prioridad"),
        _assert(len(window.priority_rows) == len(window.outputs), 
                f"filas={len(window.priority_rows)} salidas={len(window.outputs)}")))

    def check_primary_is_first():
        keys = list(window.priority_rows)
        _assert(bool(keys), "sin filas")
        _wait(lambda: window.engine.priority_state()["active"] == keys[0], 12.0)
        active = window.engine.priority_state()["active"]
        _assert(active == keys[0], f"activa={active} primera={keys[0]}")

    step("la principal es la primera de la lista y suena", check_primary_is_first)

    def move_second_up():
        keys = list(window.priority_rows)
        if len(keys) < 2:
            return
        first, second = keys[0], keys[1]
        window._priority_move(second, -1)
        pump(700)
        new_order = list(window.priority_rows)
        _assert(new_order[0] == second and new_order[1] == first, f"orden={new_order}")
        _wait(lambda: window.engine.priority_state()["active"] == second, 12.0)

    step("subir la segunda al primer puesto (pasa a ser principal)", move_second_up)

    step("bajarla otra vez", lambda: (
        keys := list(window.priority_rows),
        window._priority_move(keys[0], 1), pump(500),
        _assert(list(window.priority_rows)[0] != keys[0] or len(keys) == 1, "no se movio")))

    step("quitar una salida de la lista", lambda: (
        n := len(window.priority_rows),
        window._priority_remove(list(window.priority_rows)[-1]) if n > 1 else None,
        pump(400),
        _assert(len(window.priority_rows) == max(1, n - 1), "no se quito")))

    step("volver a anadir todas las salidas", lambda: (
        window._priority_add_all(), pump(400),
        _assert(len(window.priority_rows) == len(window.outputs), "no se anadieron todas")))

    step("el vigilante de dispositivos no rompe nada", lambda: (window._watch_devices(), pump(2000)))

    step("desactivar la prioridad automatica", lambda: (
        window.prio_toggle.setChecked(False), window._on_priority_toggled(False), pump(600),
        _assert(not window.engine.priority_mode, "el motor sigue en modo prioridad"),
        _assert(window.outputs_page.isVisible() and not window.priority_page.isVisible(),
                "no se volvio a la vista normal")))

    step("dialogo de ayuda", lambda: (_assert(window._make_help_dialog() is not None, "sin dialogo"),))

    step("dialogo de instalacion (sin arrancar)", lambda: (
        InstallDialog(window, auto_start=False).close(),))

    step("las tarjetas siguen respondiendo tras el reinicio", lambda: (
        window._on_card_toggle(window.inputs[0].key, True), pump(800),
        window._on_card_toggle(window.inputs[0].key, False), pump(300)))

    window.close()
    pump(400)

    print("-" * 60)
    if PROBLEMS:
        print(f"PROBLEMAS: {len(PROBLEMS)} -> {', '.join(PROBLEMS)}")
        return 1
    print("PRUEBA DE HUMO DE LA INTERFAZ: TODO CORRECTO")
    return 0


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _wait(predicate, timeout: float = 8.0, step: float = 0.2) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if predicate():
                return True
        except Exception:
            pass
        time.sleep(step)
    return False


if __name__ == "__main__":
    sys.exit(main())
