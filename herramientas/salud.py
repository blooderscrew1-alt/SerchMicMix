"""Comprobacion de salud de Serch MicMix: diagnostico y reparacion.

Se usa desde ``diagnostico.bat`` y ``reparar.bat``, pero tambien a mano:

    python herramientas\\salud.py            (informe y recomendaciones)
    python herramientas\\salud.py --reparar  (reinstala lo que falle)

Existe porque el error tipico en un PC recien preparado no es de Serch MicMix:
numpy no consigue cargar sus DLL y el mensaje de Python ("DLL load failed
while importing _multiarray_umath") no dice nada util al usuario.
"""

from __future__ import annotations

import argparse
import ctypes
import importlib.util
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

MODULOS = ("PySide6", "sounddevice", "numpy")

VC_REDIST = {
    "AMD64": "https://aka.ms/vs/17/release/vc_redist.x64.exe",
    "ARM64": "https://aka.ms/vs/17/release/vc_redist.arm64.exe",
    "X86": "https://aka.ms/vs/17/release/vc_redist.x86.exe",
}

#: NumPy 2.x exige SSE4.2 como minimo en x86-64 (documentado por NumPy).
#: Los procesadores AMD anteriores a Bulldozer (Phenom, Athlon II...) y los
#: Intel anteriores a Nehalem no lo tienen, asi que numpy 2 no puede cargar
#: alli. La solucion es un Python mas antiguo con numpy 1.26, cuya linea
#: base era SSE3.
FEATURES_CPU = (
    ("SSSE3", 36),
    ("SSE4.1", 37),
    ("SSE4.2", 38),
    ("AVX", 39),
    ("AVX2", 40),
)

#: Ultimo instalador de Windows publicado para cada rama (python.org deja de
#: publicar binarios cuando la rama pasa a solo-seguridad).
PYTHON_COMPATIBLE = "3.12.10"
URL_PYTHON_COMPATIBLE = (
    f"https://www.python.org/ftp/python/{PYTHON_COMPATIBLE}/"
    f"python-{PYTHON_COMPATIBLE}-amd64.exe"
)
NUMPY_COMPATIBLE = "numpy==1.26.4"

LINEA = "=" * 62


# --------------------------------------------------------------------------
def log(texto: str = "") -> None:
    print(texto, flush=True)


def probar_modulo_en_proceso(modulo: str) -> tuple[bool, str]:
    """Prueba un import en un proceso limpio y devuelve (ok, error).

    Se usa un proceso nuevo porque un import fallido puede dejar el
    interprete en un estado raro, y porque asi el resultado es el mismo que
    tendra la aplicacion al arrancar.
    """
    codigo = f"import {modulo}"
    try:
        with tempfile.TemporaryFile() as salida:
            proc = subprocess.run(
                [sys.executable, "-c", codigo],
                stdout=salida,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
            )
            salida.seek(0)
            texto = salida.read().decode("utf-8", "replace").strip()
    except Exception as exc:  # no se pudo ni lanzar el proceso
        return False, f"No se pudo ejecutar Python: {exc}"
    if proc.returncode == 0:
        return True, ""
    return False, texto or f"codigo de salida {proc.returncode}"


def arquitectura() -> str:
    maquina = (platform.machine() or "").upper()
    if "ARM" in maquina:
        return "ARM64"
    if "AMD64" in maquina or "X86_64" in maquina or "64" in maquina:
        return "AMD64"
    return "X86"


def nombre_cpu() -> str:
    try:
        import winreg

        clave = r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, clave) as k:
            return str(winreg.QueryValueEx(k, "ProcessorNameString")[0]).strip()
    except Exception:
        return platform.processor() or "desconocido"


