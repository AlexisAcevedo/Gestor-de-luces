"""Casos de uso principales para la gestion y el control de focos inteligentes.

LightControlService orquesta las entidades del dominio y delega la comunicacion
de red y la persistencia en los puertos salientes (LightController, BulbRepository).
Esta disenado desde el primer dia para controlar tanto un foco individual como
multiples focos en simultaneo de forma concurrente con asyncio.gather.
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

from gestor_luces.application.rate_limiter import StreamRateLimiter
from gestor_luces.application.sleep_timer import AwaitableStatusDict, SleepTimerManager
from gestor_luces.domain.models import Bulb, LightState
from gestor_luces.domain.scenes import CustomScene, get_builtin_scene
from gestor_luces.domain.value_objects import (
    Brightness,
    Color,
    ColorTemperature,
    LightMode,
    SceneSpeed,
)
from gestor_luces.ports.repositories import (
    BulbRepository,
    LightController,
    SceneRepository,
)


class LightControlService:
    """Servicio de aplicacion que coordina el inventario de focos, escenas y temporizadores."""

    def __init__(
        self,
        controller: LightController,
        bulb_repository: BulbRepository | None = None,
        scene_repository: SceneRepository | None = None,
        rate_limiter: StreamRateLimiter | None = None,
        sleep_timer: SleepTimerManager | None = None,
    ) -> None:
        self._controller = controller
        self._bulb_repo = bulb_repository
        self._scene_repo = scene_repository
        self._rate_limiter = rate_limiter or StreamRateLimiter()
        self._sleep_timer = sleep_timer or SleepTimerManager()
        self._bulbs: dict[str, Bulb] = {}
        self._selected_ips: list[str] = []
        self._custom_scenes: dict[str, CustomScene] = {}

        if self._bulb_repo is not None:
            for saved_bulb in self._bulb_repo.load_bulbs():
                self._bulbs[saved_bulb.ip] = saved_bulb
            self._selected_ips = list(self._bulbs.keys())

        if self._scene_repo is not None:
            for saved_scene in self._scene_repo.load_scenes():
                self._custom_scenes[saved_scene.id] = saved_scene

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

    def list_custom_scenes(self) -> list[CustomScene]:
        """Devuelve la coleccion de escenas personalizadas creadas por el usuario."""
        return list(self._custom_scenes.values())

    def get_custom_scene(self, scene_id: str) -> CustomScene | None:
        """Busca una escena personalizada por su identificador unico."""
        return self._custom_scenes.get(scene_id)

    def save_custom_scene_from_current(
        self,
        name: str,
        source_ip: str | None = None,
        scene_id: str | None = None,
    ) -> CustomScene:
        """Captura la fotografia luminica actual del foco de referencia y la guarda como preset.

        Si no se especifica `source_ip`, toma el primer foco seleccionado o el primero
        registrado. Si aun no hay focos en el inventario, emplea el estado por defecto
        (4200K al 100%) para permitir crear presets antes de conectar fisicamente un foco.
        """
        cleaned_name = name.strip()
        if not cleaned_name:
            raise ValueError("Custom scene name cannot be empty.")

        reference_state = self._resolve_reference_state(source_ip)
        return self.create_or_update_custom_scene(
            name=cleaned_name,
            mode=reference_state.mode,
            brightness=reference_state.brightness,
            color=reference_state.color,
            temperature=reference_state.temperature,
            built_in_scene_id=reference_state.scene_id,
            speed=reference_state.speed,
            scene_id=scene_id,
        )

    def create_or_update_custom_scene(
        self,
        name: str,
        mode: LightMode | str,
        brightness: int = 100,
        color: Color | None = None,
        temperature: int | None = None,
        built_in_scene_id: int | None = None,
        speed: int = 100,
        scene_id: str | None = None,
    ) -> CustomScene:
        """Crea un nuevo preset personalizado o actualiza uno existente validando el dominio."""
        cleaned_name = name.strip()
        if not cleaned_name:
            raise ValueError("Custom scene name cannot be empty.")

        resolved_mode = mode if isinstance(mode, LightMode) else LightMode(str(mode))
        resolved_id = (
            scene_id.strip()
            if (scene_id is not None and scene_id.strip())
            else uuid4().hex[:8]
        )

        if resolved_mode == LightMode.RGB:
            resolved_color = color if color is not None else Color(255, 140, 66)
            resolved_temp = None
            resolved_builtin = None
        elif resolved_mode == LightMode.SCENE:
            resolved_color = None
            resolved_temp = None
            resolved_builtin = built_in_scene_id if built_in_scene_id is not None else 1
        else:
            resolved_color = None
            resolved_temp = temperature if temperature is not None else 4200
            resolved_builtin = None

        scene = CustomScene(
            id=resolved_id,
            name=cleaned_name,
            mode=resolved_mode,
            brightness=int(brightness),
            color=resolved_color,
            temperature=resolved_temp,
            built_in_scene_id=resolved_builtin,
            speed=int(speed),
        )
        self._custom_scenes[scene.id] = scene
        self._persist_scenes()
        return scene

    def rename_custom_scene(self, scene_id: str, new_name: str) -> CustomScene:
        """Actualiza el nombre de una escena personalizada existente y la persiste."""
        existing = self._custom_scenes.get(scene_id)
        if existing is None:
            raise KeyError(f"Custom scene '{scene_id}' does not exist.")
        cleaned = new_name.strip()
        if not cleaned:
            raise ValueError("Custom scene name cannot be empty.")
        existing.name = cleaned
        self._persist_scenes()
        return existing

    def delete_custom_scene(self, scene_id: str) -> None:
        """Elimina una escena personalizada del inventario y actualiza el archivo JSON."""
        if scene_id not in self._custom_scenes:
            raise KeyError(f"Custom scene '{scene_id}' does not exist.")
        del self._custom_scenes[scene_id]
        self._persist_scenes()

    async def apply_custom_scene(
        self,
        scene_id: str,
        ips: list[str] | None = None,
    ) -> list[Bulb]:
        """Aplica los parametros guardados en una escena personalizada a los focos objetivo."""
        scene = self._custom_scenes.get(scene_id)
        if scene is None:
            raise KeyError(f"Custom scene '{scene_id}' does not exist.")

        if scene.mode == LightMode.RGB and scene.color is not None:
            return await self.set_color(
                r=scene.color.r,
                g=scene.color.g,
                b=scene.color.b,
                brightness=scene.brightness,
                ips=ips,
            )
        if scene.mode == LightMode.SCENE and scene.built_in_scene_id is not None:
            return await self.set_builtin_scene(
                scene_id=scene.built_in_scene_id,
                speed=scene.speed,
                brightness=scene.brightness,
                ips=ips,
            )
        kelvin = scene.temperature if scene.temperature is not None else 4200
        return await self.set_temperature(
            kelvin=kelvin,
            brightness=scene.brightness,
            ips=ips,
        )

    def start_sleep_timer(
        self,
        minutes: float,
        ips: list[str] | None = None,
    ) -> AwaitableStatusDict:
        """Programa el apagado automatico con atenuacion progresiva tras `minutes` minutos."""
        parsed_minutes = float(minutes)
        if parsed_minutes <= 0 or parsed_minutes > 240:
            raise ValueError("Sleep timer minutes must be greater than 0 and at most 240.")

        target_ips = self.get_target_ips(ips)
        ref_state = self._resolve_reference_state(target_ips[0] if target_ips else None)

        async def _on_step_brightness(step_b: int, step_ips: list[str]) -> None:
            await self.set_brightness(brightness=step_b, ips=step_ips)

        async def _on_expire_off(off_ips: list[str]) -> None:
            await self.set_power(is_on=False, ips=off_ips)

        return self._sleep_timer.start(
            duration_seconds=parsed_minutes * 60.0,
            target_ips=target_ips,
            initial_brightness=ref_state.brightness,
            on_step_brightness=_on_step_brightness,
            on_expire_power_off=_on_expire_off,
        )

    def cancel_sleep_timer(self) -> AwaitableStatusDict:
        """Cancela el temporizador de apagado activo."""
        return self._sleep_timer.cancel()

    def get_sleep_timer_status(self) -> dict[str, Any]:
        """Consulta el estado actual del temporizador de apagado."""
        return dict(self._sleep_timer.get_status())

    def _resolve_reference_state(self, source_ip: str | None = None) -> LightState:
        """Determina el estado luminico de referencia a partir de una IP o la seleccion actual."""
        if source_ip and source_ip in self._bulbs:
            return self._bulbs[source_ip].state
        for ip in self.get_target_ips():
            if ip in self._bulbs:
                return self._bulbs[ip].state
        if self._bulbs:
            return next(iter(self._bulbs.values())).state
        return LightState()

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

    def _persist_scenes(self) -> None:
        """Delega el guardado de escenas personalizadas si hay un repositorio configurado."""
        if self._scene_repo is not None:
            self._scene_repo.save_scenes(self.list_custom_scenes())
