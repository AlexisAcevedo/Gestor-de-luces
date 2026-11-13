"""Enumeracion de dispositivos de salida con soporte WASAPI Loopback en Windows.

`pyaudiowpatch` expone el listado de endpoints loopback del mezclador del sistema. Este
modulo aisla esa consulta (y su degradacion a un descriptor por defecto cuando el
controlador no responde) del ciclo de vida del stream de captura, de modo que el
muestreador pueda listar dispositivos sin abrir audio.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from gestor_luces.adapters.audio.wasapi_session import (
    WASAPI_DEVICE_ERRORS,
    _release_native_resource,
)

_LOGGER = logging.getLogger(__name__)

_DEFAULT_DEVICE: dict[str, Any] = {
    "index": -1,
    "name": "System Audio Loopback",
    "label": "Default System Output (WASAPI Loopback)",
    "sample_rate": 48000,
    "channels": 2,
    "is_default": True,
}


def enumerate_loopback_devices(create_pyaudio: Callable[[], Any]) -> list[dict[str, Any]]:
    """Enumera los endpoints loopback disponibles, con un descriptor por defecto de reserva."""
    devices: list[dict[str, Any]] = []
    pa = None
    try:
        pa = create_pyaudio()
        default_index: int | None = None
        try:
            default_info = pa.get_default_wasapi_loopback()
            if isinstance(default_info, dict) and "index" in default_info:
                default_index = int(default_info["index"])
        except WASAPI_DEVICE_ERRORS:
            # Sin endpoint por defecto la lista sigue siendo util: ningun item lleva la
            # etiqueta "Default ·".
            _LOGGER.debug("Default loopback endpoint unavailable.", exc_info=True)
            default_index = None

        gen_fn = getattr(pa, "get_loopback_device_info_generator", None)
        raw_list = list(gen_fn()) if callable(gen_fn) else []

        for info in raw_list:
            idx = int(info.get("index", -1))
            name = str(info.get("name", f"Loopback {idx}")).strip()
            rate = int(float(info.get("defaultSampleRate", 48000)))
            ch = max(1, int(info.get("maxInputChannels", 2) or 2))
            is_def = default_index is not None and idx == default_index
            prefix = "Default · " if is_def else ""
            devices.append(
                {
                    "index": idx,
                    "name": name,
                    "label": f"{prefix}{name} ({rate} Hz)",
                    "sample_rate": rate,
                    "channels": ch,
                    "is_default": is_def,
                }
            )
    except WASAPI_DEVICE_ERRORS:
        _LOGGER.debug(
            "WASAPI loopback device enumeration fell back to the default descriptor.",
            exc_info=True,
        )
    finally:
        if pa is not None:
            _release_native_resource(pa, "terminate", "terminating PyAudio after enumeration")

    if not devices:
        return [dict(_DEFAULT_DEVICE)]

    devices.sort(key=lambda d: (not bool(d.get("is_default")), int(d.get("index", 0))))
    return devices