def caracteristicas_cpu() -> dict[str, bool | None]:
    """Consulta que instrucciones SIMD tiene el procesador.

    Se pregunta a Windows con ``IsProcessorFeaturePresent``, que es la forma
    fiable de saberlo sin ejecutar codigo que podria fallar.
    """
    resultado: dict[str, bool | None] = {}
    try:
        kernel32 = ctypes.windll.kernel32
    except Exception:
        return {nombre: None for nombre, _ in FEATURES_CPU}
    for nombre, codigo in FEATURES_CPU:
        try:
            resultado[nombre] = bool(kernel32.IsProcessorFeaturePresent(codigo))
        except Exception:
            resultado[nombre] = None
    return resultado


def cpu_admite_numpy_moderno() -> bool | None:
    """True/False/None (None = no se pudo averiguar)."""
    return caracteristicas_cpu().get("SSE4.2")


def es_64_bits() -> bool:
    return sys.maxsize > 2**32


def version_windows() -> str:
    try:
        v = sys.getwindowsversion()
        return f"Windows {v.major}.{v.minor} build {v.build}"
    except Exception:
        return platform.platform()


def version_pip() -> str:
    try:
        with tempfile.TemporaryFile() as salida:
            subprocess.run(
                [sys.executable, "-m", "pip", "--version"],
                stdout=salida,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
            )
            salida.seek(0)
            return salida.read().decode("utf-8", "replace").strip()
    except Exception as exc:
        return f"(no se pudo consultar: {exc})"


def pip_disponible() -> bool:
    try:
        with tempfile.TemporaryFile() as salida:
            proc = subprocess.run(
                [sys.executable, "-m", "pip", "--version"],
                stdout=salida,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
            )
        return proc.returncode == 0
    except Exception:
        return False


def es_fallo_de_dll(error: str) -> bool:
    """True si el error huele a DLL que no carga (y no a modulo ausente).

    Es la diferencia entre "falta instalar numpy" y "numpy esta instalado
    pero Windows no consigue cargar sus DLL", que es el caso del
    redistribuible de Visual C++.
    """
    texto = (error or "").lower()
    if "modulenotfounderror" in texto or "no module named" in texto:
        return False
    return (
        "dll load failed" in texto
        or "dll initialization" in texto
        or "_multiarray_umath" in texto
        or "importerror" in texto
        or "winerror 126" in texto
    )


def carpeta_programa() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# --------------------------------------------------------------------------
def runtime_vc() -> tuple[int, str]:
    """Version instalada del redistribuible de Visual C++ 2015-2022 (x64)."""
    try:
        import winreg
    except ImportError:
        return 0, "desconocido"
    rutas = [
        r"SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\X64",
        r"SOFTWARE\WOW6432Node\Microsoft\VisualStudio\14.0\VC\Runtimes\X64",
        r"SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\Arm64",
    ]
    for ruta in rutas:
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, ruta) as clave:
                instalado = winreg.QueryValueEx(clave, "Installed")[0]
                version = winreg.QueryValueEx(clave, "Version")[0]
                if instalado:
                    return 1, str(version)
        except OSError:
            continue
    return 0, "no instalado"


def dlls_runtime_presentes() -> list[str]:
    sistema = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "System32")
    encontradas = []
    for nombre in ("vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll", "concrt140.dll"):
        if os.path.exists(os.path.join(sistema, nombre)):
            encontradas.append(nombre)
    return encontradas


def info_numpy() -> list[str]:
    """Detalles del numpy instalado, incluso si no se puede importar."""
    lineas: list[str] = []
    try:
        spec = importlib.util.find_spec("numpy")
    except Exception as exc:
        return [f"No se pudo localizar numpy: {exc}"]
    if spec is None or not spec.origin:
        return ["numpy no esta instalado"]

    carpeta = os.path.dirname(spec.origin)
    lineas.append(f"carpeta: {carpeta}")

    libs = os.path.join(carpeta, "..", "numpy.libs")
    libs = os.path.normpath(libs)
    if os.path.isdir(libs):
        contenido = sorted(os.listdir(libs))
        lineas.append(f"numpy.libs: {len(contenido)} archivo(s)")
        for nombre in contenido[:8]:
            lineas.append(f"    {nombre}")
    else:
        lineas.append("numpy.libs: NO EXISTE  <-- falta la libreria de calculo")

    nucleo = os.path.join(carpeta, "_core")
    if os.path.isdir(nucleo):
        pyds = sorted(f for f in os.listdir(nucleo) if f.endswith(".pyd"))
        lineas.append(f"extensiones nativas: {', '.join(pyds) if pyds else 'ninguna'}")
    return lineas


