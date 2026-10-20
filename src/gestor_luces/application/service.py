"""Casos de uso principales para la gestion y el control de focos inteligentes.

LightControlService orquesta las entidades del dominio y delega la comunicacion
de red y la persistencia en los puertos salientes (LightController, BulbRepository).
Esta disenado desde el primer dia para controlar tanto un foco individual como
multiples focos en simultaneo de forma concurrente con asyncio.gather.
"""

from __future__ import annotations

import asyncio

from gestor_luces.application.rate_limiter import StreamRateLimiter
from gestor_luces.domain.models import Bulb, LightState
from gestor_luces.domain.scenes import get_builtin_scene
from gestor_luces.domain.value_objects import (
    Brightness,
    Color,
    ColorTemperature,
    LightMode,
    SceneSpeed,
)
from gestor_luces.ports.repositories import BulbRepository, LightController


class LightControlService:
    """Servicio de aplicacion que coordina el inventario de focos y el envio de comandos."""

    def __init__(
        self,
        controller: LightController,
        bulb_repository: BulbRepository | None = None,
        rate_limiter: StreamRateLimiter | None = None,
    ) -> None:
        self._controller = controller
        self._bulb_repo = bulb_repository
        self._rate_limiter = rate_limiter or StreamRateLimiter()
        self._bulbs: dict[str, Bulb] = {}
        self._selected_ips: list[str] = []

        if self._bulb_repo is not None:
            for saved_bulb in self._bulb_repo.load_bulbs():
                self._bulbs[saved_bulb.ip] = saved_bulb
            self._selected_ips = list(self._bulbs.keys())

    def list_bulbs(self) -> list[Bulb]:
        """Devuelve la lista de todos los focos registrados actualmente."""
        return list(self._bulbs.values())

    def get_bulb(self, ip: str) -> Bulb | None:
        """Obtiene un foco registrado por su direccion IP."""
        return self._bulbs.get(ip)

    def select_targets(self, ips: list[str]) -> list[str]:
        """Define que subconjunto de focos recibira los comandos cuando no se indiquen IPs explicitas."""
        valid_ips = [ip for ip in ips if ip in self._bulbs]
        self._selected_ips = valid_ips
        return list(self._selected_ips)

    def get_target_ips(self, explicit_ips: list[str] | None = None) -> list[str]:
        """Resuelve la lista de IPs destino para una operacion de control.

        Si el llamador pasa explicit_ips, se utilizan esas direcciones. De lo contrario,
        se usan los focos seleccionados actualmente (o todos los registrados si la
        seleccion esta vacia).
        """
        if explicit_ips is not None:
            return list(explicit_ips)
        if self._selected_ips:
            return list(self._selected_ips)
        return list(self._bulbs.keys())

    async def discover_bulbs(self, wait_time: float = 2.5) -> list[Bulb]:
        """Ejecuta el descubrimiento en la red local y sincroniza el estado real de cada foco.

        Si un foco ya existia en el repositorio local con un nombre personalizado,
        se preserva dicho nombre para no perder la configuracion del usuario.
        """
        discovered = await self._controller.discover(wait_time=wait_time)
        for bulb in discovered:
            existing = self._bulbs.get(bulb.ip)
            if existing is not None and not existing.name.startswith("WiZ Bulb ("):
                bulb.name = existing.name
            self._bulbs[bulb.ip] = bulb

        await self.refresh_states([b.ip for b in discovered])

        if not self._selected_ips and self._bulbs:
            self._selected_ips = list(self._bulbs.keys())

        self._persist_bulbs()
        return self.list_bulbs()

    async def add_manual_bulb(self, ip: str, name: str | None = None) -> Bulb:
        """Registra un foco manualmente por su IP y verifica su estado en la red."""
        cleaned_ip = ip.strip()
        if not cleaned_ip:
            raise ValueError("Bulb IP address cannot be empty.")

        probed = await self._controller.probe_bulb(cleaned_ip)
        if probed is not None:
            if name and name.strip():
                probed.name = name.strip()
            self._bulbs[cleaned_ip] = probed
        else:
            fallback_name = name.strip() if name and name.strip() else f"WiZ Bulb ({cleaned_ip})"
            self._bulbs[cleaned_ip] = Bulb(ip=cleaned_ip, name=fallback_name, is_online=False)

        if cleaned_ip not in self._selected_ips:
            self._selected_ips.append(cleaned_ip)

        self._persist_bulbs()
        return self._bulbs[cleaned_ip]

    def rename_bulb(self, ip: str, new_name: str) -> Bulb:
        """Cambia el nombre amigable de un foco registrado y guarda el cambio."""
        bulb = self._bulbs.get(ip)
        if bulb is None:
            raise KeyError(f"Bulb with IP '{ip}' is not registered.")
        cleaned = new_name.strip()
        if not cleaned:
            raise ValueError("Bulb name cannot be empty.")
        bulb.name = cleaned
        self._persist_bulbs()
        return bulb

    async def refresh_states(self, ips: list[str] | None = None) -> list[Bulb]:
        """Consulta en paralelo el estado real (getPilot) de los focos indicados.

        Esto garantiza que si alguien apago o cambio el color del foco desde la
        llave de pared o la app movil de WiZ, nuestra aplicacion refleje la verdad.
        """
        target_ips = self.get_target_ips(ips)
        if not target_ips:
            return []

        async def _refresh_one(ip: str) -> Bulb:
            bulb = self._ensure_bulb_entry(ip)
            live_state = await self._controller.get_state(ip)
            if live_state is not None:
                bulb.state = live_state
                bulb.is_online = True
            else:
                bulb.is_online = False
            return bulb

        updated = await asyncio.gather(*(_refresh_one(ip) for ip in target_ips))
        return list(updated)

    async def set_power(
        self,
        is_on: bool,
        brightness: int | None = None,
        ips: list[str] | None = None,
    ) -> list[Bulb]:
        """Enciende o apaga uno o varios focos en paralelo."""
        validated_brightness = Brightness(brightness).percent if brightness is not None else None
        target_ips = self.get_target_ips(ips)

        async def _apply(ip: str) -> Bulb:
            bulb = self._ensure_bulb_entry(ip)
            ok = await self._controller.set_power(ip, is_on=is_on, brightness=validated_brightness)
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
        target_ips = self.get_target_ips(ips)

        async def _apply(ip: str) -> Bulb:
            bulb = self._ensure_bulb_entry(ip)
            ok = await self._controller.set_brightness(ip, brightness=validated)
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
        target_ips = self.get_target_ips(ips)

        async def _apply(ip: str) -> Bulb:
            bulb = self._ensure_bulb_entry(ip)
            ok = await self._controller.set_color(
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
        target_ips = self.get_target_ips(ips)

        async def _apply(ip: str) -> Bulb:
            bulb = self._ensure_bulb_entry(ip)
            ok = await self._controller.set_temperature(
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
            SceneSpeed(speed).value
            if (speed is not None and scene.supports_speed)
            else None
        )
        validated_brightness = Brightness(brightness).percent if brightness is not None else None
        target_ips = self.get_target_ips(ips)

        async def _apply(ip: str) -> Bulb:
            bulb = self._ensure_bulb_entry(ip)
            ok = await self._controller.set_scene(
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

    async def stream_color_frame(
        self,
        color: Color,
        brightness: int = 100,
        ips: list[str] | None = None,
    ) -> bool:
        """Envia un fotograma continuo (Ambilight/Musica) filtrado por el RateLimiter.

        Devuelve True si al menos un foco recibio un paquete nuevo, o False si
        todos los envios fueron suprimidos por limite de frecuencia o deduplicacion.
        """
        target_ips = self.get_target_ips(ips)
        if not target_ips:
            return False

        tasks = []
        for ip in target_ips:
            prepared = self._rate_limiter.prepare_frame(ip, color, brightness)
            if prepared is not None:
                smoothed_color, smoothed_brightness = prepared
                bulb = self._ensure_bulb_entry(ip)
                bulb.state = LightState(
                    is_on=True,
                    brightness=smoothed_brightness,
                    mode=LightMode.RGB,
                    color=smoothed_color,
                    temperature=None,
                )
                tasks.append(
                    self._controller.stream_pilot(
                        ip,
                        color=smoothed_color,
                        brightness=smoothed_brightness,
                    )
                )

        if not tasks:
            return False

        await asyncio.gather(*tasks)
        return True

    def _ensure_bulb_entry(self, ip: str) -> Bulb:
        """Obtiene la instancia Bulb registrada o crea una temporal si la IP es nueva."""
        bulb = self._bulbs.get(ip)
        if bulb is None:
            bulb = Bulb(ip=ip)
            self._bulbs[ip] = bulb
        return bulb

    def _persist_bulbs(self) -> None:
        """Delega el guardado del inventario si hay un repositorio configurado."""
        if self._bulb_repo is not None:
            self._bulb_repo.save_bulbs(self.list_bulbs())
