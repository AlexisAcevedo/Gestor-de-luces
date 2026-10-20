"""Orquestador asincrono del flujo continuo de color de pantalla (modo Ambilight).

Mantiene una tarea en segundo plano sobre el bucle de eventos `asyncio` que muestrea
el color de la pantalla en un hilo trabajador (`asyncio.to_thread`) a ~10 Hz y delega
la emision en `LightControlService.stream_color_frame`. De esta manera, el suavizado
exponencial (EMA), el limite de tasa por foco y la deduplicacion por banda muerta se
aplican de forma consistente sin bloquear la interfaz grafica ni saturar el bus UDP.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import inspect
import logging
from typing import Any

from gestor_luces.application.sleep_timer import AwaitableStatusDict
from gestor_luces.domain.value_objects import Brightness, Color
from gestor_luces.ports.repositories import ScreenSampler

_LOGGER = logging.getLogger(__name__)

VALID_AMBILIGHT_MODES = ("vibrant", "average")


class AmbilightStreamManager:
    """Gestiona el ciclo de vida de la tarea asincrona de muestreo y emision Ambilight."""

    def __init__(
        self,
        sampler: ScreenSampler | None = None,
        interval_seconds: float = 0.10,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("Ambilight sampling interval must be greater than zero.")
        self._sampler: ScreenSampler | None = sampler
        self._interval_seconds: float = float(interval_seconds)
        self._task: asyncio.Task[None] | None = None
        self._active: bool = False
        self._monitor_index: int = 1
        self._color_mode: str = "vibrant"
        self._auto_brightness: bool = True
        self._fixed_brightness: int = 85
        self._smoothing_alpha: float = 0.38
        self._last_color: Color | None = None
        self._last_brightness: int = 85
        self._target_ips: list[str] = []
        self._frames_sent: int = 0

    def set_sampler(self, sampler: ScreenSampler) -> None:
        """Asigna o reemplaza el adaptador de muestreo de pantalla."""
        self._sampler = sampler

    def start(
        self,
        *,
        sampler: ScreenSampler,
        target_ips: list[str],
        on_frame: Callable[[Color, int, list[str]], Awaitable[bool]],
        monitor_index: int = 1,
        color_mode: str = "vibrant",
        auto_brightness: bool = True,
        brightness: int = 85,
        smoothing_alpha: float = 0.38,
    ) -> AwaitableStatusDict:
        """Inicia o reinicia el bucle continuo de muestreo de pantalla hacia los focos objetivo."""
        normalized_mode = str(color_mode).strip().lower()
        if normalized_mode not in VALID_AMBILIGHT_MODES:
            raise ValueError(
                f"Invalid Ambilight color mode '{color_mode}'. Expected one of {VALID_AMBILIGHT_MODES}."
            )
        parsed_alpha = float(smoothing_alpha)
        if not (0.05 <= parsed_alpha <= 1.0):
            raise ValueError("Smoothing alpha must be between 0.05 and 1.0.")

        validated_brightness = Brightness(int(brightness)).percent

        self.stop()

        self._sampler = sampler
        self._monitor_index = int(monitor_index)
        self._color_mode = normalized_mode
        self._auto_brightness = bool(auto_brightness)
        self._fixed_brightness = validated_brightness
        self._last_brightness = validated_brightness
        self._smoothing_alpha = parsed_alpha
        self._target_ips = list(target_ips)
        self._frames_sent = 0
        self._active = True

        loop = asyncio.get_running_loop()
        self._task = loop.create_task(
            self._run_loop(on_frame=on_frame),
            name="GestorLucesAmbilightStream",
        )
        return self.get_status()

    def stop(self) -> AwaitableStatusDict:
        """Detiene inmediatamente la captura continua sin apagar los focos."""
        if self._task is not None and not self._task.done():
            self._task.cancel()
        self._task = None
        self._active = False
        self._target_ips = []
        return self.get_status()

    def update_targets(self, target_ips: list[str]) -> None:
        """Actualiza en caliente los focos destino cuando el usuario cambia la seleccion."""
        if self._active:
            self._target_ips = list(target_ips)

    def update_fixed_brightness(self, brightness: int) -> None:
        """Actualiza el techo de brillo manual si el usuario mueve el deslizador maestro."""
        validated = Brightness(int(brightness)).percent
        self._fixed_brightness = validated
        if not self._auto_brightness:
            self._last_brightness = validated

    def get_status(self) -> AwaitableStatusDict:
        """Devuelve una fotografia serializable del estado actual del flujo Ambilight."""
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
                "monitor_index": self._monitor_index,
                "color_mode": self._color_mode,
                "auto_brightness": self._auto_brightness,
                "brightness": (
                    self._last_brightness if self._auto_brightness else self._fixed_brightness
                ),
                "fixed_brightness": self._fixed_brightness,
                "smoothing_alpha": round(self._smoothing_alpha, 2),
                "last_color": (
                    self._last_color.to_dict() if self._last_color is not None else None
                ),
                "target_ips": list(self._target_ips) if is_running else [],
                "frames_sent": self._frames_sent,
            }
        )

    def _sample_once(self, monitor_index: int, color_mode: str) -> tuple[Color, int]:
        """Ejecuta una captura sincrona de pantalla (invocada mediante `asyncio.to_thread`)."""
        if self._sampler is None:
            return Color(0, 0, 0), self._fixed_brightness

        sample_frame_fn = getattr(self._sampler, "sample_frame", None)
        if callable(sample_frame_fn):
            color, suggested_brightness = sample_frame_fn(
                monitor_index=monitor_index,
                mode=color_mode,
            )
            return color, int(suggested_brightness)

        # Compatibilidad con dobles de prueba que solo implementan `sample_average_color`
        sig = inspect.signature(self._sampler.sample_average_color)
        if "mode" in sig.parameters or len(sig.parameters) >= 2:
            color = self._sampler.sample_average_color(monitor_index, color_mode)
        else:
            color = self._sampler.sample_average_color(monitor_index)

        lum = (0.2126 * color.r + 0.7152 * color.g + 0.0722 * color.b) / 255.0
        derived_brightness = max(10, min(100, round(10.0 + lum * 90.0)))
        return color, derived_brightness

    async def _run_loop(
        self,
        on_frame: Callable[[Color, int, list[str]], Awaitable[bool]],
    ) -> None:
        """Bucle asincrono que muestrea el monitor y transmite fotogramas suavizados."""
        try:
            while self._active:
                try:
                    sampled_color, suggested_brightness = await asyncio.to_thread(
                        self._sample_once,
                        self._monitor_index,
                        self._color_mode,
                    )
                    effective_brightness = (
                        suggested_brightness
                        if self._auto_brightness
                        else self._fixed_brightness
                    )
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
                    _LOGGER.exception("Ambilight frame sampling iteration failed.")

                await asyncio.sleep(self._interval_seconds)
        except asyncio.CancelledError:
            raise
        finally:
            self._active = False
