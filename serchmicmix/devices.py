"""Enumeracion generica de dispositivos de audio.

Reglas de diseno (para que funcione en *cualquier* PC):

* Nunca se asume un nombre, indice ni idioma concreto de dispositivo.
* Se prefiere el controlador WASAPI (mejor calidad y menor latencia). Si ese
  controlador no ofrece nada, se cae automaticamente al siguiente disponible.
* Se descartan los dispositivos "pseudo" (Sound Mapper / Controlador primario)
  y las entradas WDM-KS sin nombre util.
* La identidad de un dispositivo para guardar la configuracion es
  ``controlador::nombre`` (no el indice, que cambia entre reinicios).
"""

from __future__ import annotations

import ctypes
import re
import unicodedata
from dataclasses import dataclass

import sounddevice as sd


# --------------------------------------------------------------------------
# COM por hilo (Windows)
# --------------------------------------------------------------------------
#: COINIT_MULTITHREADED. Es el apartamento correcto para un hilo que no
#: procesa mensajes de ventana.
_COINIT_MULTITHREADED = 0x2


def init_com() -> bool:
    """Inicializa COM en el hilo actual.

    **Es obligatorio antes de tocar PortAudio/WASAPI desde un hilo que no sea
    el principal.** Windows exige que COM este inicializado en el hilo que
    hace las llamadas, y PortAudio solo lo hace por el hilo que ejecuta
    ``Pa_Initialize``. Si un hilo trabajador abre o arranca un stream sin
    esto, el fallo que aparece es enganoso y no menciona COM para nada:

        PortAudioError: Error starting stream: Unanticipated host error
        [PaErrorCode -9999]: 'WdmSyncIoctl: DeviceIoControl GLE = 0x00000492'
        (que significa "el conjunto de propiedades especificado no existe")

    Devuelve ``True`` solo si COM lo inicializo *este* hilo (S_OK). Si ya
    estaba inicializado (``S_FALSE``) o lo estaba con otro apartamento
    (``RPC_E_CHANGED_MODE``) devuelve ``False``, y en ese caso **no** hay que
    llamar a ``liberar_com()`` para no desbalancear el contador de COM.
    """
    try:
        resultado = ctypes.windll.ole32.CoInitializeEx(None, _COINIT_MULTITHREADED)
        return int(resultado) == 0  # S_OK
    except Exception:
        # En plataformas que no son Windows, o si ole32 no esta, no hay nada
        # que hacer: PortAudio tampoco necesitara COM.
        return False


def liberar_com(inicializado: bool) -> None:
    """Deshace ``init_com()`` al terminar el hilo.

    Solo debe llamarse si ``init_com()`` devolvio ``True``.
    """
    if not inicializado:
        return
    try:
        ctypes.windll.ole32.CoUninitialize()
    except Exception:
        pass

# --------------------------------------------------------------------------
# Controladores
# --------------------------------------------------------------------------
API_RANK = {
    "Windows WASAPI": 0,
    "Windows DirectSound": 1,
    "MME": 2,
    "ASIO": 3,
    "Windows WDM-KS": 4,
}

# Nombres de los dispositivos "comodin" que no son hardware real.
_PSEUDO_RE = re.compile(
    r"(sound\s*mapper|asignador\s*de\s*sonido|primary\s*sound|controlador\s*primario"
    r"|default\s*device|dispositivo\s*predeterminado|microsoft\s*sound\s*mapper)",
    re.I,
)

# Dispositivos WDM-KS sin nombre real, del estilo "Input ()" o "Speakers ()".
_EMPTY_NAME_RE = re.compile(r"^(input|output|speakers|microphone|line\s*in|micr[oó]fono|altavoces|entrada|salida)\s*\(?\s*\)?$", re.I)

# Todo lo que identifica a un cable virtual de VB-Audio (VB-Cable, Cable A/B,
# Hi-Fi Cable, VoiceMeeter). Sirve para etiquetar y para el asistente de
# instalacion; se compara sin distinguir mayusculas ni acentos.
_VIRTUAL_RE = re.compile(
    r"(vb[\s\-_]*audio|vb[\s\-_]*cable|vbcable|virtual\s*cable|cable\s*virtual"
    r"|hifi[\s\-_]*cable|voicemeeter|voicemeeter\s*aux"
    r"|cable[\s\-_]*(input|output|in|out)\b"
    r"|cable[\s\-_]*[ab]\b)",
    re.I,
)

