"""Control de encendido, brillo, color, temperatura y escenas nativas de WiZ."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from gestor_luces.application.service_context import ServiceContext
from gestor_luces.application.sleep_timer import AwaitableStatusDict
from gestor_luces.domain.models import Bulb
from gestor_luces.domain.scenes import get_builtin_scene
from gestor_luces.domain.value_objects import (
    Brightness,
    Color,
    ColorTemperature,
    LightMode,
    SceneSpeed,
)


class BulbControlService:
    """Aplica comandos de control a los focos objetivo del contexto."""

    def __init__(
        self,
        context: ServiceContext,
        stop_ambilight: Callable[[], AwaitableStatusDict],
        stop_music_sync: Callable[[], AwaitableStatusDict],
    ) -> None:
        self._ctx = context
        self._stop_ambilight = stop_ambilight
        self._stop_music_sync = stop_music_sync

    async def set_power(
        self,
        is_on: bool,
        brightness: int | None = None,
        ips: list[str] | None = None,
    ) -> list[Bulb]:
        """Enciende o apaga uno o varios focos en paralelo."""
        if not is_on:
            # Si el usuario apaga manualmente o expira el Sleep Timer, detenemos Ambilight
            # y la sincronizacion musical para que un fotograma rezagado no vuelva a encender el
            # foco.
            self._stop_ambilight()
            self._stop_music_sync()
        validated_brightness = Brightness(brightness).percent if brightness is not None else None
        target_ips = self._ctx.get_target_ips(ips)

        async def _apply(ip: str) -> Bulb:
            bulb = self._ctx.ensure_bulb_entry(ip)
            ok = await self._ctx.controller.set_power(
                ip, is_on=is_on, brightness=validated_brightness
            )
            bulb.is_online = ok
            if ok:
                bulb.state.is_on = is_on
                if validated_brightness is not None:
                    bulb.state.brightness = validated_brightness
            return bulb

        results = await asyncio.gather(*(_apply(ip) for ip in target_ips))
        return list(results)

    async def set_brightness(
        self,
        brightness: int,
        ips: list[str] | None = None,
    ) -> list[Bulb]:
        """Ajusta el brillo (10-100%) en todos los focos objetivo."""
        validated = Brightness(brightness).percent
        self._ctx.ambilight.update_fixed_brightness(validated)
        self._ctx.music_sync.update_fixed_brightness(validated)
        target_ips = self._ctx.get_target_ips(ips)

        async def _apply(ip: str) -> Bulb:
            bulb = self._ctx.ensure_bulb_entry(ip)
            ok = await self._ctx.controller.set_brightness(ip, brightness=validated)
            bulb.is_online = ok
            if ok:
                bulb.state.is_on = True
                bulb.state.brightness = validated
            return bulb

        results = await asyncio.gather(*(_apply(ip) for ip in target_ips))
        return list(results)

    async def set_color(
        self,
        r: int,
        g: int,
        b: int,
        brightness: int | None = None,
        ips: list[str] | None = None,
    ) -> list[Bulb]:
        """Aplica un color RGB validado a uno o multiples focos."""
        color = Color(r=r, g=g, b=b)
        validated_brightness = Brightness(brightness).percent if brightness is not None else None
        # Cualquier cambio manual de color toma precedencia y detiene los flujos continuos.
        self._stop_ambilight()
        self._stop_music_sync()
        target_ips = self._ctx.get_target_ips(ips)

        async def _apply(ip: str) -> Bulb:
            bulb = self._ctx.ensure_bulb_entry(ip)
            ok = await self._ctx.controller.set_color(
                ip,
                color=color,
                brightness=validated_brightness,
            )
            bulb.is_online = ok
            if ok:
                bulb.state.is_on = True
                bulb.state.mode = LightMode.RGB
                bulb.state.color = color
                bulb.state.temperature = None
                bulb.state.scene_id = None
                bulb.state.scene_name = None
                if validated_brightness is not None:
                    bulb.state.brightness = validated_brightness
            return bulb

        results = await asyncio.gather(*(_apply(ip) for ip in target_ips))
        return list(results)

    async def set_temperature(
        self,
        kelvin: int,
        brightness: int | None = None,
        ips: list[str] | None = None,
    ) -> list[Bulb]:
        """Aplica una temperatura de color blanco (2200K-6500K) a los focos objetivo."""
        validated_temp = ColorTemperature(kelvin).kelvin
        validated_brightness = Brightness(brightness).percent if brightness is not None else None
        self._stop_ambilight()
        self._stop_music_sync()
        target_ips = self._ctx.get_target_ips(ips)

        async def _apply(ip: str) -> Bulb:
            bulb = self._ctx.ensure_bulb_entry(ip)
            ok = await self._ctx.controller.set_temperature(
                ip,
                kelvin=validated_temp,
                brightness=validated_brightness,
            )
            bulb.is_online = ok
            if ok:
                bulb.state.is_on = True
                bulb.state.mode = LightMode.TEMPERATURE
                bulb.state.temperature = validated_temp
                bulb.state.color = None
                bulb.state.scene_id = None
                bulb.state.scene_name = None
                if validated_brightness is not None:
                    bulb.state.brightness = validated_brightness
            return bulb

        results = await asyncio.gather(*(_apply(ip) for ip in target_ips))
        return list(results)

    async def set_builtin_scene(
        self,
        scene_id: int,
        speed: int | None = None,
        brightness: int | None = None,
        ips: list[str] | None = None,
    ) -> list[Bulb]:
        """Activa una de las 36 escenas nativas de WiZ en los focos objetivo."""
        scene = get_builtin_scene(scene_id)
        if scene is None:
            raise ValueError(f"Unknown WiZ built-in scene ID: {scene_id}.")

        validated_speed = (
            SceneSpeed(speed).value if (speed is not None and scene.supports_speed) else None
        )
        validated_brightness = Brightness(brightness).percent if brightness is not None else None
        self._stop_ambilight()
        self._stop_music_sync()
        target_ips = self._ctx.get_target_ips(ips)

        async def _apply(ip: str) -> Bulb:
            bulb = self._ctx.ensure_bulb_entry(ip)
            ok = await self._ctx.controller.set_scene(
                ip,
                scene_id=scene.scene_id,
                speed=validated_speed,
                brightness=validated_brightness,
            )
            bulb.is_online = ok
            if ok:
                bulb.state.is_on = True
                bulb.state.mode = LightMode.SCENE
                bulb.state.scene_id = scene.scene_id
                bulb.state.scene_name = scene.name
                bulb.state.color = None
                bulb.state.temperature = None
                if validated_speed is not None:
                    bulb.state.speed = validated_speed
                if validated_brightness is not None:
                    bulb.state.brightness = validated_brightness
            return bulb

        results = await asyncio.gather(*(_apply(ip) for ip in target_ips))
        return list(results)
