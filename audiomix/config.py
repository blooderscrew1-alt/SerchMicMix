"""Persistencia de la configuracion del usuario.

Todo se guarda en %APPDATA%\\AudioMix\\config.json y es tolerante a fallos:
si el archivo esta corrupto se ignora y se empieza de cero. Las entradas de
dispositivos que ya no existan simplemente se ignoran al arrancar, de modo que
una misma configuracion sirve en cualquier PC.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

APP_NAME = "AudioMix"


def config_dir() -> Path:
    """Carpeta de datos del usuario (se crea si no existe)."""
    base = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    path = Path(base) / APP_NAME
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        path = Path(tempfile.gettempdir()) / APP_NAME
        path.mkdir(parents=True, exist_ok=True)
    return path


def config_path() -> Path:
    return config_dir() / "config.json"


def log_path() -> Path:
    return config_dir() / "error.log"


def default_config() -> dict[str, Any]:
    return {
        "version": 1,
        "master_gain": 0.9,
        "show_all_apis": False,
        "limiter": True,
        "inputs": {},
        "outputs": {},
        # Prioridad de salidas: la primera de "order" que este disponible es la
        # que suena. "names" guarda el nombre visible para poder seguir
        # mostrando un dispositivo que ahora mismo no esta conectado (una
        # bocina Bluetooth apagada, por ejemplo) y "removed" evita que vuelvan
        # a anadirse solos los que el usuario haya quitado a proposito.
        "priority": {"enabled": False, "order": [], "names": {}, "removed": []},
        "window": {"w": 1180, "h": 760},
        "vbcable": {"last_url": "", "install_dir": "", "pack_version": ""},
    }


class Config:
    """Almacen clave-valor con guardado automatico y seguro entre hilos."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._path = config_path()
        self.data = default_config()
        self.load()

    # ------------------------------------------------------------------ io
    def load(self) -> None:
        try:
            if self._path.exists():
                raw = json.loads(self._path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    merged = default_config()
                    _deep_update(merged, raw)
                    with self._lock:
                        self.data = merged
        except Exception:
            # Configuracion ilegible: seguimos con los valores por defecto.
            with self._lock:
                self.data = default_config()

    def save(self) -> None:
        try:
            with self._lock:
                payload = json.dumps(self.data, indent=2, ensure_ascii=False)
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(payload, encoding="utf-8")
            os.replace(tmp, self._path)
        except Exception:
            pass

    # --------------------------------------------------------------- access
    def get(self, *keys: str, default: Any = None) -> Any:
        with self._lock:
            cur: Any = self.data
            for key in keys:
                if not isinstance(cur, dict) or key not in cur:
                    return default
                cur = cur[key]
            return cur

    def set(self, *keys: str, value: Any, save: bool = True) -> None:
        if not keys:
            return
        with self._lock:
            cur = self.data
            for key in keys[:-1]:
                nxt = cur.get(key)
                if not isinstance(nxt, dict):
                    nxt = {}
                    cur[key] = nxt
                cur = nxt
            cur[keys[-1]] = value
        if save:
            self.save()

    def forget_device(self, section: str, key: str) -> None:
        with self._lock:
            bucket = self.data.get(section)
            if isinstance(bucket, dict):
                bucket.pop(key, None)
        self.save()


def _deep_update(base: dict, extra: dict) -> None:
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_update(base[key], value)
        else:
            base[key] = value
