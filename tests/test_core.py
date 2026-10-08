"""Pruebas basicas de serchmicmix.

Se ejecutan sin interfaz grafica:

    python tests\\test_core.py

Las pruebas de audio real abren los dispositivos predeterminados durante un
par de segundos y fuerzan la mezcla a silencio, de modo que no se oye nada.
"""

from __future__ import annotations

import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from serchmicmix.engine import LinearResampler, RingBuffer  # noqa: E402

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    status = "OK  " if condition else "FALLA"
    print(f"[{status}] {name}" + (f"  ({detail})" if detail else ""))
    if not condition:
        FAILURES.append(name)


# --------------------------------------------------------------------------
def test_ring_buffer() -> None:
    rb = RingBuffer(1000)
    check("anillo vacio devuelve None", rb.read(100, 0)[0] is None)

    block = np.ones((100, 2), dtype=np.float32) * 0.5
    rb.write(block)
    data, cursor = rb.read(100, 0)
    check("anillo lee lo escrito", data is not None and data.shape == (100, 2))
    check("anillo conserva el valor", data is not None and abs(float(data.mean()) - 0.5) < 1e-6)

    # Escritura envolvente (mas de una vuelta completa)
    for _ in range(20):
        rb.write(block)
    data2, cursor2 = rb.read(100, cursor)
    check("anillo sobrevive al desbordamiento", data2 is not None and data2.shape == (100, 2))

    # Cursor muy antiguo: debe resincronizar sin fallar
    data3, cursor3 = rb.read(100, 1)
    check("anillo resincroniza cursor antiguo", data3 is not None and cursor3 > 0)


def test_resampler() -> None:
    rs = LinearResampler(48000 / 44100.0)
    total_out = 0
    total_in = 0
    rng = np.random.default_rng(0)
    for _ in range(100):
        x = rng.standard_normal((441, 2)).astype(np.float32)
        total_in += x.shape[0]
        out = rs.process(x)
        if out is not None:
            total_out += out.shape[0]
    expected = total_in * (48000 / 44100.0)
    error = abs(total_out - expected) / expected
    check("remuestreador 44.1k->48k", error < 0.01, f"{total_in} -> {total_out} (error {error:.2%})")

    rs2 = LinearResampler(1.0)
    x = rng.standard_normal((256, 2)).astype(np.float32)
    check("remuestreador pasa directo a 1:1", rs2.process(x) is x)

    rs3 = LinearResampler(0.5)
    out3 = None
    for _ in range(10):
        r = rs3.process(rng.standard_normal((100, 2)).astype(np.float32))
        if r is not None:
            out3 = r if out3 is None else np.concatenate((out3, r))
    check("remuestreador 96k->48k reduce a la mitad", out3 is not None and abs(out3.shape[0] - 500) < 12,
          f"{out3.shape[0] if out3 is not None else 0} muestras")


def test_devices() -> None:
    from serchmicmix import devices as dev_mod

    ins, outs = dev_mod.build_registry()
    check("se detectan dispositivos", len(ins) + len(outs) > 0, f"{len(ins)} entradas / {len(outs)} salidas")
    check(
        "ningun dispositivo duplicado",
        len({d.key for d in ins}) == len(ins) and len({d.key for d in outs}) == len(outs),
    )
    check(
        "sin dispositivos comodin",
        not any("mapper" in dev_mod.norm(d.name) or "asignador" in dev_mod.norm(d.name) for d in ins + outs),
    )
    for d in ins:
        check(f"entrada con canales: {d.name[:32]}", d.max_in >= 1)
    for d in outs:
        check(f"salida con canales: {d.name[:32]}", d.max_out >= 1)

    eps = dev_mod.find_virtual_endpoints(outs, ins)
    print(f"       cable virtual instalado: {eps['installed']}")
    print(f"       extremos: {eps['render']} / {eps['capture']}")