# Especificamente el extremo de *reproduccion* de VB-Cable (lo que las apps
# usan como "altavoz" para mandar audio al cable).
_CABLE_RENDER_RE = re.compile(r"cable[\s\-_]*([ab][\s\-_]*)?(input|in\b)", re.I)

# Especificamente el extremo de *captura* de VB-Cable (lo que las apps leen).
_CABLE_CAPTURE_RE = re.compile(r"cable[\s\-_]*([ab][\s\-_]*)?(output|out\b)", re.I)


def strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def norm(text: str) -> str:
    return strip_accents(text or "").strip().lower()


def is_virtual_device(name: str) -> bool:
    return bool(_VIRTUAL_RE.search(name or ""))


def is_cable_render(name: str) -> bool:
    return bool(_CABLE_RENDER_RE.search(name or ")"))


def is_cable_capture(name: str) -> bool:
    return bool(_CABLE_CAPTURE_RE.search(name or ""))


@dataclass(frozen=True)
class DeviceInfo:
    """Descripcion inmutable de un dispositivo apto para usar."""

    index: int
    name: str
    hostapi: str
    max_in: int
    max_out: int
    default_sr: float
    is_default: bool
    kind: str  # "input" | "output"

    @property
    def key(self) -> str:
        """Identificador estable para guardar la configuracion."""
        return f"{self.hostapi}::{self.name}"

    @property
    def virtual(self) -> bool:
        return is_virtual_device(self.name)

    @property
    def is_cable_endpoint(self) -> bool:
        """Extremo de un cable virtual.

        La direccion la marca el propio dispositivo (una salida virtual es el
        extremo de reproduccion; una entrada virtual, el de captura), de modo
        que funciona igual con VB-Cable, Cable A/B, Hi-Fi Cable o VoiceMeeter.
        """
        return self.virtual

    @property
    def category(self) -> str:
        """'music' para el cable virtual (audio del sistema), 'mic' para el resto."""
        return "music" if self.virtual else "mic"

    def display_name(self) -> str:
        return self.name


def _hostapi_table() -> list[dict]:
    try:
        return list(sd.query_hostapis())
    except Exception:
        return []


def _default_indices() -> tuple[set[int], set[int]]:
    """Indices de dispositivo predeterminado, buscando en el mejor controlador."""
    ins: set[int] = set()
    outs: set[int] = set()
    apis = _hostapi_table()
    ordered = sorted(
        range(len(apis)),
        key=lambda i: API_RANK.get(apis[i].get("name", ""), 9),
    )
    for i in ordered:
        api = apis[i]
        di = api.get("default_input_device", -1)
        do = api.get("default_output_device", -1)
        if di is not None and di >= 0:
            ins.add(int(di))
        if do is not None and do >= 0:
            outs.add(int(do))
    return ins, outs


def _accept(dev: dict, name: str, kind: str, show_all: bool) -> bool:
    api = dev.get("hostapi", 0)
    apis = _hostapi_table()
    api_name = apis[api]["name"] if 0 <= api < len(apis) else ""
    if not show_all and API_RANK.get(api_name, 9) > API_RANK.get("MME", 2):
        # En modo normal solo WASAPI / DirectSound / MME
        return False
    if _PSEUDO_RE.search(name):
        return False
    if _EMPTY_NAME_RE.match(name.strip()):
        return False
    if not show_all and "WDM-KS" in api_name:
        return False
    if kind == "input" and dev.get("max_input_channels", 0) < 1:
        return False
    if kind == "output" and dev.get("max_output_channels", 0) < 1:
        return False
    return True


def _collect(kind: str, show_all: bool) -> list[DeviceInfo]:
    apis = _hostapi_table()
    try:
        devices = list(sd.query_devices())
    except Exception:
        return []
    defaults_in, defaults_out = _default_indices()
    defaults = defaults_in if kind == "input" else defaults_out

    found: list[DeviceInfo] = []
    for idx, dev in enumerate(devices):
        name = str(dev.get("name", "")).strip()
        api = dev.get("hostapi", 0)
        api_name = apis[api]["name"] if 0 <= api < len(apis) else "?"
        if not _accept(dev, name, kind, show_all):
            continue
        found.append(
            DeviceInfo(
                index=idx,
                name=name,
                hostapi=api_name,
                max_in=int(dev.get("max_input_channels", 0)),
                max_out=int(dev.get("max_output_channels", 0)),
                default_sr=float(dev.get("default_samplerate", 48000.0) or 48000.0),
                is_default=idx in defaults,
                kind=kind,
            )
        )

    if show_all:
        return _dedupe(found)

    # Politica: usar el mejor controlador que aporte dispositivos reales.
    by_api: dict[int, list[DeviceInfo]] = {}
    for d in found:
        by_api.setdefault(API_RANK.get(d.hostapi, 9), []).append(d)
    for rank in sorted(by_api):
        group = by_api[rank]
        if group:
            return _dedupe(group)
    return []


