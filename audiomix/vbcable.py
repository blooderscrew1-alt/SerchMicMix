"""Integracion con el controlador VB-Cable (VB-Audio).

Responsabilidades:

1. **Detectar** si el cable virtual esta instalado, sin depender del idioma ni
   del nombre exacto del dispositivo.
2. **Descargar** el paquete oficial desde vb-audio.com eligiendo siempre la
   version mas reciente publicada (con URLs de respaldo si la pagina cambia).
3. **Instalar** el controlador elevando privilegios (UAC). Se intenta primero
   una instalacion silenciosa con ``pnputil`` y, si no basta, se lanza el
   instalador oficial de VB-Audio.

Nada de esto es obligatorio para usar AudioMix: sin VB-Cable la aplicacion
sigue funcionando como mezclador normal entre microfonos y altavoces.
"""

from __future__ import annotations

import ctypes
import json
import os
import platform
import re
import shutil
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
import zipfile
from dataclasses import dataclass
from pathlib import Path

from . import devices as dev_mod
from .config import config_dir

PAGE_URL = "https://vb-audio.com/Cable/index.htm"
DOWNLOAD_HOST = "https://download.vb-audio.com/Download_CABLE/"
KNOWN_PACKS = [
    "VBCABLE_Driver_Pack45.zip",
    "VBCABLE_Driver_Pack43.zip",
]
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

_PACK_RE = re.compile(r"(VBCABLE_Driver_Pack(\d+)\.zip)", re.I)


# --------------------------------------------------------------------------
# Estado
# --------------------------------------------------------------------------
@dataclass
class VBStatus:
    installed: bool
    render_name: str = ""
    capture_name: str = ""
    detail: str = ""


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def architecture() -> str:
    """'ARM64', 'AMD64' o 'X86'."""
    machine = (platform.machine() or "").upper()
    env = (os.environ.get("PROCESSOR_ARCHITECTURE") or "").upper()
    arch = machine or env
    if "ARM" in arch:
        return "ARM64"
    if "64" in arch or arch in ("AMD64", "X64"):
        return "AMD64"
    return "X86"


def windows_build() -> int:
    try:
        v = sys.getwindowsversion()
        return int(getattr(v, "build", 0) or 0)
    except Exception:
        return 0


def detect(outputs=None, inputs=None) -> VBStatus:
    """Detecta el cable virtual a partir de los dispositivos de audio actuales."""
    if outputs is None or inputs is None:
        try:
            outs, ins = dev_mod.build_registry(show_all=True)
        except Exception:
            outs, ins = [], []
    else:
        outs, ins = outputs, inputs

    eps = dev_mod.find_virtual_endpoints(outs, ins)
    render = eps.get("render")
    capture = eps.get("capture")

    driver_files = _driver_file_present()
    if eps.get("installed"):
        return VBStatus(
            installed=True,
            render_name=getattr(render, "name", ""),
            capture_name=getattr(capture, "name", ""),
            detail="Controlador activo y endpoints de audio detectados.",
        )
    if driver_files:
        return VBStatus(
            installed=False,
            detail="Hay archivos del controlador pero Windows todavia no expone "
            "los dispositivos. Reinicia el equipo o vuelve a conectar el audio.",
        )
    if render or capture:
        return VBStatus(
            installed=False,
            render_name=getattr(render, "name", ""),
            capture_name=getattr(capture, "name", ""),
            detail="Se detecto un cable virtual parcialmente instalado.",
        )
    return VBStatus(installed=False, detail="No se detecto ningun cable virtual.")


def _driver_file_present() -> bool:
    windir = os.environ.get("WINDIR", r"C:\Windows")
    drivers = Path(windir) / "System32" / "drivers"
    try:
        for item in drivers.glob("vbaudio_cable*.sys"):
            return True
    except Exception:
        pass
    return False


# --------------------------------------------------------------------------
# Red
# --------------------------------------------------------------------------
def _urlopen(url: str, timeout: float = 30.0):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    except ssl.SSLError:
        # Equipos antiguos sin TLS moderno: se reintenta sin validar el
        # certificado para no dejar al usuario sin opcion automatica.
        ctx = ssl._create_unverified_context()  # noqa: S323
        return urllib.request.urlopen(req, timeout=timeout, context=ctx)


