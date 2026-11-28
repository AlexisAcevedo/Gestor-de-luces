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
from collections.abc import Callable, Iterable
from typing import Any

import mss
import numpy as np

from wiz_console.domain.value_objects import Color

_LOGGER = logging.getLogger(__name__)

VALID_COLOR_MODES = ("vibrant", "average")
VALID_AMBILIGHT_REGIONS = ("full", "left", "right", "top", "bottom", "center")
DEFAULT_MONITOR_DESCRIPTOR: dict[str, Any] = {
    "index": 1,
    "label": "Display 1 (Primary)",
    "width": 1920,
    "height": 1080,
}


def _compute_color_from_array(arr: np.ndarray, mode: str) -> tuple[Color, int]:
    """Compute representative RGB color and suggested brightness (10-100) from BGRA array."""
    if arr.size == 0:
        return Color(0, 0, 0), 10

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

        weights = max_c
        weights -= min_c
        weights += 16.0
        weight_sum = float(np.sum(weights))
        raw_r = float(np.vdot(r, weights)) / weight_sum
        raw_g = float(np.vdot(g, weights)) / weight_sum
        raw_b = float(np.vdot(b, weights)) / weight_sum

        avg_channel = (raw_r + raw_g + raw_b) / 3.0
        boost = 1.22
        out_r = round(avg_channel + (raw_r - avg_channel) * boost)
        out_g = round(avg_channel + (raw_g - avg_channel) * boost)
        out_b = round(avg_channel + (raw_b - avg_channel) * boost)
    else:
        out_r = round(mean_r)
        out_g = round(mean_g)
        out_b = round(mean_b)

    return (
        Color(
            r=max(0, min(255, int(out_r))),
            g=max(0, min(255, int(out_g))),
            b=max(0, min(255, int(out_b))),
        ),
        suggested_brightness,
    )


def detect_letterbox_bounds(
    arr: np.ndarray,
    luma_threshold: float = 12.0,
    max_crop_ratio: float = 0.28,
) -> tuple[int, int, int, int]:
    """Detect dark cinema letterbox/pillarbox borders on a downsampled BGRA array."""
    height, width = int(arr.shape[0]), int(arr.shape[1])
    if height < 6 or width < 6:
        return 0, height, 0, width

    luma = (
        0.2126 * arr[:, :, 2].astype(np.float32)
        + 0.7152 * arr[:, :, 1].astype(np.float32)
        + 0.0722 * arr[:, :, 0].astype(np.float32)
    )
    row_luma = np.mean(luma, axis=1)
    if not bool(np.any(row_luma > luma_threshold)):
        return 0, height, 0, width

    max_v = int(height * max_crop_ratio)
    top = 0
    while top < max_v and row_luma[top] <= luma_threshold:
        top += 1
    bottom = height
    while (height - bottom) < max_v and row_luma[bottom - 1] <= luma_threshold:
        bottom -= 1
    if bottom - top < 4:
        top, bottom = 0, height

    col_luma = np.mean(luma[top:bottom, :], axis=0)
    max_h = int(width * max_crop_ratio)
    left = 0
    while left < max_h and col_luma[left] <= luma_threshold:
        left += 1
    right = width
    while (width - right) < max_h and col_luma[right - 1] <= luma_threshold:
        right -= 1
    if right - left < 4:
        left, right = 0, width
    return top, bottom, left, right


def _slice_region(arr: np.ndarray, region: str) -> np.ndarray:
    """Slice a named screen zone (`full`, `left`, `right`, `top`, `bottom`, `center`)."""
    height, width = int(arr.shape[0]), int(arr.shape[1])
    if region == "left":
        return arr[:, : max(1, (width * 35) // 100)]
    if region == "right":
        return arr[:, width - max(1, (width * 35) // 100) :]
    if region == "top":
        return arr[: max(1, (height * 35) // 100), :]
    if region == "bottom":
        return arr[height - max(1, (height * 35) // 100) :, :]
    if region == "center":
        y0, y1 = height // 4, max(height // 4 + 1, (3 * height) // 4)
        x0, x1 = width // 4, max(width // 4 + 1, (3 * width) // 4)
        return arr[y0:y1, x0:x1]
    return arr


def extract_region_colors_from_bgra(
    bgra: bytes | bytearray | memoryview,
    width: int,
    height: int,
    regions: Iterable[str] = ("full",),
    mode: str = "vibrant",
    stride: int = 16,
    letterbox_crop: bool = True,
) -> dict[str, tuple[Color, int]]:
    """Extract representative color & brightness for multiple screen regions in one pass."""
    unique_regions = tuple(
        dict.fromkeys(r if r in VALID_AMBILIGHT_REGIONS else "full" for r in regions)
    )
    if not unique_regions:
        unique_regions = ("full",)
    if width <= 0 or height <= 0:
        return {region: (Color(0, 0, 0), 10) for region in unique_regions}

    expected_bytes = int(width) * int(height) * 4
    raw_view = memoryview(bgra).cast("B")
    if len(raw_view) < expected_bytes:
        return {region: (Color(0, 0, 0), 10) for region in unique_regions}

    step = max(1, int(stride))
    arr = np.frombuffer(raw_view[:expected_bytes], dtype=np.uint8).reshape((height, width, 4))[
        ::step, ::step
    ]
    if arr.size == 0:
        return {region: (Color(0, 0, 0), 10) for region in unique_regions}

    if letterbox_crop:
        top, bottom, left, right = detect_letterbox_bounds(arr)
        arr = arr[top:bottom, left:right]

    return {
        region: _compute_color_from_array(_slice_region(arr, region), mode=mode)
        for region in unique_regions
    }


def extract_color_and_brightness_from_bgra(
    bgra: bytes | bytearray | memoryview,
    width: int,
    height: int,
    mode: str = "vibrant",
    stride: int = 16,
) -> tuple[Color, int]:
    """Extrae el color representativo y el brillo sugerido (10-100%) desde un buffer BGRA crudo."""
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
    return _compute_color_from_array(arr, mode=mode)


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

    def sample_regions(
        self,
        monitor_index: int = 1,
        mode: str = "vibrant",
        regions: Iterable[str] = ("full",),
        letterbox_crop: bool = True,
    ) -> dict[str, tuple[Color, int]]:
        """Capture one frame from the monitor and compute colors for each requested region."""
        requested = tuple(regions) or ("full",)
        try:
            with self._sct_factory() as sct:
                monitors = list(sct.monitors)
                if not monitors:
                    return {region: (Color(0, 0, 0), 10) for region in requested}
                idx = int(monitor_index)
                if idx < 0 or idx >= len(monitors):
                    idx = 1 if len(monitors) > 1 else 0
                shot = sct.grab(monitors[idx])
                return extract_region_colors_from_bgra(
                    bgra=shot.bgra,
                    width=int(shot.width),
                    height=int(shot.height),
                    regions=requested,
                    mode=mode,
                    stride=self._stride,
                    letterbox_crop=letterbox_crop,
                )
        except (OSError, mss.exception.ScreenShotError):
            _LOGGER.debug("Screen region capture failed; returning standby frames.", exc_info=True)
            self._cached_monitors = None
            return {region: (Color(0, 0, 0), 10) for region in requested}

    def sample_frame(
        self,
        monitor_index: int = 1,
        mode: str = "vibrant",
    ) -> tuple[Color, int]:
        """Captura el monitor solicitado y devuelve `(Color, brillo_sugerido_10_a_100)`."""
        return self.sample_regions(
            monitor_index=monitor_index,
            mode=mode,
            regions=("full",),
            letterbox_crop=False,
        )["full"]

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
