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

from typing import Any

import numpy as np

from gestor_luces.domain.value_objects import Color

VALID_MUSIC_PALETTES = ("spectrum", "club", "chill")
SILENCE_TIMEOUT_SECONDS = 0.16
STANDBY_BRIGHTNESS_FLOOR = 12


def _standby_color_for_palette(palette_mode: str) -> Color:
    """Devuelve una cromacidad tenue de reposo acorde a la paleta seleccionada.

    Cuando la pista musical hace una pausa o el sistema queda en silencio, mantener
    un matiz suave evita parpadeos bruscos hacia el negro absoluto mientras el brillo
    desciende al piso del 12%.
    """
    normalized = palette_mode.strip().lower() if isinstance(palette_mode, str) else "spectrum"
    if normalized == "club":
        return Color(r=64, g=18, b=52)
    if normalized == "chill":
        return Color(r=18, g=52, b=78)
    return Color(r=56, g=34, b=24)


def _map_bands_to_color(
    bass: float,
    mid: float,
    treble: float,
    rms: float,
    palette_mode: str,
) -> Color:
    """Transforma la energia de las tres bandas espectrales en un color RGB saturado.

    Se separa la direccion cromatica (proporcion relativa entre graves, medios y agudos)
    de la intensidad energetica para que incluso a volumenes moderados los golpes de
    bombo (Bass), las voces/sintetizadores (Mid) y los platillos (Treble) produzcan
    colores definidos y no grises apagados.
    """
    max_band = max(bass, mid, treble)
    if max_band <= 1e-4 and rms <= 1e-4:
        return _standby_color_for_palette(palette_mode)

    inv_max = 1.0 / max(1e-6, max_band)
    rel_bass = bass * inv_max
    rel_mid = mid * inv_max
    rel_treble = treble * inv_max
    intensity = max(0.45, min(1.0, max(rms, max_band)))

    normalized = palette_mode.strip().lower() if isinstance(palette_mode, str) else "spectrum"
    if normalized == "club":
        # Paleta Club: graves en magenta/carmesi, medios en cian electrico y agudos en
        # violeta/dorado.
        raw_r = (rel_bass * 1.00 + rel_treble * 0.72 + rel_mid * 0.08) * 255.0
        raw_g = (rel_mid * 0.92 + rel_treble * 0.35 + rel_bass * 0.05) * 255.0
        raw_b = (rel_mid * 0.95 + rel_treble * 0.95 + rel_bass * 0.42) * 255.0
    elif normalized == "chill":
        # Paleta Chill (Aurora/Oceano): azul profundo en graves, esmeralda/turquesa en medios y
        # lavanda en agudos.
        raw_r = (rel_treble * 0.68 + rel_bass * 0.10 + rel_mid * 0.06) * 255.0
        raw_g = (rel_mid * 0.92 + rel_bass * 0.38 + rel_treble * 0.45) * 255.0
        raw_b = (rel_bass * 0.95 + rel_treble * 0.98 + rel_mid * 0.68) * 255.0
    else:
        # Paleta Spectrum: asignacion directa Graves -> Rojo, Medios -> Verde, Agudos -> Azul.
        raw_r = (rel_bass * 0.98 + rel_mid * 0.10) * 255.0
        raw_g = (rel_mid * 0.98 + rel_bass * 0.12 + rel_treble * 0.08) * 255.0
        raw_b = (rel_treble * 0.98 + rel_mid * 0.18) * 255.0

    r = max(0, min(255, round(raw_r * intensity)))
    g = max(0, min(255, round(raw_g * intensity)))
    b = max(0, min(255, round(raw_b * intensity)))
    return Color(r=r, g=g, b=b)


def _silence_metrics(palette_mode: str) -> dict[str, Any]:
    """Devuelve el sobre de silencio absoluto con el piso de brillo de cortesia."""
    return {
        "rms": 0.0,
        "bass": 0.0,
        "mid": 0.0,
        "treble": 0.0,
        "brightness": STANDBY_BRIGHTNESS_FLOOR,
        "color": _standby_color_for_palette(palette_mode),
    }


