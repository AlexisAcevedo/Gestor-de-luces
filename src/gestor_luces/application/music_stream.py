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
import logging
import threading
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from typing import Any

from gestor_luces.application.sleep_timer import (
    AwaitableStatusDict,
    finite_metric,
    require_finite_float,
    require_int_value,
    sanitize_brightness,
)
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
        max_error_backoff: float = 5.0,
    ) -> None:
        parsed_interval = require_finite_float(interval_seconds, "interval_seconds")
        if parsed_interval <= 0:
            raise ValueError("Music sync sampling interval must be greater than zero.")
        parsed_backoff = require_finite_float(max_error_backoff, "max_error_backoff")
        if parsed_backoff < parsed_interval:
            raise ValueError("max_error_backoff must be >= interval_seconds.")
        self._sampler: AudioSampler | None = sampler
        self._interval_seconds: float = parsed_interval
        self._max_error_backoff: float = parsed_backoff
        self._task: asyncio.Task[None] | None = None
        self._active: bool = False
        self._generation: int = 0
        self._sample_lock = threading.Lock()
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

    def set_sampler(self, sampler: AudioSampler | None) -> None:
        """Asigna o reemplaza el adaptador de captura acustica."""
        self._sampler = sampler

    @contextmanager
    def hold_sampler_lock(self, timeout: float = 1.0) -> Iterator[bool]:
        """Serializa el cierre del sampler respecto a lecturas activas en otros hilos."""
        acquired = self._sample_lock.acquire(timeout=timeout)
        try:
            yield acquired
        finally:
            if acquired:
                self._sample_lock.release()

    def start(
        self,
        *,
        sampler: AudioSampler | None = None,
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
        parsed_sensitivity = require_finite_float(sensitivity, "sensitivity")
        if not (0.3 <= parsed_sensitivity <= 3.0):
            raise ValueError("Music sensitivity must be between 0.3 and 3.0.")
        parsed_alpha = require_finite_float(smoothing_alpha, "smoothing_alpha")
        if not (0.05 <= parsed_alpha <= 1.0):
            raise ValueError("Smoothing alpha must be between 0.05 and 1.0.")

        validated_brightness = Brightness(require_int_value(brightness, "brightness")).percent
        if device_index is None:
            normalized_device = None
        else:
            parsed_dev = require_int_value(device_index, "device_index")
            normalized_device = parsed_dev if parsed_dev >= 0 else None
        loop = asyncio.get_running_loop()

        self.stop()

        self._generation += 1
        run_id = self._generation
        if sampler is not None:
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

        self._task = loop.create_task(
            self._run_loop(on_frame=on_frame, run_id=run_id),
            name="WizConsoleMusicSyncStream",
        )
        return self.get_status()

    def stop(self) -> AwaitableStatusDict:
        """Detiene inmediatamente la captura musical sin apagar los focos."""
        self._generation += 1
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
        validated = Brightness(require_int_value(brightness, "brightness")).percent
        self._fixed_brightness = validated
        if not self._audio_brightness:
            self._last_brightness = validated

    def get_status(self) -> AwaitableStatusDict:
        """Devuelve una fotografia serializable del estado y telemetria del flujo musical."""
        is_running = self._active and self._task is not None and not self._task.done()
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
        sampler: AudioSampler | None,
        device_index: int | None,
        palette_mode: str,
        sensitivity: float,
        run_id: int,
    ) -> dict[str, Any]:
        """Ejecuta una lectura sincrona del muestreador de audio (via `asyncio.to_thread`)."""
        with self._sample_lock:
            if self._generation != run_id or sampler is None or self._sampler is not sampler:
                return {
                    "rms": 0.0,
                    "bass": 0.0,
                    "mid": 0.0,
                    "treble": 0.0,
                    "brightness": self._fixed_brightness,
                    "color": Color(56, 34, 24),
                }

            sample_frame_fn = getattr(sampler, "sample_frame", None)
            if callable(sample_frame_fn):
                result = sample_frame_fn(
                    device_index=device_index,
                    palette_mode=palette_mode,
                    sensitivity=sensitivity,
                )
                return dict(result)

            # Compatibilidad con dobles de prueba que solo implementan `sample_audio_metrics`
            energy, color = sampler.sample_audio_metrics()

        clamped_energy = max(0.0, min(1.0, finite_metric(energy) * float(sensitivity)))
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
        run_id: int,
    ) -> None:
        """Bucle asincrono que analiza el espectro acustico y transmite fotogramas UDP."""
        consecutive_errors = 0
        try:
            while self._active and self._generation == run_id:
                sleep_delay = self._interval_seconds
                try:
                    sampler = self._sampler
                    device_index = self._device_index
                    palette_mode = self._palette_mode
                    sensitivity = self._sensitivity
                    metrics = await asyncio.to_thread(
                        self._sample_once,
                        sampler,
                        device_index,
                        palette_mode,
                        sensitivity,
                        run_id,
                    )
                    if self._generation != run_id or not self._active:
                        break
                    sampled_color: Color = metrics["color"]
                    suggested_brightness = sanitize_brightness(
                        metrics.get("brightness", self._fixed_brightness),
                        self._fixed_brightness,
                    )
                    effective_brightness = (
                        suggested_brightness if self._audio_brightness else self._fixed_brightness
                    )

                    self._rms = finite_metric(metrics.get("rms", 0.0))
                    self._bass = finite_metric(metrics.get("bass", 0.0))
                    self._mid = finite_metric(metrics.get("mid", 0.0))
                    self._treble = finite_metric(metrics.get("treble", 0.0))
                    self._last_color = sampled_color
                    self._last_brightness = effective_brightness

                    if self._target_ips:
                        sent = await on_frame(
                            sampled_color,
                            effective_brightness,
                            list(self._target_ips),
                        )
                        if sent and self._generation == run_id:
                            self._frames_sent += 1
                    consecutive_errors = 0
                except asyncio.CancelledError:
                    raise
                # FRONTERA: cada iteracion lee el endpoint de audio nativo (PortAudio/WASAPI
                # via ctypes y NumPy) en un hilo y envia por UDP. Un fotograma fallido no
                # puede terminar el flujo que el usuario inicio: se registra con traza y se
                # reintenta con backoff exponencial acotado.
                except Exception:
                    consecutive_errors += 1
                    if consecutive_errors == 1:
                        _LOGGER.exception("Music sync frame sampling iteration failed.")
                    else:
                        _LOGGER.warning(
                            "Music sync frame sampling failed (%d consecutive errors).",
                            consecutive_errors,
                        )
                    sleep_delay = min(
                        self._max_error_backoff,
                        self._interval_seconds * (2 ** min(consecutive_errors, 8)),
                    )

                if self._generation != run_id or not self._active:
                    break
                await asyncio.sleep(sleep_delay)
        except asyncio.CancelledError:
            raise
        finally:
            if self._generation == run_id:
                self._active = False
                self._task = None
