"""Adaptador de captura acustica WASAPI Loopback para el modo Musica.

`WasapiLoopbackSampler` implementa el puerto `AudioSampler` componiendo tres piezas de
este paquete: la sesion de captura no bloqueante (`wasapi_session`), la enumeracion de
endpoints loopback (`wasapi_devices`) y el analisis espectral FFT de cada ventana PCM
(`wasapi_capture`). El adaptador solo aporta la politica de silencio: si el sistema
detuvo el envio de paquetes por ausencia de audio en el mezclador, reporta energia cero
con el piso de brillo de cortesia en vez de reutilizar un buffer congelado o bloquearse.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import numpy as np

from gestor_luces.adapters.audio.wasapi_capture import (
    SILENCE_TIMEOUT_SECONDS,
    STANDBY_BRIGHTNESS_FLOOR,
    VALID_MUSIC_PALETTES,
    analyze_pcm_audio_frame,
)
from gestor_luces.adapters.audio.wasapi_devices import enumerate_loopback_devices
from gestor_luces.adapters.audio.wasapi_session import WasapiLoopbackStreamSession
from gestor_luces.domain.value_objects import Color

__all__ = [
    "SILENCE_TIMEOUT_SECONDS",
    "STANDBY_BRIGHTNESS_FLOOR",
    "VALID_MUSIC_PALETTES",
    "WasapiLoopbackSampler",
    "analyze_pcm_audio_frame",
]


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
        self._cached_devices: list[dict[str, Any]] | None = None
        self._session = WasapiLoopbackStreamSession(
            frames_per_buffer=self._frames_per_buffer,
            pyaudio_factory=pyaudio_factory,
        )

    def list_audio_devices(self, refresh: bool = False) -> list[dict[str, Any]]:
        """Enumera los dispositivos de salida con soporte WASAPI Loopback disponibles en Windows."""
        if self._cached_devices is not None and not refresh:
            return list(self._cached_devices)
        devices = enumerate_loopback_devices(self._session.create_pyaudio)
        self._cached_devices = list(devices)
        return devices

    def _ensure_stream(self, requested_device_index: int | None) -> bool:
        """Abre o reconfigura el stream no bloqueante de captura WASAPI Loopback."""
        return self._session.ensure_stream(requested_device_index)

    def _silence(self, palette_mode: str, sensitivity: float) -> dict[str, Any]:
        """Metricas de silencio absoluto para una ventana sin paquetes del sistema."""
        return analyze_pcm_audio_frame(
            np.empty(0, dtype=np.float32),
            sample_rate=self._session.sample_rate,
            channels=self._session.channels,
            palette_mode=palette_mode,
            sensitivity=sensitivity,
        )

    def sample_frame(
        self,
        device_index: int | None = None,
        palette_mode: str = "spectrum",
        sensitivity: float = 1.0,
    ) -> dict[str, Any]:
        """Extrae las metricas espectrales de la ventana actual o silencio si WASAPI se detuvo."""
        if not self._ensure_stream(device_index):
            return self._silence(palette_mode, sensitivity)

        pcm_bytes, last_time, sample_rate, channels = self._session.read()

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
        self._session.close()
