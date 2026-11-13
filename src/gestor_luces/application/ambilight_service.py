"""Sincronizacion Ambilight: color de pantalla hacia los focos objetivo."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from gestor_luces.application.service_context import ServiceContext
from gestor_luces.application.sleep_timer import AwaitableStatusDict
from gestor_luces.domain.value_objects import Color


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
        # Exclusion mutua: iniciar Ambilight detiene automaticamente la sincronizacion musical.
        self._stop_music_sync()
        sampler = self._ctx.ensure_screen_sampler()
        parsed_alpha = max(0.05, min(1.0, float(smoothing_alpha)))
        self._ctx.rate_limiter.set_alpha(parsed_alpha)
        self._ctx.rate_limiter.reset()
        target_ips = self._ctx.get_target_ips(ips)

        async def _on_frame(
            frame_color: Color, frame_brightness: int, frame_ips: list[str]
        ) -> bool:
            return await self._ctx.stream_color_frame(
                color=frame_color,
                brightness=frame_brightness,
                ips=frame_ips,
            )

        return self._ctx.ambilight.start(
            sampler=sampler,
            target_ips=target_ips,
            on_frame=_on_frame,
            monitor_index=int(monitor_index),
            color_mode=str(color_mode),
            auto_brightness=bool(auto_brightness),
            brightness=int(brightness),
            smoothing_alpha=parsed_alpha,
            min_brightness=int(min_brightness),
        )

    def stop_ambilight(self) -> AwaitableStatusDict:
        """Detiene el flujo continuo de Ambilight."""
        return self._ctx.ambilight.stop()

    def get_ambilight_status(self) -> dict[str, Any]:
        """Devuelve el estado actual de la sincronizacion Ambilight."""
        return dict(self._ctx.ambilight.get_status())
