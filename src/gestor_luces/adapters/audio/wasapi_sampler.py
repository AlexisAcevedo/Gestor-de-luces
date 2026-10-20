"""Adaptador de captura acustica WASAPI Loopback y analisis espectral FFT para el modo Musica.

En Windows, la API de audio de baja latencia WASAPI (Windows Audio Session API) permite
capturar el flujo digital de salida de un dispositivo de reproduccion (altavoces o
auriculares) mediante el modo *Loopback*, sin necesidad de cables virtuales ni mezclas
analogicas. Sin embargo, WASAPI presenta una particularidad critica de diseno: cuando
ninguna aplicacion del sistema emite sonido, el motor de audio de Windows detiene el
reloj de transferencia del endpoint y deja de invocar el callback de captura (o bloquea
indefinidamente cualquier llamada sincrona a `stream.read()`).

Para evitar que un hilo trabajador quede congelado en silencio, `WasapiLoopbackSampler`
abre el flujo en modo no bloqueante (`stream_callback`) y registra la marca de tiempo
monotonica (`time.monotonic()`) de cada bloque PCM recibido. Si al consultar el estado
han transcurrido mas de 160 ms sin nuevos buffers del sistema operativo, el adaptador
asume silencio acustico de forma instantanea y devuelve energia cero (`0.0`) con un piso
de brillo de cortesia (`12%`) sin bloquear nunca el bucle de eventos.
"""

from __future__ import annotations

from collections.abc import Callable
import logging
import threading
import time
from typing import Any

import numpy as np

from gestor_luces.domain.value_objects import Color

_LOGGER = logging.getLogger(__name__)

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
        # Paleta Club: graves en magenta/carmesi, medios en cian electrico y agudos en violeta/dorado.
        raw_r = (rel_bass * 1.00 + rel_treble * 0.72 + rel_mid * 0.08) * 255.0
        raw_g = (rel_mid * 0.92 + rel_treble * 0.35 + rel_bass * 0.05) * 255.0
        raw_b = (rel_mid * 0.95 + rel_treble * 0.95 + rel_bass * 0.42) * 255.0
    elif normalized == "chill":
        # Paleta Chill (Aurora/Oceano): azul profundo en graves, esmeralda/turquesa en medios y lavanda en agudos.
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