def test_engine_live() -> None:
    from serchmicmix import devices as dev_mod
    from serchmicmix.engine import AudioEngine

    ins, outs = dev_mod.build_registry()
    if not ins or not outs:
        print("[SALTA] prueba en vivo: hacen falta entrada y salida")
        return

    engine = AudioEngine()
    engine.set_master(0.0)  # silencio absoluto: no se oye nada
    engine.sync_devices(ins, outs)

    in_key = next(d.key for d in ins if not d.virtual) if any(not d.virtual for d in ins) else ins[0].key
    out_key = next(d.key for d in outs if not d.virtual) if any(not d.virtual for d in outs) else outs[0].key

    engine.set_input(in_key, enabled=True, muted=False)
    engine.set_output(out_key, enabled=True, muted=False)

    peak = 0.0
    deadline = time.time() + 4.0
    while time.time() < deadline:
        snap = engine.snapshot()
        stats = snap["stats"]
        if stats["inputs_open"] and stats["outputs_open"]:
            peak = max(peak, snap["inputs"][in_key]["level"], snap["outputs"][out_key]["level"])
            if peak > 0:
                break
        time.sleep(0.15)

    snap = engine.snapshot()
    check("entrada abierta en vivo", snap["inputs"][in_key]["open"],
          snap["inputs"][in_key]["error"] or f"rate={snap['inputs'][in_key]['rate']}")
    check("salida abierta en vivo", snap["outputs"][out_key]["open"],
          snap["outputs"][out_key]["error"] or f"rate={snap['outputs'][out_key]['rate']}")
    check("no hay errores del motor", not snap["stats"]["last_error"], snap["stats"]["last_error"])
    print(f"       frecuencia maestra: {snap['stats']['master_rate']} Hz, "
          f"carga {snap['stats']['load']:.2f} ms/bloque")

    engine.set_input(in_key, enabled=False)
    engine.set_output(out_key, enabled=False)
    time.sleep(0.6)
    snap = engine.snapshot()
    check("los streams se cierran al apagar", not snap["inputs"][in_key]["open"] and not snap["outputs"][out_key]["open"])
    engine.shutdown()


def test_config_roundtrip() -> None:
    from serchmicmix.config import Config, config_path

    path = config_path()
    writable = True
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        probe = path.parent / "_probe_escritura.tmp"
        probe.write_text("x", encoding="utf-8")
        probe.unlink()
    except Exception as exc:  # entorno restringido (sandbox, perfil de solo lectura)
        writable = False
        print(f"[SALTA] la carpeta de configuracion no es escribible: {type(exc).__name__}")

    if writable:
        cfg = Config()
        cfg.set("inputs", "PRUEBA::Dispositivo", value={"gain": 0.42, "enabled": True})
        cfg2 = Config()
        check("la configuracion persiste",
              abs(float(cfg2.get("inputs", "PRUEBA::Dispositivo", "gain", default=0)) - 0.42) < 1e-6)
        cfg.forget_device("inputs", "PRUEBA::Dispositivo")
        check("se olvida el dispositivo", cfg.get("inputs", "PRUEBA::Dispositivo", default=None) is None)

        # Configuracion corrupta: no debe romper la aplicacion.
        backup = path.read_text(encoding="utf-8") if path.exists() else None
        try:
            path.write_text("{ esto no es json", encoding="utf-8")
            cfg3 = Config()
            check("configuracion corrupta no rompe", cfg3.get("master_gain", default=None) is not None)
        finally:
            if backup is not None:
                path.write_text(backup, encoding="utf-8")
            else:
                path.unlink(missing_ok=True)

    # Los valores por defecto deben existir siempre, escriba o no.
    cfg4 = Config()
    check("hay valores por defecto", cfg4.get("master_gain", default=None) is not None)
    check("existe la seccion de prioridad",
          isinstance(cfg4.get("priority", default=None), dict)
          and "order" in cfg4.get("priority", default={}))