# --------------------------------------------------------------------------
def informe() -> tuple[bool, list[str]]:
    """Escribe el informe completo. Devuelve (todo_ok, modulos_que_fallan)."""
    log(LINEA)
    log(" Serch MicMix - informe de salud")
    log(LINEA)
    log()
    log("--- Sistema ---")
    log(f"  {version_windows()}")
    log(f"  Arquitectura: {arquitectura()}")
    log(f"  Carpeta del programa: {carpeta_programa()}")

    log()
    log("--- Procesador ---")
    cpu_nombre = nombre_cpu()
    features = caracteristicas_cpu()
    log(f"  {cpu_nombre}")
    log("  Instrucciones: " + ", ".join(
        f"{nombre}={'si' if valor else ('no' if valor is False else '?')}"
        for nombre, valor in features.items()
    ))
    sse42 = features.get("SSE4.2")
    if sse42 is False:
        log("  AVISO: este procesador NO tiene SSE4.2.")
        log("  numpy 2.x lo exige, asi que no puede cargar en este equipo.")
        log(f"  Hace falta Python {PYTHON_COMPATIBLE} con {NUMPY_COMPATIBLE}.")
    elif sse42 is None:
        log("  (no se pudo averiguar el soporte de SSE4.2)")

    log()
    log("--- Python que se esta usando ---")
    log(f"  ejecutable : {sys.executable}")
    log(f"  version    : {platform.python_version()}")
    log(f"  64 bits    : {'si' if es_64_bits() else 'NO (se necesita 64 bits)'}")
    log(f"  entorno    : {sys.prefix}")
    log(f"  pip        : {version_pip()}")

    log()
    log("--- Dependencias ---")
    fallan: list[str] = []
    errores: dict[str, str] = {}
    for modulo in MODULOS:
        ok, error = probar_modulo_en_proceso(modulo)
        if ok:
            log(f"  [OK]    {modulo}")
        else:
            log(f"  [FALLA] {modulo}")
            fallan.append(modulo)
            errores[modulo] = error

    for modulo, error in errores.items():
        log()
        log(f"--- Detalle del fallo de {modulo} ---")
        for linea in error.splitlines():
            log(f"  {linea}")

    log()
    log("--- Runtime de Microsoft Visual C++ 2015-2022 ---")
    instalado, version = runtime_vc()
    log(f"  instalado: {'si' if instalado else 'NO'}  (version: {version})")
    dlls = dlls_runtime_presentes()
    log(f"  DLLs en System32: {', '.join(dlls) if dlls else 'ninguna'}")

    if "numpy" in fallan:
        log()
        log("--- numpy (detalle) ---")
        for linea in info_numpy():
            log(f"  {linea}")

    log()
    log("--- Dispositivos de audio ---")
    try:
        import sounddevice as sd

        dispositivos = sd.query_devices()
        entradas = sum(1 for d in dispositivos if d["max_input_channels"] > 0)
        salidas = sum(1 for d in dispositivos if d["max_output_channels"] > 0)
        log(f"  {len(dispositivos)} dispositivos ({entradas} entradas, {salidas} salidas)")
    except Exception as exc:
        log(f"  no se pudieron consultar: {type(exc).__name__}: {exc}")

    log()
    log("--- Recomendaciones ---")
    hay_pip = pip_disponible()
    if not hay_pip:
        log("  pip no funciona en este Python, asi que no se puede instalar nada")
        log("  automaticamente. Vuelve a instalar Python desde python.org marcando")
        log("  las casillas 'pip' y 'Add python.exe to PATH'.")
    if not es_64_bits():
        log("  ATENCION: este Python es de 32 bits. Serch MicMix necesita uno de 64 bits.")

    if not fallan:
        log("  Todo correcto. Ejecuta run.bat para abrir serchmicmix.")
    elif sse42 is False and "numpy" in fallan:
        log("  La causa NO es Internet ni el runtime de Visual C++: es el")
        log("  procesador. numpy 2.x necesita SSE4.2 y este no lo tiene.")
        log("")
        log(f"  Solucion: usar Python {PYTHON_COMPATIBLE} (cuya numpy 1.26.4 si")
        log("  funciona sin SSE4.2). reparar.bat puede instalarlo por ti en tu")
        log("  propio usuario, sin tocar el Python actual.")
    else:
        if hay_pip:
            log(f"  Ejecuta reparar.bat: reinstalara {', '.join(fallan)}.")
        problemas_dll = [m for m in fallan if es_fallo_de_dll(errores.get(m, ""))]
        if problemas_dll:
            log("")
            log(f"  {', '.join(problemas_dll)} esta instalado pero Windows no consigue")
            log("  cargar sus DLL. La causa mas habitual es que falte (o este")
            log("  anticuado) el redistribuible de Microsoft Visual C++ 2015-2022.")
            if not instalado:
                log("  Aqui NO esta instalado, asi que es lo primero que hay que")
                log("  resolver.")
            log(f"  Descarga: {VC_REDIST.get(arquitectura(), VC_REDIST['AMD64'])}")
            log("  reparar.bat puede descargarlo e instalarlo por ti.")
        log("")
        log("  Si nada de esto funciona, guarda este informe y pide ayuda con el.")
    log()
    log(LINEA)
    return not fallan, fallan