def _dedupe(items: list[DeviceInfo]) -> list[DeviceInfo]:
    """Elimina duplicados con el mismo nombre normalizado (conserva el mejor)."""
    seen: dict[str, DeviceInfo] = {}
    order: list[str] = []
    for dev in sorted(items, key=lambda d: API_RANK.get(d.hostapi, 9)):
        k = norm(dev.name)
        if k in seen:
            continue
        seen[k] = dev
        order.append(k)
    return [seen[k] for k in order]


def list_inputs(show_all: bool = False) -> list[DeviceInfo]:
    return _collect("input", show_all)


def list_outputs(show_all: bool = False) -> list[DeviceInfo]:
    return _collect("output", show_all)


def refresh_portaudio() -> None:
    """Reinicia PortAudio por completo para reescanear el hardware.

    Es la via segura pero **corta todos los streams**: solo debe llamarse
    cuando no hay nada abierto. Para detectar cambios con audio sonando usa
    ``refresh_wasapi_devices()``.
    """
    try:
        sd._terminate()
    except Exception:
        pass
    try:
        sd._initialize()
    except Exception:
        pass


def refresh_wasapi_devices() -> bool:
    """Pide a PortAudio que vuelva a enumerar los dispositivos WASAPI.

    A diferencia de ``refresh_portaudio()``, esta llamada **no reinicia**
    PortAudio, asi que es segura teniendo streams abiertos. Es lo que permite
    detectar una bocina Bluetooth que se acaba de encender, o notar que se ha
    apagado, sin que se corte el audio que este sonando.

    Devuelve ``True`` si el refresco se pudo realizar.
    """
    lib = getattr(sd, "_lib", None)
    fn = getattr(lib, "PaWasapi_UpdateDeviceList", None) if lib is not None else None
    if fn is None:
        return False
    try:
        fn()
        return True
    except Exception:
        return False


def device_signature() -> tuple:
    """Huella de la lista de dispositivos, para detectar cambios.

    Dos huellas distintas significan que alguien ha conectado o desconectado
    algo (o que Windows ha cambiado su configuracion).
    """
    try:
        devs = sd.query_devices()
        apis = _hostapi_table()
    except Exception:
        return ()
    out = []
    for dev in devs:
        api = dev.get("hostapi", 0)
        api_name = apis[api]["name"] if 0 <= api < len(apis) else "?"
        out.append(
            (
                str(dev.get("name", "")),
                api_name,
                int(dev.get("max_input_channels", 0)),
                int(dev.get("max_output_channels", 0)),
            )
        )
    return tuple(out)


def poll_devices() -> tuple:
    """Refresca la lista WASAPI y devuelve su huella actual."""
    refresh_wasapi_devices()
    return device_signature()


def build_registry(show_all: bool = False) -> tuple[list[DeviceInfo], list[DeviceInfo]]:
    return list_inputs(show_all), list_outputs(show_all)


def find_virtual_endpoints(outputs: list[DeviceInfo], inputs: list[DeviceInfo]) -> dict:
    """Localiza los extremos del cable virtual entre los dispositivos actuales."""
    render = [d for d in outputs if d.is_cable_endpoint] or [d for d in outputs if d.virtual]
    capture = [d for d in inputs if d.is_cable_endpoint] or [d for d in inputs if d.virtual]
    render = sorted(render, key=lambda d: (0 if "cable" in norm(d.name) else 1, d.name))
    capture = sorted(capture, key=lambda d: (0 if "cable" in norm(d.name) else 1, d.name))
    return {
        "installed": bool(render and capture),
        "render": render[0] if render else None,
        "capture": capture[0] if capture else None,
        "render_all": render,
        "capture_all": capture,
    }


def query_device_channels(index: int) -> tuple[int, int]:
    try:
        dev = sd.query_devices(index)
        return int(dev.get("max_input_channels", 0)), int(dev.get("max_output_channels", 0))
    except Exception:
        return 0, 0


def check_settings(kind: str, index: int, samplerate: int, channels: int, extra=None) -> bool:
    try:
        if kind == "input":
            sd.check_input_settings(device=index, samplerate=samplerate, channels=channels, extra_settings=extra)
        else:
            sd.check_output_settings(device=index, samplerate=samplerate, channels=channels, extra_settings=extra)
        return True
    except Exception:
        return False