def test_vbcable_url() -> None:
    from serchmicmix import vbcable

    check("arquitectura reconocida", vbcable.architecture() in ("AMD64", "ARM64", "X86"), vbcable.architecture())
    check("build de Windows leido", vbcable.windows_build() > 0, str(vbcable.windows_build()))
    try:
        url, name = vbcable.fetch_latest_pack(timeout=20)
        check("URL de VB-Cable obtenida", url.startswith("https://") and name.endswith(".zip"), f"{name} -> {url}")
    except Exception as exc:
        print(f"[SALTA] sin conexion a vb-audio.com ({type(exc).__name__})")


def test_vbcable_names() -> None:
    """La deteccion del cable no debe depender del idioma ni del nombre exacto."""
    from serchmicmix import devices as dev_mod

    renders = [
        "CABLE Input (VB-Audio Virtual Cable)",
        "CABLE Input",
        "CABLE-A Input (VB-Audio Cable A)",
        "CABLE-B Input",
        "CABLE In 16ch (VB-Audio Virtual Cable)",
    ]
    captures = [
        "CABLE Output (VB-Audio Virtual Cable)",
        "CABLE Output",
        "CABLE-A Output (VB-Audio Cable A)",
    ]
    for name in renders:
        check(f"detecta salida de cable: {name[:34]}",
              dev_mod.is_cable_render(name) and dev_mod.is_virtual_device(name))
    for name in captures:
        check(f"detecta entrada de cable: {name[:34]}",
              dev_mod.is_cable_capture(name) and dev_mod.is_virtual_device(name))

    # Otros cables virtuales de VB-Audio (productos distintos, mismo uso)
    for name in ["VoiceMeeter Input (VB-Audio VoiceMeeter VAIO)",
                 "VoiceMeeter Output (VB-Audio VoiceMeeter VAIO)",
                 "VoiceMeeter Aux Input (VB-Audio VoiceMeeter AUX VAIO)",
                 "Hi-Fi Cable Input (VB-Audio Hi-Fi Cable)",
                 "Hi-Fi Cable Output (VB-Audio Hi-Fi Cable)"]:
        check(f"reconoce otro cable virtual: {name[:30]}", dev_mod.is_virtual_device(name))

    for name in ["Altavoces (Realtek(R) Audio)", "Microphone (USB Audio Device)",
                 "Speakers (2- High Definition Audio Device)", "Micrófono (Steam Streaming Microphone)",
                 "2 - L1510M (AMD High Definition Audio Device)"]:
        check(f"no confunde hardware real: {name[:34]}", not dev_mod.is_virtual_device(name))

    # find_virtual_endpoints con dispositivos simulados
    fake_out = [
        dev_mod.DeviceInfo(0, "Altavoces (Realtek)", "Windows WASAPI", 0, 2, 48000, True, "output"),
        dev_mod.DeviceInfo(1, "CABLE Input (VB-Audio Virtual Cable)", "Windows WASAPI", 0, 2, 48000, False, "output"),
    ]
    fake_in = [
        dev_mod.DeviceInfo(2, "Micrófono (USB)", "Windows WASAPI", 1, 0, 48000, True, "input"),
        dev_mod.DeviceInfo(3, "CABLE Output (VB-Audio Virtual Cable)", "Windows WASAPI", 2, 0, 48000, False, "input"),
    ]
    eps = dev_mod.find_virtual_endpoints(fake_out, fake_in)
    check("empareja los extremos del cable", eps["installed"] and eps["render"].index == 1 and eps["capture"].index == 3)

    # Si solo hubiera VoiceMeeter, tambien debe servir como cable
    vm_out = [dev_mod.DeviceInfo(4, "VoiceMeeter Input (VB-Audio VoiceMeeter VAIO)",
                                 "Windows WASAPI", 0, 2, 48000, False, "output")]
    vm_in = [dev_mod.DeviceInfo(5, "VoiceMeeter Output (VB-Audio VoiceMeeter VAIO)",
                                "Windows WASAPI", 2, 0, 48000, False, "input")]
    eps2 = dev_mod.find_virtual_endpoints(vm_out, vm_in)
    check("VoiceMeeter sirve como cable virtual", eps2["installed"])


