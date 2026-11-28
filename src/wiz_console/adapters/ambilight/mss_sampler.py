"""Adaptador de muestreo de pantalla basado en `mss` y `numpy` para el modo Ambilight.

En Windows, `mss` utiliza contextos de dispositivo GDI (`HDC`) asociados a `threading.local()`.
Cuando el bucle de eventos `asyncio` delega las capturas a un pool de hilos (`asyncio.to_thread`),
reutilizar una unica instancia de `mss.mss()` creada en el hilo principal provoca errores de
acceso a descriptores GDI inexistentes en los hilos trabajadores. Por ello abrimos un contexto
`with self._sct_factory() as sct:` en cada muestreo y reducimos la matriz BGRA mediante un
`stride` espacial antes de calcular el color dominante o promedio en `numpy`.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import mss
import numpy as np

from wiz_console.domain.value_objects import Color

_LOGGER = logging.getLogger(__name__)

VALID_COLOR_MODES = ("vibrant", "average")
DEFAULT_MONITOR_DESCRIPTOR: dict[str, Any] = {
    "index": 1,
    "label": "Display 1 (Primary)",
    "width": 1920,
    "height": 1080,
}


def extract_color_and_brightness_from_bgra(
    bgra: bytes | bytearray | memoryview,
    width: int,
    height: int,
    mode: str = "vibrant",
    stride: int = 16,
) -> tuple[Color, int]:
    """Extrae el color representativo y el brillo sugerido (10-100%) desde un buffer BGRA crudo.

    Separar el calculo matricial de la llamada al sistema operativo permite verificar con
    precision matematica tanto el modo `average` como el modo `vibrant` usando fotogramas
    sinteticos deterministas en las pruebas automatizadas.
    """
    if width <= 0 or height <= 0:
        return Color(0, 0, 0), 10

    expected_bytes = int(width) * int(height) * 4
    raw_view = memoryview(bgra).cast("B")
    if len(raw_view) < expected_bytes:
        return Color(0, 0, 0), 10

    step = max(1, int(stride))
    arr = np.frombuffer(raw_view[:expected_bytes], dtype=np.uint8).reshape((height, width, 4))[
        ::step, ::step
    ]
    if arr.size == 0:
        return Color(0, 0, 0), 10

    # mss entrega los pixeles en orden BGRA (canal 0 = Azul, canal 1 = Verde, canal 2 = Rojo).
    # Luminancia relativa ITU-R BT.709 derivada de las medias por canal sin copias float32.
    mean_b = float(np.mean(arr[:, :, 0], dtype=np.float64))
    mean_g = float(np.mean(arr[:, :, 1], dtype=np.float64))
    mean_r = float(np.mean(arr[:, :, 2], dtype=np.float64))
    mean_lum = (0.2126 * mean_r + 0.7152 * mean_g + 0.0722 * mean_b) / 255.0
    suggested_brightness = max(10, min(100, round(10.0 + mean_lum * 90.0)))

    normalized_mode = mode.strip().lower() if isinstance(mode, str) else "average"
    if normalized_mode == "vibrant":
        b = arr[:, :, 0].astype(np.float32)
        g = arr[:, :, 1].astype(np.float32)
        r = arr[:, :, 2].astype(np.float32)
        max_c = np.maximum(r, g)
        np.maximum(max_c, b, out=max_c)
        min_c = np.minimum(r, g)
        np.minimum(min_c, b, out=min_c)

        # Ponderamos cada pixel por su saturacion cromatica (+16 de base para evitar divisiones
        # por cero en pantallas completamente grises o negras) usando producto punto en C.
        weights = max_c
        weights -= min_c
        weights += 16.0
        weight_sum = float(np.sum(weights))
        raw_r = float(np.vdot(r, weights)) / weight_sum
        raw_g = float(np.vdot(g, weights)) / weight_sum
        raw_b = float(np.vdot(b, weights)) / weight_sum

        # Realzamos ligeramente la saturacion respecto a la media acromatica para que el LED
        # fisico reproduzca matices intensos en lugar de tonos apastelados.
        avg_channel = (raw_r + raw_g + raw_b) / 3.0
        boost = 1.22
        out_r = round(avg_channel + (raw_r - avg_channel) * boost)
        out_g = round(avg_channel + (raw_g - avg_channel) * boost)
        out_b = round(avg_channel + (raw_b - avg_channel) * boost)
    else:
        out_r = round(mean_r)
        out_g = round(mean_g)
        out_b = round(mean_b)

    clamped_r = max(0, min(255, int(out_r)))
    clamped_g = max(0, min(255, int(out_g)))
    clamped_b = max(0, min(255, int(out_b)))
    return Color(r=clamped_r, g=clamped_g, b=clamped_b), suggested_brightness


class MssScreenSampler:
    """Implementacion del puerto `ScreenSampler` usando `mss` y submuestreo con `numpy`."""

    def __init__(
        self,
        stride: int = 16,
        sct_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._stride = max(1, int(stride))
        default_factory = getattr(mss, "MSS", mss.mss)
        self._sct_factory = sct_factory or default_factory
        self._cached_monitors: list[dict[str, Any]] | None = None

    def list_monitors(self, refresh: bool = False) -> list[dict[str, Any]]:
        """Enumera los monitores activos devolviendo etiquetas legibles para la interfaz."""
        cached = self._cached_monitors
        if cached is not None and not refresh:
            return [dict(mon) for mon in cached]

        try:
            with self._sct_factory() as sct:
                raw_monitors = list(sct.monitors)
        except (OSError, mss.exception.ScreenShotError):
            # `mss` solo falla asi cuando no puede abrir un contexto GDI: se informa un
            # descriptor sintetico para que la UI siga mostrando una pantalla.
            _LOGGER.debug(
                "Monitor enumeration failed; reporting a synthetic display.", exc_info=True
            )
            return [dict(DEFAULT_MONITOR_DESCRIPTOR)]

        if not raw_monitors:
            return [dict(DEFAULT_MONITOR_DESCRIPTOR)]

        descriptors: list[dict[str, Any]] = []
        physical_monitors = raw_monitors[1:]
        for idx, mon in enumerate(physical_monitors, start=1):
            width = int(mon.get("width", 1920))
            height = int(mon.get("height", 1080))
            descriptors.append(
                {
                    "index": idx,
                    "label": f"Display {idx} ({width}x{height})",
                    "width": width,
                    "height": height,
                }
            )

        # Cuando existen multiples pantallas fisicas, ofrecemos tambien el indice 0 de mss
        # que abarca el escritorio virtual combinado ("All displays").
        if len(physical_monitors) > 1:
            combined = raw_monitors[0]
            c_width = int(combined.get("width", 1920))
            c_height = int(combined.get("height", 1080))
            descriptors.append(
                {
                    "index": 0,
                    "label": f"All displays ({c_width}x{c_height})",
                    "width": c_width,
                    "height": c_height,
                }
            )

        if not descriptors:
            first = raw_monitors[0]
            w = int(first.get("width", 1920))
            h = int(first.get("height", 1080))
            descriptors.append(
                {
                    "index": 1,
                    "label": f"Display 1 ({w}x{h})",
                    "width": w,
                    "height": h,
                }
            )

        self._cached_monitors = [dict(mon) for mon in descriptors]
        return [dict(mon) for mon in self._cached_monitors]

    def sample_frame(
        self,
        monitor_index: int = 1,
        mode: str = "vibrant",
    ) -> tuple[Color, int]:
        """Captura el monitor solicitado y devuelve `(Color, brillo_sugerido_10_a_100)`."""
        try:
            with self._sct_factory() as sct:
                monitors = list(sct.monitors)
                if not monitors:
                    return Color(0, 0, 0), 10

                idx = int(monitor_index)
                if idx < 0 or idx >= len(monitors):
                    idx = 1 if len(monitors) > 1 else 0

                shot = sct.grab(monitors[idx])
                return extract_color_and_brightness_from_bgra(
                    bgra=shot.bgra,
                    width=int(shot.width),
                    height=int(shot.height),
                    mode=mode,
                    stride=self._stride,
                )
        except (OSError, mss.exception.ScreenShotError):
            # Captura fallida por bloqueo de escritorio, UAC o cambio de topologia GDI:
            # invalidamos la cache de monitores y devolvemos reposo sin cruzar la frontera.
            _LOGGER.debug("Screen capture failed; returning standby frame.", exc_info=True)
            self._cached_monitors = None
            return Color(0, 0, 0), 10

    def sample_average_color(
        self,
        monitor_index: int = 1,
        mode: str = "average",
    ) -> Color:
        """Cumple el contrato `ScreenSampler` devolviendo el color extraido de la pantalla."""
        color, _ = self.sample_frame(monitor_index=monitor_index, mode=mode)
        return color

    def close(self) -> None:
        """Limpia la cache de monitores del muestreador de pantalla."""
        self._cached_monitors = None
