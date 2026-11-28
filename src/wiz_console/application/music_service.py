"""Sincronizacion musical: audio WASAPI Loopback hacia los focos objetivo."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from wiz_console.application.music_stream import VALID_MUSIC_PALETTES
from wiz_console.application.service_context import ServiceContext
from wiz_console.application.sleep_timer import (
    AwaitableStatusDict,
    require_finite_float,
    require_int_value,
)
from wiz_console.domain.value_objects import Brightness, Color


class MusicService:
    """Configura, inicia y detiene el flujo continuo de sincronizacion acustica."""

    def __init__(
        self,
        context: ServiceContext,
        stop_ambilight: Callable[[], AwaitableStatusDict],
    ) -> None:
        self._ctx = context
        self._stop_ambilight = stop_ambilight

    def list_audio_devices(self) -> list[dict[str, Any]]:
        """Devuelve la lista de dispositivos WASAPI Loopback disponibles para el modo Musica."""
        sampler = self._ctx.ensure_audio_sampler()
        list_fn = getattr(sampler, "list_audio_devices", None)
        if callable(list_fn):
            return list(list_fn())
        return [
            {
                "index": -1,
                "name": "System Audio Loopback",
                "label": "Default System Output (WASAPI Loopback)",
                "sample_rate": 48000,
                "channels": 2,
                "is_default": True,
            }
        ]

    def start_music_sync(
        self,
        palette_mode: str = "spectrum",
        sensitivity: float = 1.0,
        smoothing_alpha: float = 0.50,
        audio_brightness: bool = True,
        brightness: int = 85,
        device_index: int | None = None,
        ips: list[str] | None = None,
    ) -> AwaitableStatusDict:
        """Inicia la sincronizacion acustica WASAPI Loopback hacia los focos objetivo."""
        normalized_palette = str(palette_mode).strip().lower()
        if normalized_palette not in VALID_MUSIC_PALETTES:
            raise ValueError(
                f"Invalid music palette '{palette_mode}'. Expected one of {VALID_MUSIC_PALETTES}."
            )
        parsed_sensitivity = require_finite_float(sensitivity, "sensitivity")
        if not (0.3 <= parsed_sensitivity <= 3.0):
            raise ValueError("Music sensitivity must be between 0.3 and 3.0.")
        raw_alpha = require_finite_float(smoothing_alpha, "smoothing_alpha")
        parsed_alpha = max(0.05, min(1.0, raw_alpha))
        validated_brightness = Brightness(require_int_value(brightness, "brightness")).percent
        parsed_device = (
            require_int_value(device_index, "device_index") if device_index is not None else None
        )
        target_ips = self._ctx.get_target_ips(ips)
        asyncio.get_running_loop()

        # Exclusion mutua: iniciar el modo Musica detiene automaticamente el flujo Ambilight.
        self._stop_ambilight()
        sampler = self._ctx.ensure_audio_sampler()
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

        self._ctx.music_prefs = {
            "palette_mode": normalized_palette,
            "sensitivity": parsed_sensitivity,
            "smoothing_alpha": parsed_alpha,
            "audio_brightness": bool(audio_brightness),
            "brightness": validated_brightness,
            "device_index": parsed_device,
        }
        self._ctx.persist_settings()

        return self._ctx.music_sync.start(
            sampler=sampler,
            target_ips=target_ips,
            on_frame=_on_frame,
            palette_mode=normalized_palette,
            sensitivity=parsed_sensitivity,
            smoothing_alpha=parsed_alpha,
            audio_brightness=bool(audio_brightness),
            brightness=validated_brightness,
            device_index=parsed_device,
        )

    def stop_music_sync(self, close_sampler: bool = False) -> AwaitableStatusDict:
        """Detiene el flujo continuo de sincronizacion musical y opcionalmente cierra el stream
        WASAPI."""
        status = self._ctx.music_sync.stop()
        if close_sampler:
            self._ctx.close_audio_sampler()
        return status

    def get_music_sync_status(self) -> dict[str, Any]:
        """Devuelve el estado actual y telemetria espectral de la sincronizacion musical."""
        return dict(self._ctx.music_sync.get_status())