def analyze_pcm_audio_frame(
    samples: np.ndarray | bytes | bytearray | memoryview,
    sample_rate: int = 48000,
    channels: int = 2,
    palette_mode: str = "spectrum",
    sensitivity: float = 1.0,
) -> dict[str, Any]:
    """Analiza una ventana PCM mediante RMS y FFT devolviendo bandas de frecuencia y color.

    Aislar el procesamiento digital de senales (DSP) del hardware del sistema operativo
    permite inyectar ondas senoidales sinteticas puras en las pruebas unitarias (por ejemplo,
    80 Hz para graves, 1000 Hz para medios y 6000 Hz para agudos) y verificar matematicamente
    la descomposicion espectral:
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
        return {
            "rms": 0.0,
            "bass": 0.0,
            "mid": 0.0,
            "treble": 0.0,
            "brightness": STANDBY_BRIGHTNESS_FLOOR,
            "color": _standby_color_for_palette(palette_mode),
        }

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
        return {
            "rms": 0.0,
            "bass": 0.0,
            "mid": 0.0,
            "treble": 0.0,
            "brightness": STANDBY_BRIGHTNESS_FLOOR,
            "color": _standby_color_for_palette(palette_mode),
        }

    # Calculo de energia eficaz (RMS) en el dominio del tiempo.
    raw_rms = float(np.sqrt(np.mean(np.square(mono), dtype=np.float32)))
    if raw_rms < 1e-4:
        return {
            "rms": 0.0,
            "bass": 0.0,
            "mid": 0.0,
            "treble": 0.0,
            "brightness": STANDBY_BRIGHTNESS_FLOOR,
            "color": _standby_color_for_palette(palette_mode),
        }

    normalized_rms = min(1.0, (raw_rms / 0.35) * clamped_sensitivity)
    brightness = max(
        10,
        min(
            100,
            round(
                STANDBY_BRIGHTNESS_FLOOR
                + (normalized_rms ** 0.85) * (100.0 - STANDBY_BRIGHTNESS_FLOOR)
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

    bass_energy = float(np.sqrt(np.sum(np.square(spectrum[bass_mask])))) if np.any(bass_mask) else 0.0
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


class WasapiLoopbackSampler:
    """Implementacion del puerto `AudioSampler` sobre Windows WASAPI Loopback (`pyaudiowpatch`)."""

    def __init__(
        self,
        frames_per_buffer: int = 2048,
        silence_timeout: float = SILENCE_TIMEOUT_SECONDS,
        pyaudio_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._frames_per_buffer = max(256, int(frames_per_buffer))
        self._silence_timeout = max(0.05, float(silence_timeout))
        self._pyaudio_factory = pyaudio_factory
        self._lock = threading.Lock()
        self._pa: Any | None = None
        self._stream: Any | None = None
        self._active_device_index: int | None = None
        self._sample_rate: int = 48000
        self._channels: int = 2
        self._latest_pcm_bytes: bytes = b""
        self._last_chunk_monotonic: float = 0.0
        self._cached_devices: list[dict[str, Any]] | None = None

    def _create_pyaudio(self) -> Any:
        """Instancia el contenedor PortAudio/WASAPI bajo demanda."""
        if self._pyaudio_factory is not None:
            return self._pyaudio_factory()
        import pyaudiowpatch as pyaudio

        return pyaudio.PyAudio()

    def list_audio_devices(self, refresh: bool = False) -> list[dict[str, Any]]:
        """Enumera los dispositivos de salida con soporte WASAPI Loopback disponibles en Windows."""
        if self._cached_devices is not None and not refresh:
            return list(self._cached_devices)

        devices: list[dict[str, Any]] = []
        pa = None
        try:
            pa = self._create_pyaudio()
            default_index: int | None = None
            try:
                default_info = pa.get_default_wasapi_loopback()
                if isinstance(default_info, dict) and "index" in default_info:
                    default_index = int(default_info["index"])
            except Exception:
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
        except Exception:
            _LOGGER.debug("WASAPI loopback device enumeration fell back to default descriptor.")
        finally:
            if pa is not None:
                try:
                    pa.terminate()
                except Exception:
                    pass

        if not devices:
            fallback = [
                {
                    "index": -1,
                    "name": "System Audio Loopback",
                    "label": "Default System Output (WASAPI Loopback)",
                    "sample_rate": 48000,
                    "channels": 2,
                    "is_default": True,
                }
            ]
            self._cached_devices = list(fallback)
            return fallback

        devices.sort(key=lambda d: (not bool(d.get("is_default")), int(d.get("index", 0))))
        self._cached_devices = list(devices)
        return devices

    def _ensure_stream(self, requested_device_index: int | None) -> bool:
        """Abre o reconfigura el stream no bloqueante de captura WASAPI Loopback."""
        normalized_req = (
            int(requested_device_index)
            if (requested_device_index is not None and int(requested_device_index) >= 0)
            else None
        )
        if (
            self._stream is not None
            and self._pa is not None
            and self._active_device_index == normalized_req
        ):
            return True

        self.close()

        try:
            import pyaudiowpatch as pyaudio

            pa_float32 = getattr(pyaudio, "paFloat32", 1)
            pa_continue = getattr(pyaudio, "paContinue", 0)
        except Exception:
            pa_float32 = 1
            pa_continue = 0

        try:
            pa = self._create_pyaudio()
            device_info: dict[str, Any] | None = None

            if normalized_req is not None:
                try:
                    candidate = pa.get_device_info_by_index(normalized_req)
                    if candidate and int(candidate.get("maxInputChannels", 0)) > 0:
                        device_info = dict(candidate)
                except Exception:
                    device_info = None

            if device_info is None:
                device_info = dict(pa.get_default_wasapi_loopback())

            sample_rate = int(float(device_info.get("defaultSampleRate", 48000)))
            channels = max(1, int(device_info.get("maxInputChannels", 2) or 2))
            dev_idx = int(device_info["index"])

            def _audio_callback(
                in_data: bytes | None,
                frame_count: int,
                time_info: Any,
                status_flags: int,
            ) -> tuple[None, int]:
                if in_data:
                    with self._lock:
                        self._latest_pcm_bytes = bytes(in_data)
                        self._last_chunk_monotonic = time.monotonic()
                return (None, pa_continue)

            stream = pa.open(
                format=pa_float32,
                channels=channels,
                rate=sample_rate,
                frames_per_buffer=self._frames_per_buffer,
                input=True,
                input_device_index=dev_idx,
                stream_callback=_audio_callback,
            )
            if hasattr(stream, "start_stream"):
                stream.start_stream()

            with self._lock:
                self._pa = pa
                self._stream = stream
                self._active_device_index = normalized_req
                self._sample_rate = sample_rate
                self._channels = channels
            return True
        except Exception:
            _LOGGER.debug("Could not open WASAPI loopback stream; returning standby silence.")
            self.close()
            return False

    def sample_frame(
        self,
        device_index: int | None = None,
        palette_mode: str = "spectrum",
        sensitivity: float = 1.0,
    ) -> dict[str, Any]:
        """Extrae las metricas espectrales de la ventana actual o silencio si WASAPI se detuvo."""
        stream_ready = self._ensure_stream(device_index)
        if not stream_ready:
            return analyze_pcm_audio_frame(
                np.empty(0, dtype=np.float32),
                sample_rate=self._sample_rate,
                channels=self._channels,
                palette_mode=palette_mode,
                sensitivity=sensitivity,
            )

        with self._lock:
            pcm_bytes = self._latest_pcm_bytes
            last_time = self._last_chunk_monotonic
            sample_rate = self._sample_rate
            channels = self._channels

        # Si Windows detuvo el envio de paquetes por ausencia de audio en el mezclador,
        # evitamos reutilizar el ultimo buffer congelado y reportamos silencio inmediato.
        elapsed = time.monotonic() - last_time
        if not pcm_bytes or last_time <= 0.0 or elapsed > self._silence_timeout:
            return analyze_pcm_audio_frame(
                np.empty(0, dtype=np.float32),
                sample_rate=sample_rate,
                channels=channels,
                palette_mode=palette_mode,
                sensitivity=sensitivity,
            )

        return analyze_pcm_audio_frame(
            pcm_bytes,
            sample_rate=sample_rate,
            channels=channels,
            palette_mode=palette_mode,
            sensitivity=sensitivity,
        )

    def sample_audio_metrics(self) -> tuple[float, Color]:
        """Cumple el protocolo `AudioSampler` devolviendo `(rms_0_a_1, Color)`."""
        metrics = self.sample_frame(palette_mode="spectrum", sensitivity=1.0)
        return float(metrics["rms"]), metrics["color"]

    def close(self) -> None:
        """Cierra de forma segura el stream de captura y libera la sesion WASAPI."""
        with self._lock:
            stream = self._stream
            pa = self._pa
            self._stream = None
            self._pa = None
            self._active_device_index = None
            self._latest_pcm_bytes = b""
            self._last_chunk_monotonic = 0.0

        if stream is not None:
            try:
                if hasattr(stream, "stop_stream"):
                    stream.stop_stream()
            except Exception:
                pass
            try:
                if hasattr(stream, "close"):
                    stream.close()
            except Exception:
                pass

        if pa is not None:
            try:
                pa.terminate()
            except Exception:
                pass