# --------------------------------------------------------------------------
def reinstalar(modulos: list[str]) -> None:
    log()
    log(LINEA)
    log(f" Reinstalando: {', '.join(modulos)}")
    log(" (se descarga de nuevo desde Internet; puede tardar unos minutos)")
    log(LINEA)
    for modulo in modulos:
        log()
        log(f">>> {modulo}")
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--force-reinstall",
                "--no-cache-dir",
                modulo,
            ],
            stdin=subprocess.DEVNULL,
        )


def descargar(url: str) -> str | None:
    """Descarga un archivo a la carpeta temporal, mostrando el progreso."""
    destino = os.path.join(tempfile.gettempdir(), os.path.basename(url))
    log()
    log(f"Descargando {url}")
    try:
        with urllib.request.urlopen(url, timeout=90) as respuesta, open(destino, "wb") as fh:
            total = int(respuesta.headers.get("Content-Length") or 0)
            hecho = 0
            while True:
                trozo = respuesta.read(262144)
                if not trozo:
                    break
                fh.write(trozo)
                hecho += len(trozo)
                if total:
                    print(
                        f"\r  {hecho / 1048576:.1f} / {total / 1048576:.1f} MB",
                        end="",
                        flush=True,
                    )
        print()
    except Exception as exc:
        log(f"  No se pudo descargar: {type(exc).__name__}: {exc}")
        return None
    log(f"  Guardado en: {destino}")
    return destino


def descargar_redist() -> str | None:
    url = VC_REDIST.get(arquitectura(), VC_REDIST["AMD64"])
    ruta = descargar(url)
    if ruta is None:
        log(f"  Descargalo a mano desde: {url}")
    return ruta


def ruta_python_compatible() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or ""
    carpeta = f"Python{PYTHON_COMPATIBLE.replace('.', '')[:3]}"  # Python312
    if base:
        return os.path.join(base, "Programs", "Python", carpeta, "python.exe")
    return ""


