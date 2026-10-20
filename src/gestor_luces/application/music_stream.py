"""Orquestador asincrono del flujo reactivo de audio (modo Sincronizacion Musical).

Coordina una tarea en segundo plano sobre el bucle `asyncio` que consulta el adaptador
de captura acustica (`AudioSampler`) en un hilo trabajador (`asyncio.to_thread`) a ~10.5 Hz
(`interval_seconds = 0.095`) y transmite cada fotograma cromatico y de brillo hacia los
focos seleccionados mediante `LightControlService.stream_color_frame`. De este modo, el
analisis espectral FFT y la emision UDP fire-and-forget conviven sin bloquear la interfaz
ni saturar el microcontrolador Wi-Fi de las lamparas WiZ.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import logging
from typing import Any

from gestor_luces.application.sleep_timer import AwaitableStatusDict
from gestor_luces.domain.value_objects import Brightness, Color
from gestor_luces.ports.repositories import AudioSampler

_LOGGER = logging.getLogger(__name__)

VALID_MUSIC_PALETTES = ("spectrum", "club", "chill")


class MusicSyncStreamManager:
    """Gestiona el ciclo de vida de la tarea asincrona de muestreo acustico y emision UDP."""

    def __init__(
        self,
        sampler: AudioSampler | None = None,
        interval_seconds: float = 0.095,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("Music sync sampling interval must be greater than zero.")
        self._sampler: AudioSampler | None = sampler
        self._interval_seconds: float = float(interval_seconds)
        self._task: asyncio.Task[None] | None = None
        self._active: bool = False
        self._device_index: int | None = None
        self._palette_mode: str = "spectrum"
        self._sensitivity: float = 1.0
        self._smoothing_alpha: float = 0.50
        self._audio_brightness: bool = True
        self._fixed_brightness: int = 85
        self._last_color: Color | None = None
        self._last_brightness: int = 85
        self._rms: float = 0.0
        self._bass: float = 0.0
        self._mid: float = 0.0
        self._treble: float = 0.0
        self._target_ips: list[str] = []
        self._frames_sent: int = 0

    def set_sampler(self, sampler: AudioSampler) -> None:
        """Asigna o reemplaza el adaptador de captura acustica."""
        self._sampler = sampler

    def start(
        self,
        *,
        sampler: AudioSampler,
        target_ips: list[str],
        on_frame: Callable[[Color, int, list[str]], Awaitable[bool]],
        palette_mode: str = "spectrum",
        sensitivity: float = 1.0,
        smoothing_alpha: float = 0.50,
        audio_brightness: bool = True,
        brightness: int = 85,
        device_index: int | None = None,
    ) -> AwaitableStatusDict:
        """Inicia o reinicia el bucle continuo de reaccion musical hacia los focos objetivo."""
        normalized_palette = str(palette_mode).strip().lower()
        if normalized_palette not in VALID_MUSIC_PALETTES:
            raise ValueError(
                f"Invalid music palette '{palette_mode}'. Expected one of {VALID_MUSIC_PALETTES}."
            )

        parsed_sensitivity = float(sensitivity)
        if not (0.3 <= parsed_sensitivity <= 3.0):
            raise ValueError("Music sensitivity must be between 0.3 and 3.0.")

        parsed_alpha = float(smoothing_alpha)
        if not (0.05 <= parsed_alpha <= 1.0):
            raise ValueError("Smoothing alpha must be between 0.05 and 1.0.")

        validated_brightness = Brightness(int(brightness)).percent
        normalized_device = (
            int(device_index)
            if (device_index is not None and int(device_index) >= 0)
            else None
        )

        self.stop()

        self._sampler = sampler
        self._device_index = normalized_device
        self._palette_mode = normalized_palette
        self._sensitivity = parsed_sensitivity
        self._smoothing_alpha = parsed_alpha
        self._audio_brightness = bool(audio_brightness)
        self._fixed_brightness = validated_brightness
        self._last_brightness = validated_brightness
        self._target_ips = list(target_ips)
        self._frames_sent = 0
        self._active = True

        loop = asyncio.get_running_loop()
        self._task = loop.create_task(
            self._run_loop(on_frame=on_frame),
            name="GestorLucesMusicSyncStream",
        )
        return self.get_status()

    def stop(self) -> AwaitableStatusDict:
        """Detiene inmediatamente la captura musical sin apagar los focos."""
        if self._task is not None and not self._task.done():
            self._task.cancel()
        self._task = None
        self._active = False
        self._target_ips = []
        self._rms = 0.0
        self._bass = 0.0
        self._mid = 0.0
        self._treble = 0.0
        return self.get_status()

    def update_targets(self, target_ips: list[str]) -> None:
        """Actualiza en caliente los focos destino cuando el usuario cambia la seleccion."""
        if self._active:
            self._target_ips = list(target_ips)

    def update_fixed_brightness(self, brightness: int) -> None:
        """Actualiza el brillo fijo si la modulacion de brillo por volumen esta desactivada."""
        validated = Brightness(int(brightness)).percent
        self._fixed_brightness = validated
        if not self._audio_brightness:
            self._last_brightness = validated

    def get_status(self) -> AwaitableStatusDict:
        """Devuelve una fotografia serializable del estado y telemetria del flujo musical."""
        is_running = (
            self._active
            and self._task is not None
            and not self._task.done()
        )
        if not is_running:
            self._active = False

        return AwaitableStatusDict(
            {
                "active": is_running,
                "device_index": self._device_index,
                "palette_mode": self._palette_mode,
                "sensitivity": round(self._sensitivity, 2),
                "smoothing_alpha": round(self._smoothing_alpha, 2),
                "audio_brightness": self._audio_brightness,
                "brightness": (
                    self._last_brightness if self._audio_brightness else self._fixed_brightness
                ),
                "fixed_brightness": self._fixed_brightness,
                "rms": round(self._rms, 3) if is_running else 0.0,
                "bass": round(self._bass, 3) if is_running else 0.0,
                "mid": round(self._mid, 3) if is_running else 0.0,
                "treble": round(self._treble, 3) if is_running else 0.0,
                "last_color": (
                    self._last_color.to_dict() if self._last_color is not None else None
                ),
                "target_ips": list(self._target_ips) if is_running else [],
                "frames_sent": self._frames_sent,
            }
        )

    def _sample_once(
        self,
        device_index: int | None,
        palette_mode: str,
        sensitivity: float,
    ) -> dict[str, Any]:
        """Ejecuta una lectura sincrona del muestreador de audio (via `asyncio.to_thread`)."""
        if self._sampler is None:
            return {
                "rms": 0.0,
                "bass": 0.0,
                "mid": 0.0,
                "treble": 0.0,
                "brightness": self._fixed_brightness,
                "color": Color(56, 34, 24),
            }

        sample_frame_fn = getattr(self._sampler, "sample_frame", None)
        if callable(sample_frame_fn):
            result = sample_frame_fn(
                device_index=device_index,
                palette_mode=palette_mode,
                sensitivity=sensitivity,
            )
            return dict(result)

        # Compatibilidad con dobles de prueba que solo implementan `sample_audio_metrics`
        energy, color = self._sampler.sample_audio_metrics()
        clamped_energy = max(0.0, min(1.0, float(energy) * float(sensitivity)))
        derived_brightness = max(10, min(100, round(12.0 + clamped_energy * 88.0)))
        return {
            "rms": clamped_energy,
            "bass": round(clamped_energy * (color.r / 255.0), 3),
            "mid": round(clamped_energy * (color.g / 255.0), 3),
            "treble": round(clamped_energy * (color.b / 255.0), 3),
            "brightness": derived_brightness,
            "color": color,
        }

    async def _run_loop(
        self,
        on_frame: Callable[[Color, int, list[str]], Awaitable[bool]],
    ) -> None:
        """Bucle asincrono que analiza el espectro acustico y transmite fotogramas UDP."""
        try:
            while self._active:
                try:
                    metrics = await asyncio.to_thread(
                        self._sample_once,
                        self._device_index,
                        self._palette_mode,
                        self._sensitivity,
                    )
                    sampled_color: Color = metrics["color"]
                    suggested_brightness = int(metrics.get("brightness", self._fixed_brightness))
                    effective_brightness = (
                        suggested_brightness
                        if self._audio_brightness
                        else self._fixed_brightness
                    )

                    self._rms = float(metrics.get("rms", 0.0))
                    self._bass = float(metrics.get("bass", 0.0))
                    self._mid = float(metrics.get("mid", 0.0))
                    self._treble = float(metrics.get("treble", 0.0))
                    self._last_color = sampled_color
                    self._last_brightness = effective_brightness

                    if self._target_ips:
                        sent = await on_frame(
                            sampled_color,
                            effective_brightness,
                            list(self._target_ips),
                        )
                        if sent:
                            self._frames_sent += 1
                except asyncio.CancelledError:
                    raise
                except Exception:
                    _LOGGER.exception("Music sync frame sampling iteration failed.")

                await asyncio.sleep(self._interval_seconds)
        except asyncio.CancelledError:
            raise
        finally:
            self._active = False