def test_priority_failover() -> None:
    """Comprueba que la salida prioritaria conmuta sola cuando la principal cae.

    Se simula que la principal deja de estar disponible marcando su reintento,
    que es exactamente lo que ocurre cuando una bocina Bluetooth se apaga o
    cuando Windows no consigue abrirla.
    """
    import time

    from serchmicmix import devices as dev_mod
    from serchmicmix.engine import AudioEngine

    ins, outs = dev_mod.build_registry()
    if len(outs) < 2:
        print("[SALTA] hacen falta al menos 2 salidas para probar la prioridad")
        return

    a, b = outs[0], outs[1]
    engine = AudioEngine()
    engine.set_master(0.0)  # silencio: la prueba no suena
    engine.sync_devices(ins, outs)
    engine.set_priority_order([a.key, b.key])

    # --- seleccion inicial: debe elegir la primera (la principal) ---
    engine.set_priority_mode(True)
    _wait_for(lambda: engine.priority_state()["active"] == a.key, timeout=8.0)
    active = engine.priority_state()["active"]
    check("elige la principal al activar la prioridad", active == a.key, f"activa={active}")

    opened = _wait_for(lambda: engine.snapshot()["outputs"][a.key]["open"], timeout=8.0)
    check("la principal abre su stream", bool(opened))

    # --- la principal "cae": debe pasar a la secundaria ---
    engine.outputs[a.key].next_retry = time.monotonic() + 120.0
    switched = _wait_for(lambda: engine.priority_state()["active"] == b.key, timeout=12.0)
    check("conmuta a la secundaria cuando la principal no esta disponible", bool(switched),
          f"activa={engine.priority_state()['active']}")

    fallback_open = _wait_for(lambda: engine.snapshot()["outputs"][b.key]["open"], timeout=8.0)
    check("la secundaria abre su stream", bool(fallback_open))

    # --- la principal vuelve: debe recuperarla sola ---
    engine.outputs[a.key].next_retry = 0.0
    recovered = _wait_for(lambda: engine.priority_state()["active"] == a.key, timeout=15.0)
    check("vuelve a la principal en cuanto reaparece", bool(recovered),
          f"activa={engine.priority_state()['active']}")

    # --- la secundaria no debe quedarse sonando a la vez ---
    check("solo suena una salida a la vez",
          not engine.snapshot()["outputs"][b.key]["open"])

    # --- reordenar: al subir la secundaria, pasa a ser la principal ---
    engine.set_priority_order([b.key, a.key])
    now_primary = _wait_for(lambda: engine.priority_state()["active"] == b.key, timeout=12.0)
    check("al reordenar manda la nueva primera de la lista", bool(now_primary),
          f"activa={engine.priority_state()['active']}")

    # --- desactivar la prioridad devuelve el control manual ---
    engine.set_priority_mode(False)
    time.sleep(1.5)
    check("al desactivar no fuerza ninguna salida",
          engine.priority_state()["active"] is None)

    engine.shutdown()


def _wait_for(predicate, timeout: float = 8.0, step: float = 0.15) -> bool:
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if predicate():
                return True
        except Exception:
            pass
        time.sleep(step)
    return False


if __name__ == "__main__":
    print("=" * 66)
    print(" Serch MicMix - pruebas del nucleo")
    print("=" * 66)
    for fn in (test_ring_buffer, test_resampler, test_devices, test_config_roundtrip,
               test_vbcable_url, test_vbcable_names, test_engine_live, test_priority_failover):
        print(f"\n--- {fn.__name__} ---")
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            import traceback

            traceback.print_exc()
            FAILURES.append(f"{fn.__name__}: {exc}")

    print("\n" + "=" * 66)
    if FAILURES:
        print(f" FALLOS: {len(FAILURES)}")
        for f in FAILURES:
            print("   -", f)
        sys.exit(1)
    print(" TODAS LAS PRUEBAS PASARON")
