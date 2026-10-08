"""Arranque automatico con Windows.

Se usa la clave ``Run`` del usuario actual (``HKCU``), que **no necesita
permisos de administrador** y solo afecta a este usuario.

El comando apunta directamente a ``pythonw.exe`` (no a ``run.bat``) por dos
motivos:

* ``run.bat`` abriria una ventana de consola negra al iniciar sesion.
* ``pythonw.exe`` es el interprete sin consola, que es justo lo que quiere una
  aplicacion que arranca sola y vive en la bandeja del sistema.

El proceso se registra con ``--tray`` para que aparezca directamente
minimizado en la bandeja, sin molestar al iniciar sesion.
"""

from __future__ import annotations

import sys
from pathlib import Path

NOMBRE_VALOR = "SerchMicMix"
CLAVE_RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _winreg():
    try:
        import winreg  # noqa: PLC0415

        return winreg
    except ImportError:
        return None


def ruta_pythonw() -> str | None:
    """Interprete sin consola que corresponde a este proceso, si existe."""
    ejecutable = Path(sys.executable)
    candidatos = [ejecutable.with_name("pythonw.exe"), ejecutable]
    for candidato in candidatos:
        try:
            if candidato.is_file():
                return str(candidato)
        except OSError:
            continue
    return None


def ruta_main() -> str | None:
    """Ruta de main.py (la aplicacion no se empaqueta como .exe)."""
    raiz = Path(__file__).resolve().parent.parent
    principal = raiz / "main.py"
    try:
        if principal.is_file():
            return str(principal)
    except OSError:
        pass
    return None


def comando() -> str | None:
    """Comando completo que se escribe en el registro."""
    interprete = ruta_pythonw()
    principal = ruta_main()
    if not interprete or not principal:
        return None
    return f'"{interprete}" "{principal}" --tray'


def esta_activo() -> bool:
    winreg = _winreg()
    if winreg is None:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, CLAVE_RUN) as clave:
            valor, _tipo = winreg.QueryValueEx(clave, NOMBRE_VALOR)
            return bool(str(valor).strip())
    except OSError:
        return False


def valor_actual() -> str:
    winreg = _winreg()
    if winreg is None:
        return ""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, CLAVE_RUN) as clave:
            return str(winreg.QueryValueEx(clave, NOMBRE_VALOR)[0])
    except OSError:
        return ""


def activar() -> tuple[bool, str]:
    """Registra el arranque automatico. Devuelve (ok, mensaje)."""
    winreg = _winreg()
    if winreg is None:
        return False, "Solo disponible en Windows."
    linea = comando()
    if not linea:
        return False, "No se pudo determinar la ruta de main.py o de pythonw.exe."
    try:
        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER, CLAVE_RUN, 0, winreg.KEY_SET_VALUE
        ) as clave:
            winreg.SetValueEx(clave, NOMBRE_VALOR, 0, winreg.REG_SZ, linea)
    except OSError as exc:
        return False, f"No se pudo escribir en el registro: {exc}"
    return True, linea


def desactivar() -> tuple[bool, str]:
    """Quita el arranque automatico. Devuelve (ok, mensaje)."""
    winreg = _winreg()
    if winreg is None:
        return False, "Solo disponible en Windows."
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, CLAVE_RUN, 0, winreg.KEY_SET_VALUE
        ) as clave:
            winreg.DeleteValue(clave, NOMBRE_VALOR)
    except FileNotFoundError:
        return True, "Ya estaba desactivado."
    except OSError as exc:
        return False, f"No se pudo modificar el registro: {exc}"
    return True, ""


def establecer(activado: bool) -> tuple[bool, str]:
    return activar() if activado else desactivar()