def instalar_python_compatible() -> bool:
    """Instala Python 3.12 para el usuario y las dependencias compatibles.

    Se instala **solo para el usuario actual** (no pide administrador) y no se
    toca el PATH, para no descolocar el Python que ya hubiera.
    """
    log()
    log(LINEA)
    log(f" Instalando Python {PYTHON_COMPATIBLE} (solo para tu usuario)")
    log(LINEA)
    log(" Se guardara en tu carpeta de usuario. NO se toca el Python actual")
    log(" ni el PATH del sistema, asi que no estropea nada de lo que ya hay.")
    log()

    instalador = descargar(URL_PYTHON_COMPATIBLE)
    if instalador is None:
        log(f"  Descargalo a mano desde: {URL_PYTHON_COMPATIBLE}")
        return False

    log()
    log("Instalando en silencio (puede tardar un par de minutos)...")
    try:
        proc = subprocess.run(
            [
                instalador,
                "/quiet",
                "InstallAllUsers=0",
                "PrependPath=0",
                "Include_pip=1",
                "Include_test=0",
                "Include_launcher=0",
                "AssociateFiles=0",
                "Shortcuts=0",
            ],
            stdin=subprocess.DEVNULL,
        )
    except Exception as exc:
        log(f"  No se pudo ejecutar el instalador: {type(exc).__name__}: {exc}")
        return False

    if proc.returncode not in (0, 3010):
        log(f"  El instalador devolvio el codigo {proc.returncode}.")
        return False

    python = ruta_python_compatible()
    if not os.path.exists(python):
        log(f"  No se encontro el Python instalado en: {python}")
        log("  Busca la carpeta 'Python312' dentro de tu carpeta de usuario.")
        return False

    log(f"  Python instalado en: {python}")
    log()
    log("Instalando numpy 1.26.4 (compatible sin SSE4.2), sounddevice y PySide6...")
    subprocess.run(
        [
            python,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            NUMPY_COMPATIBLE,
            "sounddevice",
            "PySide6",
        ],
        stdin=subprocess.DEVNULL,
    )

    log()
    log("Comprobando que todo carga con el Python nuevo...")
    todo_ok = True
    for modulo in MODULOS:
        try:
            with tempfile.TemporaryFile() as salida:
                p = subprocess.run(
                    [python, "-c", f"import {modulo}"],
                    stdout=salida,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                )
            ok = p.returncode == 0
        except Exception:
            ok = False
        log(f"  [{'OK' if ok else 'FALLA'}] {modulo}")
        todo_ok = todo_ok and ok

    if todo_ok:
        log()
        log(LINEA)
        log(" LISTO. Ya puedes abrir Serch MicMix con run.bat")
        log(f" (usara automaticamente {python})")
        log(LINEA)
    return todo_ok


def instalar_redist(ruta: str) -> None:
    log()
    log("Instalando el redistribuible (Windows pedira permiso de administrador)...")
    try:
        codigo = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", ruta, "/install /passive /norestart", None, 1
        )
    except Exception as exc:
        log(f"  No se pudo lanzar: {exc}")
        return
    if int(codigo) <= 32:
        log("  Permisos denegados. Ejecutalo tu mismo con doble clic:")
        log(f"  {ruta}")
        return
    log("  Instalador lanzado. Espera a que termine y REINICIA el equipo.")