def fetch_latest_pack(timeout: float = 25.0) -> tuple[str, str]:
    """Devuelve (url, nombre_archivo) del paquete mas reciente publicado."""
    try:
        with _urlopen(PAGE_URL, timeout) as resp:
            html = resp.read().decode("utf-8", "replace")
        best: tuple[int, str] | None = None
        for name, ver in _PACK_RE.findall(html):
            try:
                n = int(ver)
            except ValueError:
                continue
            if best is None or n > best[0]:
                best = (n, name)
        if best is not None:
            return DOWNLOAD_HOST + best[1], best[1]
    except Exception:
        pass
    # Respaldos conocidos, del mas nuevo al mas antiguo.
    return DOWNLOAD_HOST + KNOWN_PACKS[0], KNOWN_PACKS[0]


def download(url: str, dest: Path, progress=None, cancel=None) -> Path:
    """Descarga ``url`` en ``dest`` informando del progreso."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with _urlopen(url, timeout=60.0) as resp:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        with open(tmp, "wb") as fh:
            while True:
                if cancel is not None and cancel():
                    raise RuntimeError("Descarga cancelada por el usuario.")
                chunk = resp.read(65536)
                if not chunk:
                    break
                fh.write(chunk)
                done += len(chunk)
                if progress is not None:
                    progress(done, total)
    if dest.exists():
        dest.unlink()
    os.replace(tmp, dest)
    return dest


def install_dir() -> Path:
    """Carpeta donde se descomprime el paquete de VB-Cable.

    Se usa la carpeta local del usuario y, si no se puede escribir (perfiles
    restringidos), la carpeta temporal del sistema.
    """
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or ""
    if base:
        path = Path(base) / "AudioMix" / "vbcable"
        try:
            path.mkdir(parents=True, exist_ok=True)
            return path
        except OSError:
            pass
    fallback = Path(config_dir()) / "vbcable"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def extract(zip_path: Path, target: Path) -> Path:
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.namelist():
            # Proteccion contra rutas maliciosas dentro del zip.
            name = member.replace("\\", "/")
            if name.startswith("/") or ".." in name.split("/"):
                continue
            zf.extract(member, target)
    return target


def pick_inf(folder: Path) -> Path | None:
    """Elige el .inf adecuado para esta version de Windows y arquitectura."""
    build = windows_build()
    arch = architecture()
    candidates: list[str] = []
    if arch == "ARM64":
        candidates += ["vbMmeCable64_win10.inf", "vbMmeCable64_win7.inf"]
    if build >= 10240:  # Windows 10 / 11
        candidates += ["vbMmeCable64_win10.inf", "vbMmeCable_win10.inf"]
    if build >= 7600:  # Windows 7 / 8 / 8.1
        candidates += ["vbMmeCable64_win7.inf", "vbMmeCable_win7.inf"]
    candidates += ["vbMmeCable64_vista.inf", "vbMmeCable64_2003.inf"]
    for name in candidates:
        p = folder / name
        if p.exists():
            return p
    for p in sorted(folder.glob("*.inf")):
        return p
    return None


def pick_setup(folder: Path) -> Path | None:
    """Localiza el instalador oficial adecuado a la arquitectura."""
    arch = architecture()
    order = ["VBCABLE_Setup_x64.exe", "VBCABLE_Setup.exe"] if arch != "X86" else [
        "VBCABLE_Setup.exe",
        "VBCABLE_Setup_x64.exe",
    ]
    for name in order:
        p = folder / name
        if p.exists():
            return p
    for p in sorted(folder.glob("*Setup*.exe")):
        return p
    return None


# --------------------------------------------------------------------------
# Instalacion con elevacion
# --------------------------------------------------------------------------
def _run_elevated_ps(script: str, result_file: Path, timeout: float = 240.0) -> dict | None:
    """Ejecuta un script de PowerShell como administrador y espera su resultado.

    El proceso elevado deja el resultado en ``result_file`` (JSON). Si el
    usuario cancela el UAC, no aparece el archivo y se devuelve ``None``.
    """
    try:
        if result_file.exists():
            result_file.unlink()
    except Exception:
        pass
    script_file = result_file.with_suffix(".ps1")
    script_file.write_text(script, encoding="utf-8-sig")

    params = f'-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{script_file}"'
    try:
        rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", "powershell.exe", params, None, 1)
    except Exception:
        return {"ok": False, "error": "No se pudo solicitar permisos de administrador."}
    if int(rc) <= 32:
        return {"ok": False, "error": "Permisos de administrador denegados o cancelados."}

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if result_file.exists():
            try:
                return json.loads(result_file.read_text(encoding="utf-8-sig"))
            except Exception:
                time.sleep(0.4)
                continue
        time.sleep(0.4)
    return {"ok": False, "error": "La instalacion tardo demasiado o se cancelo."}


def pnputil_script(inf: Path, result_file: Path) -> str:
    """Script de PowerShell que instala el .inf y deja el resultado en JSON.

    Se genera aparte para poder validar su sintaxis en las pruebas.
    """
    return f"""
