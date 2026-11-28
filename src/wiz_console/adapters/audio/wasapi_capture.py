"""Analisis espectral FFT de ventanas PCM capturadas por WASAPI Loopback.

En Windows, la API de audio de baja latencia WASAPI (Windows Audio Session API) permite
capturar el flujo digital de salida de un dispositivo de reproduccion mediante el modo
*Loopback*. Sin embargo, cuando ninguna aplicacion del sistema emite sonido el motor de
audio detiene el reloj de transferencia del endpoint y deja de invocar el callback de
captura, de modo que el muestreador debe asumir silencio sin bloquearse (ver
`wasapi_session`).

Este modulo aisla el procesamiento digital de senales (DSP) del hardware del sistema
operativo: recibe la ventana PCM y la convierte en bandas de frecuencia, RMS y color. Eso
permite inyectar ondas senoidales sinteticas puras en las pruebas unitarias (por ejemplo,
80 Hz para graves, 1000 Hz para medios y 6000 Hz para agudos) y verificar matematicamente
la descomposicion espectral.
"""

from __future__ import annotations

import math
import time
from collections import deque
from collections.abc import Callable, Mapping
from functools import lru_cache
from typing import Any

import numpy as np

from wiz_console.domain.music_colors import (
    DEFAULT_CUSTOM_PALETTE,
    STANDBY_BRIGHTNESS_FLOOR,
    VALID_BAND_ASSIGNMENTS,
    VALID_MUSIC_PALETTES,
    map_bands_to_color,
    normalize_custom_palette,
    standby_color_for_palette,
)
from wiz_console.domain.value_objects import Color

__all__ = [
    "BeatDetector",
    "DEFAULT_CUSTOM_PALETTE",
    "SILENCE_TIMEOUT_SECONDS",
    "STANDBY_BRIGHTNESS_FLOOR",
    "VALID_BAND_ASSIGNMENTS",
    "VALID_MUSIC_PALETTES",
    "analyze_pcm_audio_frame",
    "normalize_custom_palette",
]

SILENCE_TIMEOUT_SECONDS = 0.16


