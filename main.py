"""Punto de entrada de serchmicmix.

Uso:
    python main.py            (o run.bat)

Antes de abrir la ventana se comprueba que las tres dependencias se pueden
importar de verdad. Si alguna falla, en vez de un volcado de Python se muestra
un mensaje que explica que hacer (lo habitual en un PC recien preparado es que
numpy no cargue sus DLL por falta del redistribuible de Visual C++).
"""

from __future__ import annotations

import faulthandler
import os
import sys
import traceback

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

DEPENDENCIAS = (
    ("PySide6", "la interfaz grafica"),
    ("sounddevice", "el acceso a las tarjetas de sonido"),
    ("numpy", "el procesado de audio"),
)

VC_REDIST_URL = "https://aka.ms/vs/17/release/vc_redist.x64.exe"


def _prepare_logging():
    """Deja un registro de errores en %APPDATA%\\SerchMicMix\\error.log."""
    try:
        from serchmicmix.config import log_path

        path = log_path()
        handle = open(path, "a", encoding="utf-8")
        faulthandler.enable(handle)
        return handle
    except Exception:
        return None


def _guardar(log_handle, texto: str) -> None:
    try:
        if log_handle:
            log_handle.write("\n" + texto)
            log_handle.flush()
    except Exception:
        pass
    try:
        sys.stderr.write(texto)
    except Exception:
        pass


def _install_excepthook(log_handle):
    def hook(exc_type, exc, tb):
        texto = "".join(traceback.format_exception(exc_type, exc, tb))
        _guardar(log_handle, texto)
        _avisar(
            "Serch MicMix — error inesperado",
            "Ha ocurrido un error inesperado.\n\n"
            f"{exc_type.__name__}: {exc}\n\n"
            "El detalle se guardó en la carpeta de configuración de serchmicmix.\n"
            "Puedes verla con «⋮ → Abrir carpeta de configuración».",
        )

    sys.excepthook = hook


def _avisar(titulo: str, mensaje: str) -> None:
    """Muestra un aviso por Qt si se puede y, si no, por Windows."""
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox

        app = QApplication.instance()
        propia = app is None
        if propia:
            app = QApplication(sys.argv)
        caja = QMessageBox()
        caja.setIcon(QMessageBox.Critical)
        caja.setWindowTitle(titulo)
        caja.setText(mensaje)
        caja.exec()
        if propia:
            app.quit()
        return
    except Exception:
        pass
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, mensaje, titulo, 0x10)
    except Exception:
        pass


def _comprobar_dependencias() -> list[tuple[str, str, str]]:
    """Devuelve [(modulo, para_que_sirve, error)] de las que no se importan."""
    problemas = []
    for modulo, para in DEPENDENCIAS:
        try:
            __import__(modulo)
        except BaseException as exc:  # noqa: BLE001
            problemas.append((modulo, para, f"{type(exc).__name__}: {exc}"))
    return problemas


def _mensaje_dependencias(problemas: list[tuple[str, str, str]]) -> str:
    lineas = ["Serch MicMix no puede arrancar porque falta un componente de Python.", ""]
    for modulo, para, error in problemas:
        lineas.append(f"  · {modulo}  ({para})")
        lineas.append(f"      {error}")
    lineas.append("")
    lineas.append("Qué hacer:")
    lineas.append("  1. Cierra esta ventana.")
    lineas.append("  2. Ejecuta REPARAR.bat, que está junto a run.bat.")
    lineas.append("     Comprueba qué falla, lo reinstala y, si hace falta, instala")
    lineas.append("     el redistribuible de Microsoft Visual C++.")
    lineas.append("  3. Si sigue sin funcionar, ejecuta DIAGNOSTICO.bat y guarda")
    lineas.append("     el informe que genera.")

    if any(m == "numpy" for m, _p, _e in problemas):
        lineas.append("")
        lineas.append("El error «DLL load failed while importing _multiarray_umath»")
        lineas.append("tiene dos causas posibles:")
        lineas.append("  · Que falte el redistribuible de Visual C++ 2015-2022:")
        lineas.append(f"      {VC_REDIST_URL}")
        lineas.append("  · O que el procesador sea anterior a SSE4.2 (AMD Phenom /")
        lineas.append("    Athlon II, Intel anteriores a Nehalem). numpy 2.x exige")
        lineas.append("    SSE4.2; en ese equipo hace falta Python 3.12 con numpy 1.26.")
        lineas.append("")
        lineas.append("REPARAR.bat distingue los dos casos y lo arregla solo.")

    lineas.append("")
    lineas.append(f"Carpeta del programa:\n  {BASE_DIR}")
    return "\n".join(lineas)


def main() -> int:
    log_handle = _prepare_logging()
    _install_excepthook(log_handle)

    problemas = _comprobar_dependencias()
    if problemas:
        texto = _mensaje_dependencias(problemas)
        _guardar(log_handle, "=== Dependencias que fallan ===\n")
        for modulo, _para, error in problemas:
            _guardar(log_handle, f"{modulo}: {error}\n")
        _avisar("Serch MicMix — falta un componente", texto)
        return 3

    from PySide6.QtCore import Qt  # noqa: F401
    from PySide6.QtGui import QFont, QIcon
    from PySide6.QtWidgets import QApplication

    from serchmicmix import APP_NAME, APP_VERSION, theme

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName(APP_NAME)
    app.setStyle("Fusion")

    fuente = QFont()
    fuente.setFamilies(theme.FONT_STACK)
    fuente.setPointSize(10)
    app.setFont(fuente)
    app.setStyleSheet(theme.qss())

    from serchmicmix.main_window import MainWindow, make_logo

    ventana = MainWindow()
    ventana.setWindowIcon(QIcon(make_logo(128)))
    ventana.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