def analyze_pcm_audio_frame(
    samples: np.ndarray | bytes | bytearray | memoryview,
    sample_rate: int = 48000,
    channels: int = 2,
    palette_mode: str = "spectrum",
    sensitivity: float = 1.0,
) -> dict[str, Any]:
    """Analiza una ventana PCM mediante RMS y FFT devolviendo bandas de frecuencia y color.

    - **RMS (Root Mean Square)**: mide la presion acustica eficaz de la ventana temporal,
      que determina el brillo dinamico del foco entre el piso del 10-15% y el 100%.
    - **Ventana de Hann + RFFT**: atenua los extremos del bloque PCM para suprimir la fuga
      espectral (*spectral leakage*) antes de aplicar la Transformada Rapida de Fourier
      para senales reales (`np.fft.rfft`), integrando la energia en tres bandas perceptuales:
      Graves (`20-250 Hz`), Medios (`250-2000 Hz`) y Agudos (`2000-12000 Hz`).
    """
    clamped_sensitivity = max(0.2, min(4.0, float(sensitivity)))
    num_channels = max(1, int(channels))
    effective_rate = max(8000, int(sample_rate))

    if isinstance(samples, (bytes, bytearray, memoryview)):
        if len(samples) == 0:
            arr = np.empty(0, dtype=np.float32)
        else:
            arr = np.frombuffer(samples, dtype=np.float32)
    else:
        arr = np.asarray(samples)

    if arr.size == 0:
        return _silence_metrics(palette_mode)

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
        return _silence_metrics(palette_mode)

    # Calculo de energia eficaz (RMS) en el dominio del tiempo.
    raw_rms = float(np.sqrt(np.mean(np.square(mono), dtype=np.float32)))
    if raw_rms < 1e-4:
        return _silence_metrics(palette_mode)

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

    # Aplicamos una ventana de Hann antes de la RFFT para evitar discontinuidades en los bordes
    # del bloque que contaminarian las bandas vecinas con armonicos artificiales.
    window = np.hanning(mono.size).astype(np.float32)
    window_sum = float(np.sum(window)) or 1.0
    spectrum = (2.0 * np.abs(np.fft.rfft(mono * window))) / window_sum
    freqs = np.fft.rfftfreq(mono.size, d=1.0 / float(effective_rate))

    bass_mask = (freqs >= 20.0) & (freqs < 250.0)
    mid_mask = (freqs >= 250.0) & (freqs < 2000.0)
    treble_mask = (freqs >= 2000.0) & (freqs <= 12000.0)

    bass_energy = (
        float(np.sqrt(np.sum(np.square(spectrum[bass_mask])))) if np.any(bass_mask) else 0.0
    )
    mid_energy = float(np.sqrt(np.sum(np.square(spectrum[mid_mask])))) if np.any(mid_mask) else 0.0
    treble_energy = (
        float(np.sqrt(np.sum(np.square(spectrum[treble_mask])))) if np.any(treble_mask) else 0.0
    )

    bass_norm = min(1.0, bass_energy * 1.65 * clamped_sensitivity)
    mid_norm = min(1.0, mid_energy * 1.50 * clamped_sensitivity)
    treble_norm = min(1.0, treble_energy * 1.45 * clamped_sensitivity)

    color = _map_bands_to_color(
        bass=bass_norm,
        mid=mid_norm,
        treble=treble_norm,
        rms=normalized_rms,
        palette_mode=palette_mode,
    )

    return {
        "rms": round(normalized_rms, 4),
        "bass": round(bass_norm, 4),
        "mid": round(mid_norm, 4),
        "treble": round(treble_norm, 4),
        "brightness": int(brightness),
        "color": color,
    }
