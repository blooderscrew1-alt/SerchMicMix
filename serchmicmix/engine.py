"""Motor de mezcla y ruteo de audio en tiempo real.

Arquitectura
------------
* Un hilo trabajador ("reconciler") abre y cierra los streams de PortAudio.
  La interfaz grafica nunca toca PortAudio directamente, asi que activar o
  desactivar un dispositivo jamas congela la ventana.
* Cada entrada tiene su propio ``InputStream`` que escribe en un anillo
  (``RingBuffer``) a la frecuencia maestra.
* Cada salida tiene su propio ``OutputStream``. En su callback lee de los
  anillos con un cursor propio, aplica ganancia suavizada (sin clics) y
  escribe la mezcla. Varias salidas pueden sonar a la vez.
* Si un dispositivo no admite la frecuencia maestra, su entrada se remuestrea
  con interpolacion lineal (la salida usa el remuestreo de WASAPI).

Todo esta pensado para no fallar nunca de forma fatal: cualquier dispositivo
que no se pueda abrir se marca con un error y el resto sigue funcionando.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

import numpy as np
import sounddevice as sd

from . import devices as dev_mod

# Tamano de bloque de referencia (10 ms a 48 kHz)
REF_BLOCK = 480
# Segundos de historial del anillo
RING_SECONDS = 0.75


# --------------------------------------------------------------------------
# Utilidades de DSP
# --------------------------------------------------------------------------
class RingBuffer:
    """Anillo de tramas estereo float32 con lectura no destructiva por cursor."""

    def __init__(self, frames: int) -> None:
        self.cap = max(64, int(frames))
        self.buf = np.zeros((self.cap, 2), dtype=np.float32)
        self.written = 0
        self.lock = threading.Lock()

    def write(self, data: np.ndarray) -> None:
        n = data.shape[0]
        if n <= 0:
            return
        with self.lock:
            start = self.written % self.cap
            end = start + n
            if end <= self.cap:
                self.buf[start:end] = data
            else:
                k = self.cap - start
                self.buf[start:] = data[:k]
                self.buf[: end - self.cap] = data[k:]
            self.written += n

    def read(self, n: int, cursor: int) -> tuple[np.ndarray | None, int]:
        with self.lock:
            w = self.written
            if n <= 0:
                return None, cursor
            if cursor <= 0:
                # Primer bloque: empezar por lo mas reciente disponible.
                cursor = max(n, w)
            if cursor > w:
                # La salida va por delante de la entrada: silencio y resincroniza.
                return None, w
            oldest = w - (self.cap // 2)
            if cursor - n < oldest:
                # El cursor quedo obsoleto: saltar a lo mas reciente.
                cursor = max(oldest + n, w)
            start = cursor - n
            if start < 0:
                return None, cursor
            idx = start % self.cap
            if idx + n <= self.cap:
                data = self.buf[idx : idx + n].copy()
            else:
                k = self.cap - idx
                data = np.concatenate((self.buf[idx:], self.buf[: n - k]))
            return data, cursor


class LinearResampler:
    """Remuestreador lineal incremental (suficiente para voz y musica)."""

    def __init__(self, ratio: float) -> None:
        self.ratio = float(ratio)
        self.buf = np.zeros((0, 2), dtype=np.float32)
        self.t = 0.0

    @property
    def passthrough(self) -> bool:
        return abs(self.ratio - 1.0) < 1e-9

    def process(self, x: np.ndarray) -> np.ndarray | None:
        if self.passthrough:
            return x
        if x.ndim == 1:
            x = x[:, None]
        self.buf = np.concatenate((self.buf, x), axis=0)
        n = self.buf.shape[0]
        if n < 2:
            return None
        count = int(np.floor((n - 2 - self.t) * self.ratio)) + 1
        if count <= 0:
            return None
        k = np.arange(count, dtype=np.float64)
        pos = self.t + k / self.ratio
        i0 = np.floor(pos).astype(np.int64)
        np.clip(i0, 0, n - 2, out=i0)
        frac = (pos - i0).astype(np.float32)[:, None]
        out = self.buf[i0] * (1.0 - frac) + self.buf[i0 + 1] * frac
        self.t += count / self.ratio
        drop = int(np.floor(self.t))
        if drop > 0:
            self.buf = self.buf[drop:]
            self.t -= drop
        return out.astype(np.float32, copy=False)


def _soft_clip(x: np.ndarray, limit: float = 0.98) -> np.ndarray:
    """Saturacion suave: transparente por debajo de 0.6, techo en +/-limit."""
    np.clip(x, -1.5, 1.5, out=x)
    ax = np.abs(x)
    knee = 0.6
    over = ax > knee
    if np.any(over):
        scaled = knee + (limit - knee) * np.tanh((ax[over] - knee) / max(1e-6, (limit - knee)))
        x[over] = np.sign(x[over]) * scaled
    return x


def _ramp_gain(prev: float, target: float, frames: int) -> tuple[np.ndarray | None, float]:
    if abs(prev - target) < 1e-6:
        return None, target
    ramp = np.linspace(prev, target, frames, dtype=np.float32)[:, None]
    return ramp, target


# --------------------------------------------------------------------------
# Slots
# --------------------------------------------------------------------------
@dataclass
class InputSlot:
    key: str
    device: dev_mod.DeviceInfo
    gain: float = 1.0
    muted: bool = False
    solo: bool = False
    enabled: bool = False
    # --- runtime ---
    ring: RingBuffer | None = None
    stream: object | None = None
    resampler: LinearResampler | None = None
    rate: int = 0
    level: float = 0.0
    peak: float = 0.0
    error: str = ""
    xruns: int = 0
    next_retry: float = 0.0
    open_attempts: int = 0

    @property
    def category(self) -> str:
        return self.device.category

    @property
    def effective_gain(self) -> float:
        return 0.0 if self.muted else float(self.gain)


@dataclass
class OutputSlot:
    key: str
    device: dev_mod.DeviceInfo
    gain: float = 1.0
    muted: bool = False
    enabled: bool = False
    sources: dict = field(default_factory=lambda: {"mic": True, "music": True})
    # --- runtime ---
    stream: object | None = None
    rate: int = 0
    level: float = 0.0
    peak: float = 0.0
    error: str = ""
    xruns: int = 0
    next_retry: float = 0.0
    open_attempts: int = 0
    cursors: dict = field(default_factory=dict)
    gains: dict = field(default_factory=dict)
    cur_gain: float = -1.0

    @property
    def effective_gain(self) -> float:
        return 0.0 if self.muted else float(self.gain)


# --------------------------------------------------------------------------
# Motor
# --------------------------------------------------------------------------
class AudioEngine:
    #: Tiempo minimo que debe pasar entre dos conmutaciones de prioridad, para
    #: no estar saltando de salida en salida si un dispositivo parpadea.
    PRIORITY_SWITCH_COOLDOWN = 2.5
    #: Tiempo minimo antes de reintentar una salida que fallo al abrirse.
    RETRY_CAP_PRIORITY = 5.0
    RETRY_CAP_NORMAL = 15.0

    def __init__(self, config=None) -> None:
        self.config = config
        self.inputs: dict[str, InputSlot] = {}
        self.outputs: dict[str, OutputSlot] = {}

        self.master_gain = float(config.get("master_gain", default=0.9)) if config else 0.9
        self.limiter = bool(config.get("limiter", default=True)) if config else True

        prio = (config.get("priority", default={}) or {}) if config else {}
        self.priority_mode = bool(prio.get("enabled", False))
        self.priority_order: list[str] = [str(k) for k in (prio.get("order") or [])]
        self._priority_active: str | None = None
        self._priority_switched_at = 0.0

        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._active_inputs: list[InputSlot] = []
        self._active_outputs: list[OutputSlot] = []
        self._master_rate = 0
        self._solo_active = False
        self._dirty = True
        self._last_reconcile = 0.0

        self.stats = {
            "running": False,
            "master_rate": 0,
            "load": 0.0,
            "inputs_open": 0,
            "outputs_open": 0,
            "last_error": "",
        }
        self._cb_ms = 0.0

        self._thread = threading.Thread(target=self._loop, name="SerchMicMix-Reconciler", daemon=True)
        self._thread.start()

    # ------------------------------------------------------------- API GUI
    def sync_devices(self, inputs: list[dev_mod.DeviceInfo], outputs: list[dev_mod.DeviceInfo]) -> None:
        """Ajusta los slots a la lista de dispositivos actual, conservando ajustes."""
        with self._lock:
            for dev in inputs:
                slot = self.inputs.get(dev.key)
                if slot is None:
                    slot = InputSlot(key=dev.key, device=dev)
                    self._load_input_settings(slot)
                    self.inputs[dev.key] = slot
                else:
                    slot.device = dev
            for key in list(self.inputs):
                if key not in {d.key for d in inputs}:
                    self._close_input(self.inputs.pop(key))
            for dev in outputs:
                slot = self.outputs.get(dev.key)
                if slot is None:
                    slot = OutputSlot(key=dev.key, device=dev)
                    self._load_output_settings(slot)
                    self.outputs[dev.key] = slot
                else:
                    slot.device = dev
            for key in list(self.outputs):
                if key not in {d.key for d in outputs}:
                    self._close_output(self.outputs.pop(key))
        self._mark_dirty()

    def _load_input_settings(self, slot: InputSlot) -> None:
        if not self.config:
            return
        data = self.config.get("inputs", slot.key, default={}) or {}
        slot.gain = float(data.get("gain", 1.0))
        slot.muted = bool(data.get("muted", False))
        slot.solo = bool(data.get("solo", False))
        slot.enabled = bool(data.get("enabled", False))

    def _load_output_settings(self, slot: OutputSlot) -> None:
        if not self.config:
            return
        data = self.config.get("outputs", slot.key, default={}) or {}
        slot.gain = float(data.get("gain", 1.0))
        slot.muted = bool(data.get("muted", False))
        slot.enabled = bool(data.get("enabled", False))
        src = data.get("sources") or {}
        slot.sources = {"mic": bool(src.get("mic", True)), "music": bool(src.get("music", True))}

    def _persist(self, section: str, slot) -> None:
        if not self.config:
            return
        if isinstance(slot, InputSlot):
            payload = {"gain": slot.gain, "muted": slot.muted, "solo": slot.solo, "enabled": slot.enabled}
        else:
            payload = {
                "gain": slot.gain,
                "muted": slot.muted,
                "enabled": slot.enabled,
                "sources": dict(slot.sources),
            }
        self.config.set(section, slot.key, value=payload, save=False)
        self.config.save()

    def set_input(self, key: str, persist: bool = True, **changes) -> None:
        with self._lock:
            slot = self.inputs.get(key)
            if not slot:
                return
            for name, value in changes.items():
                if hasattr(slot, name):
                    setattr(slot, name, value)
            if "solo" in changes:
                self._solo_active = any(s.solo and s.enabled for s in self.inputs.values())
        if persist:
            self._persist("inputs", slot)
        self._mark_dirty()

    def set_output(self, key: str, persist: bool = True, **changes) -> None:
        with self._lock:
            slot = self.outputs.get(key)
            if not slot:
                return
            for name, value in changes.items():
                if name == "sources" and isinstance(value, dict):
                    slot.sources.update(value)
                elif hasattr(slot, name):
                    setattr(slot, name, value)
        if persist:
            self._persist("outputs", slot)
        self._mark_dirty()

    def set_master(self, gain: float) -> None:
        self.master_gain = float(max(0.0, min(2.0, gain)))
        if self.config:
            self.config.set("master_gain", value=self.master_gain)

    # ------------------------------------------------------------- prioridad
    def set_priority_mode(self, on: bool) -> None:
        """Activa la salida por orden de prioridad.

        En este modo solo suena **una** salida: la primera de la lista que este
        disponible. Si la principal desaparece (una bocina Bluetooth que se
        apaga, por ejemplo), se pasa sola a la siguiente.
        """
        if bool(on) == self.priority_mode:
            return
        self.priority_mode = bool(on)
        self._priority_active = None
        self._priority_switched_at = 0.0
        if self.config:
            self.config.set("priority", "enabled", value=self.priority_mode)
        self._mark_dirty()

    def set_priority_order(self, order: list[str]) -> None:
        self.priority_order = [str(k) for k in order]
        if self.config:
            self.config.set("priority", "order", value=self.priority_order)
        self._mark_dirty()

    def priority_state(self) -> dict:
        return {
            "enabled": self.priority_mode,
            "order": list(self.priority_order),
            "active": self._priority_active,
        }

    def _priority_usable(self, key: str, now: float) -> bool:
        slot = self.outputs.get(key)
        if slot is None:
            return False
        # Una salida que acaba de fallar al abrirse se considera no disponible
        # durante un tiempo (tipico: bocina Bluetooth apagada pero listada).
        return slot.next_retry <= now

    def _priority_choose(self, now: float) -> str | None:
        for key in self.priority_order:
            if self._priority_usable(key, now):
                return key
        return None

    def _update_priority(self, now: float) -> None:
        """Recalcula cual debe ser la salida activa segun la lista."""
        current = self._priority_active
        if current is not None and not self._priority_usable(current, now):
            # La activa ha dejado de servir: se cambia de inmediato.
            current = None
            self._priority_active = None

        ideal = self._priority_choose(now)
        if ideal == self._priority_active:
            return
        if current is None or (now - self._priority_switched_at) >= self.PRIORITY_SWITCH_COOLDOWN:
            self._priority_active = ideal
            self._priority_switched_at = now

    def set_limiter(self, on: bool) -> None:
        self.limiter = bool(on)
        if self.config:
            self.config.set("limiter", value=self.limiter)

    def enable_all_mics(self, on: bool = True) -> None:
        for slot in list(self.inputs.values()):
            if slot.category == "mic":
                self.set_input(slot.key, enabled=on, muted=not on)

    def disable_all(self, persist: bool = True) -> None:
        """Apaga todo. Con ``persist=False`` no se guarda en la configuracion
        (util para reiniciar el motor sin perder los ajustes del usuario)."""
        for slot in list(self.inputs.values()):
            self.set_input(slot.key, persist=persist, enabled=False)
        for slot in list(self.outputs.values()):
            self.set_output(slot.key, persist=persist, enabled=False)

    # ------------------------------------------------------------ consulta
    def snapshot(self) -> dict:
        with self._lock:
            inputs = {
                k: {
                    "enabled": s.enabled,
                    "muted": s.muted,
                    "solo": s.solo,
                    "gain": s.gain,
                    "level": s.level,
                    "peak": s.peak,
                    "error": s.error,
                    "rate": s.rate,
                    "open": s.stream is not None,
                }
                for k, s in self.inputs.items()
            }
            outputs = {
                k: {
                    "enabled": s.enabled,
                    "muted": s.muted,
                    "gain": s.gain,
                    "level": s.level,
                    "peak": s.peak,
                    "error": s.error,
                    "rate": s.rate,
                    "open": s.stream is not None,
                    "sources": dict(s.sources),
                }
                for k, s in self.outputs.items()
            }
        return {
            "inputs": inputs,
            "outputs": outputs,
            "stats": dict(self.stats),
            "priority": {
                "enabled": self.priority_mode,
                "order": list(self.priority_order),
                "active": self._priority_active,
            },
        }

    def shutdown(self) -> None:
        self._stop.set()
        self._wake.set()
        try:
            self._thread.join(timeout=2.0)
        except Exception:
            pass

    # ----------------------------------------------------------- interno
    def _mark_dirty(self) -> None:
        self._dirty = True
        self._wake.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                # Se reconcilia cuando algo cambia y, ademas, al menos una vez
                # por segundo: asi se detecta que un stream ha muerto (bocina
                # Bluetooth apagada de golpe) y el modo prioridad puede
                # reaccionar aunque nadie haya tocado nada.
                due = (time.monotonic() - self._last_reconcile) > 1.0
                if self._dirty or due or self.priority_mode:
                    self._dirty = False
                    self._last_reconcile = time.monotonic()
                    self._reconcile()
            except Exception as exc:  # nunca debe morir el hilo
                self.stats["last_error"] = f"{type(exc).__name__}: {exc}"
            self._wake.wait(0.2)
            self._wake.clear()

    def _extra_settings(self, device: dev_mod.DeviceInfo):
        if "WASAPI" in device.hostapi:
            try:
                return sd.WasapiSettings(exclusive=False, auto_convert=True)
            except Exception:
                try:
                    return sd.WasapiSettings(exclusive=False)
                except Exception:
                    return None
        return None

    def _candidate_rates(self, device: dev_mod.DeviceInfo, master: int) -> list[int]:
        raw = [master, int(round(device.default_sr)) or 48000, 48000, 44100, 32000, 22050, 16000]
        seen, out = set(), []
        for r in raw:
            if r and 8000 <= r <= 192000 and r not in seen:
                seen.add(r)
                out.append(int(r))
        return out

    def _outputs_can_use(self, outputs: list[OutputSlot], rate: int) -> bool:
        for slot in outputs:
            extra = self._extra_settings(slot.device)
            ch = 1 if slot.device.max_out == 1 else 2
            if not dev_mod.check_settings("output", slot.device.index, rate, ch, extra):
                return False
        return True

    def _pick_master_rate(self, outputs: list[OutputSlot], inputs: list[InputSlot]) -> int:
        if outputs:
            for cand in (48000, 44100):
                if self._outputs_can_use(outputs, cand):
                    return cand
            base = int(round(outputs[0].device.default_sr)) or 48000
            if self._outputs_can_use(outputs, base):
                return base
            return 48000
        if inputs:
            base = int(round(inputs[0].device.default_sr)) or 48000
            return base
        return 48000

    def _reconcile(self) -> None:
        with self._lock:
            in_slots = list(self.inputs.values())
            out_slots = list(self.outputs.values())
            enabled_inputs = [s for s in in_slots if s.enabled]
            enabled_outputs = [s for s in out_slots if s.enabled]
            self._solo_active = any(s.solo and s.enabled for s in in_slots)

        now = time.monotonic()

        # --- modo prioridad: decidir cual es la salida activa ---
        if self.priority_mode:
            self._update_priority(now)
            active_key = self._priority_active
            goal_outputs = [s for s in out_slots if s.key == active_key]
            want_by_key = {s.key: (s.key == active_key) for s in out_slots}
        else:
            goal_outputs = enabled_outputs
            want_by_key = {s.key: s.enabled for s in out_slots}

        # Frecuencia maestra: se decide cuando no hay nada abierto.
        any_open = any(s.stream is not None for s in in_slots + out_slots)
        if not any_open:
            self._master_rate = self._pick_master_rate(goal_outputs, enabled_inputs)
        elif not self._master_rate:
            self._master_rate = 48000

        # Si un dispositivo habilitado necesita otra frecuencia y no hay nada
        # sonando, se reabre todo a la frecuencia valida.
        if goal_outputs and not self._outputs_can_use(goal_outputs, self._master_rate):
            if not any_open:
                self._master_rate = int(round(goal_outputs[0].device.default_sr)) or 48000
            else:
                for slot in goal_outputs:
                    slot.error = "Este dispositivo no admite la frecuencia actual"

        # --- entradas ---
        for slot in in_slots:
            self._sync_input(slot, slot.enabled, now)
        # --- salidas ---
        for slot in out_slots:
            self._sync_output(slot, want_by_key.get(slot.key, False), now)

        with self._lock:
            self._active_inputs = [s for s in in_slots if s.stream is not None]
            self._active_outputs = [s for s in out_slots if s.stream is not None]

        self.stats.update(
            {
                "running": bool(self._active_inputs or self._active_outputs),
                "master_rate": self._master_rate,
                "inputs_open": len(self._active_inputs),
                "outputs_open": len(self._active_outputs),
                "load": self._cb_ms,
            }
        )

    def _sync_input(self, slot: InputSlot, want: bool, now: float) -> None:
        with self._lock:
            # El slot pudo eliminarse (dispositivo desconectado) mientras el
            # hilo trabajador recorria la lista anterior.
            if self.inputs.get(slot.key) is not slot:
                return
        if not want:
            self._close_input(slot)
            slot.level *= 0.5
            return
        if slot.stream is not None:
            try:
                if slot.stream.active:
                    return
            except Exception:
                pass
            self._close_input(slot)
        if now < slot.next_retry:
            return
        self._open_input(slot, now)

    def _sync_output(self, slot: OutputSlot, want: bool, now: float) -> None:
        with self._lock:
            if self.outputs.get(slot.key) is not slot:
                return
        if not want:
            self._close_output(slot)
            slot.level *= 0.5
            return
        if slot.stream is not None:
            try:
                if slot.stream.active:
                    return
            except Exception:
                pass
            self._close_output(slot)
        if now < slot.next_retry:
            return
        self._open_output(slot, now)

    def _open_input(self, slot: InputSlot, now: float) -> None:
        master = self._master_rate or 48000
        device = slot.device
        ring_frames = int(master * RING_SECONDS)
        last_error = ""

        for rate in self._candidate_rates(device, master):
            for channels in ({1, 2} if device.max_in >= 2 else {1}):
                extra = self._extra_settings(device)
                try:
                    stream = sd.InputStream(
                        device=device.index,
                        channels=channels,
                        samplerate=rate,
                        dtype="float32",
                        blocksize=0,
                        latency="low",
                        extra_settings=extra,
                        callback=self._make_input_callback(slot),
                    )
                except Exception as exc:
                    last_error = f"{type(exc).__name__}: {exc}"
                    continue
                slot.stream = stream
                slot.rate = rate
                slot.ring = RingBuffer(ring_frames)
                slot.resampler = None if rate == master else LinearResampler(master / float(rate))
                slot.error = ""
                slot.open_attempts = 0
                return

        slot.open_attempts += 1
        slot.error = last_error or "No se pudo abrir la entrada"
        slot.next_retry = now + min(self._retry_cap(), 1.5 * slot.open_attempts)

    def _open_output(self, slot: OutputSlot, now: float) -> None:
        master = self._master_rate or 48000
        device = slot.device
        last_error = ""
        for rate in self._candidate_rates(device, master):
            for channels in ({1, 2} if device.max_out >= 2 else {1}):
                extra = self._extra_settings(device)
                try:
                    stream = sd.OutputStream(
                        device=device.index,
                        channels=channels,
                        samplerate=rate,
                        dtype="float32",
                        blocksize=0,
                        latency="low",
                        extra_settings=extra,
                        callback=self._make_output_callback(slot),
                    )
                except Exception as exc:
                    last_error = f"{type(exc).__name__}: {exc}"
                    continue
                slot.stream = stream
                slot.rate = rate
                slot.cursors = {}
                slot.gains = {}
                slot.cur_gain = -1.0
                slot.error = ""
                slot.open_attempts = 0
                return
        slot.open_attempts += 1
        slot.error = last_error or "No se pudo abrir la salida"
        slot.next_retry = now + min(self._retry_cap(), 1.5 * slot.open_attempts)

    def _retry_cap(self) -> float:
        """En modo prioridad se reintenta antes, para volver a la principal
        en cuanto vuelva a estar disponible."""
        return self.RETRY_CAP_PRIORITY if self.priority_mode else self.RETRY_CAP_NORMAL

    def _close_input(self, slot: InputSlot) -> None:
        stream, slot.stream = slot.stream, None
        if stream is not None:
            try:
                stream.abort(ignore_errors=True)
            except Exception:
                try:
                    stream.stop()
                    stream.close()
                except Exception:
                    pass
        slot.ring = None
        slot.resampler = None
        slot.rate = 0

    def _close_output(self, slot: OutputSlot) -> None:
        stream, slot.stream = slot.stream, None
        if stream is not None:
            try:
                stream.abort(ignore_errors=True)
            except Exception:
                try:
                    stream.stop()
                    stream.close()
                except Exception:
                    pass
        slot.rate = 0
        slot.cursors = {}
        slot.gains = {}
        slot.cur_gain = -1.0

    # ----------------------------------------------------------- callbacks
    def _make_input_callback(self, slot: InputSlot):
        def callback(indata, frames, time_info, status):  # noqa: ARG001
            t0 = time.perf_counter()
            try:
                if status:
                    slot.xruns += 1
                x = np.asarray(indata, dtype=np.float32)
                if x.ndim == 1:
                    x = x[:, None]
                if x.shape[1] == 1:
                    x = np.repeat(x, 2, axis=1)
                elif x.shape[1] > 2:
                    x = x[:, :2]
                peak = float(np.max(np.abs(x))) if x.size else 0.0
                slot.peak = peak
                slot.level = peak if peak > slot.level else slot.level * 0.82
                if slot.resampler is not None and not slot.resampler.passthrough:
                    x = slot.resampler.process(x)
                    if x is None or x.shape[0] == 0:
                        return
                if slot.ring is not None:
                    slot.ring.write(x)
            except Exception as exc:
                slot.error = f"{type(exc).__name__}: {exc}"
            finally:
                dt = (time.perf_counter() - t0) * 1000.0
                self._cb_ms = self._cb_ms * 0.9 + dt * 0.1

        return callback

    def _make_output_callback(self, slot: OutputSlot):
        def callback(outdata, frames, time_info, status):  # noqa: ARG001
            t0 = time.perf_counter()
            try:
                if status:
                    slot.xruns += 1
                inputs = self._active_inputs
                mix = np.zeros((frames, 2), dtype=np.float32)
                solo_active = self._solo_active

                for src in inputs:
                    if solo_active and not src.solo:
                        continue
                    cat = src.category
                    if cat == "music" and not slot.sources.get("music", True):
                        continue
                    if cat == "mic" and not slot.sources.get("mic", True):
                        continue
                    ring = src.ring
                    if ring is None:
                        continue
                    cursor = slot.cursors.get(src.key, 0)
                    data, cursor = ring.read(frames, cursor)
                    slot.cursors[src.key] = cursor
                    if data is None:
                        continue
                    target = src.effective_gain
                    prev = slot.gains.get(src.key, target)
                    ramp, applied = _ramp_gain(prev, target, frames)
                    slot.gains[src.key] = applied
                    if ramp is not None:
                        data = data * ramp
                    elif applied != 1.0:
                        data = data * applied
                    mix += data

                target = slot.effective_gain * self.master_gain
                if slot.cur_gain < 0:
                    slot.cur_gain = target
                ramp, applied = _ramp_gain(slot.cur_gain, target, frames)
                slot.cur_gain = applied
                if ramp is not None:
                    mix *= ramp
                elif applied != 1.0:
                    mix *= applied

                if self.limiter:
                    _soft_clip(mix)
                else:
                    np.clip(mix, -1.0, 1.0, out=mix)

                peak = float(np.max(np.abs(mix))) if mix.size else 0.0
                slot.peak = peak
                slot.level = peak if peak > slot.level else slot.level * 0.82

                out = outdata if isinstance(outdata, np.ndarray) else np.frombuffer(outdata, dtype=np.float32)
                if out.shape[1] == 1:
                    out[:] = mix[:, :1]
                else:
                    out[:] = mix
            except Exception as exc:
                slot.error = f"{type(exc).__name__}: {exc}"
                try:
                    outdata.fill(0)
                except Exception:
                    pass
            finally:
                dt = (time.perf_counter() - t0) * 1000.0
                self._cb_ms = self._cb_ms * 0.9 + dt * 0.1

        return callback


def default_output_latency_ms(rate: int) -> float:
    return 1000.0 * REF_BLOCK / max(1, rate)