def reparar() -> int:
    todo_ok, fallan = informe()
    if todo_ok:
        return 0

    # --- Caso especial: procesador anterior a SSE4.2 --------------------
    # Aqui no sirve de nada reinstalar numpy: la version que se instalaria
    # sigue necesitando SSE4.2. Hace falta un Python mas antiguo.
    if cpu_admite_numpy_moderno() is False and "numpy" in fallan:
        log()
        log(LINEA)
        log(" Tu procesador no puede con numpy 2.x")
        log(LINEA)
        log(" numpy 2.x exige SSE4.2 y este procesador no lo tiene (es normal en")
        log(" los AMD Phenom / Athlon II y en los Intel anteriores a Nehalem).")
        log(" Reinstalar numpy no arreglaria nada.")
        log()
        log(f" La solucion es Python {PYTHON_COMPATIBLE}, que admite numpy 1.26.4,")
        log(" cuya linea base es SSE3 y si funciona en este procesador.")
        log()
        log(" Se instalaria SOLO para tu usuario y sin tocar el Python actual:")
        python_ok = ruta_python_compatible()
        if python_ok and os.path.exists(python_ok):
            log(f"   (ya existe: {python_ok})")
        log()
        try:
            respuesta = input(
                f"  Instalar Python {PYTHON_COMPATIBLE} y las dependencias ahora? (S/N): "
            ).strip().lower()
        except (EOFError, KeyboardInterrupt):
            respuesta = "n"
        if respuesta in ("s", "si", "sí", "y", "yes"):
            return 0 if instalar_python_compatible() else 1
        log()
        log(f"  Si prefieres hacerlo a mano, descarga Python {PYTHON_COMPATIBLE}:")
        log(f"    {URL_PYTHON_COMPATIBLE}")
        log("  Instalalo para tu usuario y luego ejecuta:")
        log(f"    pip install {NUMPY_COMPATIBLE} sounddevice PySide6")
        return 1

    log()
    try:
        respuesta = input(f"  Reinstalar ahora {', '.join(fallan)}? (S/N): ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        respuesta = "n"
    if respuesta not in ("s", "si", "sí", "y", "yes"):
        log("  Cancelado.")
        return 1

    reinstalar(fallan)

    log()
    log("Comprobando de nuevo...")
    siguen = []
    errores_finales: dict[str, str] = {}
    for modulo in fallan:
        ok, error = probar_modulo_en_proceso(modulo)
        log(f"  [{'OK' if ok else 'FALLA'}] {modulo}")
        if not ok:
            siguen.append(modulo)
            errores_finales[modulo] = error

    if not siguen:
        log()
        log(LINEA)
        log(" RESUELTO. Ya puedes abrir Serch MicMix con run.bat")
        log(LINEA)
        return 0

    log()
    log(f" Siguen fallando: {', '.join(siguen)}")

    problemas_dll = [m for m in siguen if es_fallo_de_dll(errores_finales.get(m, ""))]
    if problemas_dll:
        instalado, version = runtime_vc()
        log()
        log("--- Causa mas probable ---")
        log(f"  {', '.join(problemas_dll)} esta instalado, pero Windows no")
        log("  consigue cargar sus DLL. Eso apunta al redistribuible de")
        log("  Microsoft Visual C++ 2015-2022.")
        if not instalado:
            log("  En este equipo NO esta instalado: es casi seguro el motivo.")
        else:
            log(f"  Esta instalado (version {version}), pero puede estar anticuado.")
        log()
        try:
            respuesta = input("  Descargar e instalar el redistribuible ahora? (S/N): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            respuesta = "n"
        if respuesta in ("s", "si", "sí", "y", "yes"):
            ruta = descargar_redist()
            if ruta:
                instalar_redist(ruta)
                log()
                log("  Cuando termine, REINICIA el equipo y vuelve a ejecutar")
                log("  reparar.bat para confirmar.")
                return 0

    log()
    log("  Si sigue sin funcionar, guarda el informe y pide ayuda con el.")
    return 1


# --------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnostico y reparacion de Serch MicMix")
    parser.add_argument("--reparar", action="store_true", help="reinstala lo que falle")
    parser.add_argument("--salida", default="", help="guardar el informe en este archivo")
    args = parser.parse_args()

    if args.salida:
        original = sys.stdout

        class Duplicador:
            def write(self, texto):
                original.write(texto)
                self._fh.write(texto)
                return len(texto)

            def flush(self):
                original.flush()
                self._fh.flush()

        with open(args.salida, "w", encoding="utf-8") as fh:
            dup = Duplicador()
            dup._fh = fh
            sys.stdout = dup
            try:
                codigo = reparar() if args.reparar else (0 if informe()[0] else 1)
            finally:
                sys.stdout = original
        print(f"\nInforme guardado en: {args.salida}")
        return codigo

    if args.reparar:
        return reparar()
    return 0 if informe()[0] else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