class BeatDetector:
    """Lightweight rolling energy-history beat onset detector with cooldown."""

    def __init__(
        self,
        history_len: int = 24,
        threshold_ratio: float = 1.38,
        min_energy: float = 0.12,
        cooldown_seconds: float = 0.14,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._history: deque[float] = deque(maxlen=max(4, int(history_len)))
        self._threshold_ratio = float(threshold_ratio)
        self._min_energy = float(min_energy)
        self._cooldown_seconds = max(0.0, float(cooldown_seconds))
        self._clock = clock
        self._last_beat_at: float = -1e9

    def reset(self) -> None:
        """Clear accumulated energy history."""
        self._history.clear()
        self._last_beat_at = -1e9

    def update(self, energy: float) -> tuple[bool, float]:
        """Feed instantaneous onset energy and return `(beat_detected, intensity)`."""
        value = max(0.0, float(energy)) if math.isfinite(energy) else 0.0
        if value <= 1e-4:
            self._history.append(0.0)
            return False, 0.0

        now = self._clock()
        triggered = False
        if len(self._history) >= 4 and value >= self._min_energy:
            mean_energy = sum(self._history) / len(self._history)
            if (
                mean_energy > 1e-4
                and value >= mean_energy * self._threshold_ratio
                and (now - self._last_beat_at) >= self._cooldown_seconds
            ):
                triggered = True
                self._last_beat_at = now
        self._history.append(value)
        return triggered, (round(min(1.0, value), 3) if triggered else 0.0)


@lru_cache(maxsize=32)
def _fft_plan(
    num_samples: int,
    sample_rate: int,
) -> tuple[np.ndarray, float, slice, slice, slice]:
    """Precalcula ventana de Hann de solo lectura y slices de banda para `(N, sample_rate)`."""
    window = np.hanning(num_samples).astype(np.float32)
    window.setflags(write=False)
    window_sum = float(np.sum(window)) or 1.0
    scale = 2.0 / window_sum
    freqs = np.fft.rfftfreq(num_samples, d=1.0 / float(sample_rate))
    bass = slice(
        int(np.searchsorted(freqs, 20.0, side="left")),
        int(np.searchsorted(freqs, 250.0, side="left")),
    )
    mid = slice(
        int(np.searchsorted(freqs, 250.0, side="left")),
        int(np.searchsorted(freqs, 2000.0, side="left")),
    )
    treble = slice(
        int(np.searchsorted(freqs, 2000.0, side="left")),
        int(np.searchsorted(freqs, 12000.0, side="right")),
    )
    return window, scale, bass, mid, treble


def _band_rms(spectrum: np.ndarray, band: slice) -> float:
    """Calcula energia RMS de una banda espectral usando un slice contiguo."""
    segment = spectrum[band]
    if segment.size == 0:
        return 0.0
    return float(np.sqrt(np.dot(segment, segment)))


def _standby_color_for_palette(
    palette_mode: str,
    custom_palette: Mapping[str, str] | None = None,
) -> Color:
    """Devuelve una cromacidad tenue de reposo acorde a la paleta seleccionada."""
    return standby_color_for_palette(palette_mode, custom_palette)


def _map_bands_to_color(
    bass: float,
    mid: float,
    treble: float,
    rms: float,
    palette_mode: str,
    custom_palette: Mapping[str, str] | None = None,
) -> Color:
    """Transforma la energia de las tres bandas espectrales en un color RGB saturado."""
    return map_bands_to_color(
        bass=bass,
        mid=mid,
        treble=treble,
        rms=rms,
        palette_mode=palette_mode,
        custom_palette=custom_palette,
    )


def _silence_metrics(
    palette_mode: str,
    custom_palette: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Devuelve el sobre de silencio absoluto con el piso de brillo de cortesia."""
    return {
        "rms": 0.0,
        "bass": 0.0,
        "mid": 0.0,
        "treble": 0.0,
        "brightness": STANDBY_BRIGHTNESS_FLOOR,
        "color": _standby_color_for_palette(palette_mode, custom_palette),
    }


def analyze_pcm_audio_frame(
    samples: np.ndarray | bytes | bytearray | memoryview,
    sample_rate: int = 48000,
    channels: int = 2,
    palette_mode: str = "spectrum",
    sensitivity: float = 1.0,
    custom_palette: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Analiza una ventana PCM mediante RMS y FFT devolviendo bandas de frecuencia y color.

    - **RMS (Root Mean Square)**: mide la presion acustica eficaz de la ventana temporal,
      que determina el brillo dinamico del foco entre el piso del 10-15% y el 100%.
    - **Ventana de Hann + RFFT**: atenua los extremos del bloque PCM para suprimir la fuga
      espectral (*spectral leakage*) antes de aplicar la Transformada Rapida de Fourier
      para senales reales (`np.fft.rfft`), integrando la energia en tres bandas perceptuales:
      Graves (`20-250 Hz`), Medios (`250-2000 Hz`) y Agudos (`2000-12000 Hz`).
    """
    if isinstance(sensitivity, bool):
        raw_sensitivity = 1.0
    else:
        raw_sensitivity = float(sensitivity)
        if not math.isfinite(raw_sensitivity):
            raw_sensitivity = 1.0
    clamped_sensitivity = max(0.2, min(4.0, raw_sensitivity))
    num_channels = max(1, int(channels))
    effective_rate = max(8000, int(sample_rate))

    if isinstance(samples, (bytes, bytearray, memoryview)):
        raw_bytes = memoryview(samples).cast("B")
        aligned_len = (len(raw_bytes) // 4) * 4
        if aligned_len == 0:
            return _silence_metrics(palette_mode, custom_palette)
        arr = np.frombuffer(raw_bytes[:aligned_len], dtype=np.float32)
    else:
        arr = np.asarray(samples)

    if arr.size == 0:
        return _silence_metrics(palette_mode, custom_palette)

    # Normalizamos formatos enteros (como PCM int16) al intervalo flotante [-1.0, 1.0].
    if np.issubdtype(arr.dtype, np.integer):
        info = np.iinfo(arr.dtype)
        scale = float(max(abs(info.min), abs(info.max))) or 32768.0
        float_arr = arr.astype(np.float32) / scale
    else:
        float_arr = arr.astype(np.float32, copy=False)

    float_arr = np.nan_to_num(float_arr, nan=0.0, posinf=1.0, neginf=-1.0)

    # Mezclamos los canales entrelazados (por ejemplo, Estereo L+R) en una senal monofonica.
    if float_arr.ndim == 2:
        mono = np.mean(float_arr, axis=1, dtype=np.float32)
    elif num_channels > 1 and float_arr.size >= num_channels:
        usable = (float_arr.size // num_channels) * num_channels
        mono = np.mean(float_arr[:usable].reshape((-1, num_channels)), axis=1, dtype=np.float32)
    else:
        mono = float_arr.reshape(-1)

    mono = np.clip(mono, -1.0, 1.0)
    if mono.size == 0:
        return _silence_metrics(palette_mode, custom_palette)

    # Calculo de energia eficaz (RMS) en el dominio del tiempo.
    raw_rms = float(np.sqrt(np.mean(np.square(mono), dtype=np.float32)))
    if raw_rms < 1e-4:
        return _silence_metrics(palette_mode, custom_palette)

    normalized_rms = min(1.0, (raw_rms / 0.35) * clamped_sensitivity)
    brightness = max(
        10,
        min(
            100,
            round(
                STANDBY_BRIGHTNESS_FLOOR
                + (normalized_rms**0.85) * (100.0 - STANDBY_BRIGHTNESS_FLOOR)
            ),
        ),
    )

    # Aplicamos la ventana de Hann cacheada y los slices contiguos de frecuencia para evitar
    # recomputar `hanning`, `rfftfreq` y mascaras booleanas en cada iteracion.
    window, scale, bass_slice, mid_slice, treble_slice = _fft_plan(mono.size, effective_rate)
    spectrum = np.abs(np.fft.rfft(mono * window)) * scale

    bass_energy = _band_rms(spectrum, bass_slice)
    mid_energy = _band_rms(spectrum, mid_slice)
    treble_energy = _band_rms(spectrum, treble_slice)

    bass_norm = min(1.0, bass_energy * 1.65 * clamped_sensitivity)
    mid_norm = min(1.0, mid_energy * 1.50 * clamped_sensitivity)
    treble_norm = min(1.0, treble_energy * 1.45 * clamped_sensitivity)

    color = _map_bands_to_color(
        bass=bass_norm,
        mid=mid_norm,
        treble=treble_norm,
        rms=normalized_rms,
        palette_mode=palette_mode,
        custom_palette=custom_palette,
    )

    return {
        "rms": round(normalized_rms, 4),
        "bass": round(bass_norm, 4),
        "mid": round(mid_norm, 4),
        "treble": round(treble_norm, 4),
        "brightness": int(brightness),
        "color": color,
    }
