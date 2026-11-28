"""Sincronizacion Ambilight: color de pantalla hacia los focos objetivo."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from wiz_console.application.ambilight_stream import VALID_AMBILIGHT_MODES
from wiz_console.application.service_context import ServiceContext
from wiz_console.application.sleep_timer import (
    AwaitableStatusDict,
    require_finite_float,
    require_int_value,
)
from wiz_console.domain.value_objects import Brightness, Color


class AmbilightService:
    """Configura, inicia y detiene el flujo continuo de color de pantalla."""

    def __init__(
        self,
        context: ServiceContext,
        stop_music_sync: Callable[[], AwaitableStatusDict],
    ) -> None:
        self._ctx = context
        self._stop_music_sync = stop_music_sync

    def list_monitors(self) -> list[dict[str, Any]]:
        """Devuelve la lista de monitores disponibles para el modo Ambilight."""
        sampler = self._ctx.ensure_screen_sampler()
        list_fn = getattr(sampler, "list_monitors", None)
        if callable(list_fn):
            return list(list_fn())
        return [{"index": 1, "label": "Display 1 (Primary)", "width": 1920, "height": 1080}]

    def start_ambilight(
        self,
        monitor_index: int = 1,
        color_mode: str = "vibrant",
        auto_brightness: bool = True,
        brightness: int = 85,
        smoothing_alpha: float = 0.38,
        ips: list[str] | None = None,
        min_brightness: int = 10,
    ) -> AwaitableStatusDict:
        """Inicia la sincronizacion continua del color de la pantalla con los focos objetivo."""
        parsed_monitor = require_int_value(monitor_index, "monitor_index")
        if parsed_monitor < 0:
            raise ValueError("Monitor index must be zero or positive.")
        normalized_mode = str(color_mode).strip().lower()
        if normalized_mode not in VALID_AMBILIGHT_MODES:
            raise ValueError(
                f"Invalid Ambilight color mode '{color_mode}'. "
                f"Expected one of {VALID_AMBILIGHT_MODES}."
            )
        validated_brightness = Brightness(require_int_value(brightness, "brightness")).percent
        parsed_min_brightness = require_int_value(min_brightness, "min_brightness")
        raw_alpha = require_finite_float(smoothing_alpha, "smoothing_alpha")
        parsed_alpha = max(0.05, min(1.0, raw_alpha))
        target_ips = self._ctx.get_target_ips(ips)
        asyncio.get_running_loop()

        # Exclusion mutua: iniciar Ambilight detiene automaticamente la sincronizacion musical.
        self._stop_music_sync()
        sampler = self._ctx.ensure_screen_sampler()
        self._ctx.rate_limiter.set_alpha(parsed_alpha)
        self._ctx.rate_limiter.reset()

        async def _on_frame(
            frame_color: Color, frame_brightness: int, frame_ips: list[str]
        ) -> bool:
            return await self._ctx.stream_color_frame(
                color=frame_color,
                brightness=frame_brightness,
                ips=frame_ips,
            )

        clamped_min = max(10, min(20, parsed_min_brightness))
        self._ctx.ambilight_prefs = {
            "monitor_index": parsed_monitor,
            "color_mode": normalized_mode,
            "auto_brightness": bool(auto_brightness),
            "brightness": validated_brightness,
            "smoothing_alpha": parsed_alpha,
            "min_brightness": clamped_min,
        }
        self._ctx.persist_settings()

        return self._ctx.ambilight.start(
            sampler=sampler,
            target_ips=target_ips,
            on_frame=_on_frame,
            monitor_index=parsed_monitor,
            color_mode=normalized_mode,
            auto_brightness=bool(auto_brightness),
            brightness=validated_brightness,
            smoothing_alpha=parsed_alpha,
            min_brightness=clamped_min,
        )

    def stop_ambilight(self) -> AwaitableStatusDict:
        """Detiene el flujo continuo de Ambilight."""
        return self._ctx.ambilight.stop()

    def get_ambilight_status(self) -> dict[str, Any]:
        """Devuelve el estado actual de la sincronizacion Ambilight."""
        return dict(self._ctx.ambilight.get_status())