$ErrorActionPreference = 'Continue'
$out = @{{ ok = $false; code = -1; error = ''; log = '' }}
try {{
    $log = (& pnputil.exe /add-driver "{inf}" /install 2>&1 | Out-String)
    $out.code = $LASTEXITCODE
    $out.log = $log
    $out.ok = ($LASTEXITCODE -eq 0)
    if (-not $out.ok) {{ $out.error = $log.Trim() }}
}} catch {{
    $out.error = $_.Exception.Message
}}
$out | ConvertTo-Json -Compress | Set-Content -Encoding UTF8 "{result_file}"
"""


def install_driver_silent(folder: Path, progress=None) -> dict:
    """Instala el controlador con pnputil (sin ventanas, salvo el UAC)."""
    inf = pick_inf(folder)
    if inf is None:
        return {"ok": False, "error": "No se encontro el archivo .inf del controlador."}
    result_file = config_dir() / "install_result.json"
    if progress:
        progress("Solicitando permisos de administrador...")
    res = _run_elevated_ps(pnputil_script(inf, result_file), result_file)
    if res is None:
        return {"ok": False, "error": "Operacion cancelada."}
    return res


def launch_official_setup(folder: Path, progress=None) -> dict:
    """Abre el instalador oficial de VB-Audio con permisos elevados."""
    setup = pick_setup(folder)
    if setup is None:
        return {"ok": False, "error": "No se encontro el instalador de VB-Cable."}
    if progress:
        progress("Abriendo el instalador oficial de VB-Audio...")
    try:
        rc = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", str(setup), "", str(folder), 1
        )
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    if int(rc) <= 32:
        return {"ok": False, "error": "Permisos de administrador denegados o cancelados."}
    return {
        "ok": True,
        "gui": True,
        "error": "",
        "message": (
            "Se abrio el instalador de VB-Audio.\n\n"
            "Pulsa el boton 'Install Driver' en esa ventana y espera a que termine.\n"
            "Despues vuelve a AudioMix y pulsa 'Volver a detectar'."
        ),
    }


def open_page() -> None:
    try:
        webbrowser.open(PAGE_URL)
    except Exception:
        pass


def open_folder(folder: Path) -> None:
    try:
        os.startfile(str(folder))  # noqa: S606
    except Exception:
        pass


def wait_for_endpoints(timeout: float = 25.0, step: float = 2.0) -> VBStatus:
    """Espera a que Windows exponga los endpoints del cable tras instalar."""
    deadline = time.monotonic() + timeout
    status = detect()
    while time.monotonic() < deadline:
        if status.installed:
            return status
        time.sleep(step)
        try:
            dev_mod.refresh_portaudio()
        except Exception:
            pass
        status = detect()
    return status


def run_full_install(progress=None, cancel=None) -> dict:
    """Descarga + extrae + instala. Devuelve un dict con el resultado."""
    def report(msg: str) -> None:
        if progress:
            progress(msg)

    report("Buscando la ultima version en vb-audio.com...")
    url, name = fetch_latest_pack()
    folder = install_dir()
    zip_path = folder / name
    report(f"Descargando {name}...")
    try:
        download(url, zip_path, progress=lambda d, t: None, cancel=cancel)
    except Exception as exc:
        return {"ok": False, "error": f"No se pudo descargar: {type(exc).__name__}: {exc}", "url": url}

    report("Descomprimiendo el paquete...")
    try:
        extract(zip_path, folder)
    except Exception as exc:
        return {"ok": False, "error": f"No se pudo descomprimir: {exc}", "url": url}

    report("Instalando el controlador (puede aparecer una ventana de Windows)...")
    res = install_driver_silent(folder, progress=report)
    res["url"] = url
    res["folder"] = str(folder)
    return res


def uninstall_hint() -> str:
    return (
        "Para desinstalar VB-Cable: Panel de control > Programas > "
        "'VB-Audio Virtual Cable' > Desinstalar, o ejecuta VBCABLE_Setup_x64.exe "
        "y pulsa 'Remove Driver'."
    )
