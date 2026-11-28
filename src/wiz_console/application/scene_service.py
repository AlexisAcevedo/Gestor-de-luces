"""Catalogo de presets personalizados: CRUD, favoritos y aplicacion a los focos."""

from __future__ import annotations

import asyncio
from uuid import uuid4

from wiz_console.application.bulb_control_service import BulbControlService
from wiz_console.application.service_context import ServiceContext, validate_display_name
from wiz_console.domain.models import Bulb, LightState
from wiz_console.domain.scenes import BulbSceneState, CustomScene
from wiz_console.domain.value_objects import Color, LightMode


def _bulb_scene_state_from_light(state: LightState) -> BulbSceneState:
    """Convert live fixture state into an immutable per-bulb scene snapshot."""
    return BulbSceneState(
        is_on=bool(state.is_on),
        mode=state.mode,
        brightness=int(state.brightness),
        color=state.color,
        temperature=state.temperature,
        built_in_scene_id=state.scene_id,
        speed=int(state.speed),
    )


class SceneService:
    """Gestiona las escenas personalizadas del contexto y su aplicacion a los focos."""

    def __init__(self, context: ServiceContext, bulb_control: BulbControlService) -> None:
        self._ctx = context
        self._bulb_control = bulb_control

    def list_custom_scenes(self) -> list[CustomScene]:
        """Devuelve la coleccion de escenas personalizadas creadas por el usuario."""
        return self._ctx.list_custom_scenes()

    def get_custom_scene(self, scene_id: str) -> CustomScene | None:
        """Busca una escena personalizada por su identificador unico."""
        return self._ctx.custom_scenes.get(scene_id)

    def save_custom_scene_from_current(
        self,
        name: str,
        source_ip: str | None = None,
        scene_id: str | None = None,
        capture_all_targets: bool = False,
    ) -> CustomScene:
        """Captura la fotografia luminica actual del foco de referencia y la guarda como preset.

        Si no se especifica `source_ip`, toma el primer foco seleccionado o el primero
        registrado. Cuando `capture_all_targets=True` y existen al menos 2 luminarias
        objetivo, guarda tambien el estado individual de cada foco en `bulb_states`.
        """
        cleaned_name = validate_display_name(name, "Custom scene")

        reference_state = self._ctx.resolve_reference_state(source_ip)
        bulb_states: dict[str, BulbSceneState] | None = None
        if capture_all_targets:
            target_ips = [ip for ip in self._ctx.get_target_ips() if ip in self._ctx.bulbs]
            if len(target_ips) >= 2:
                bulb_states = {
                    ip: _bulb_scene_state_from_light(self._ctx.bulbs[ip].state) for ip in target_ips
                }
        return self.create_or_update_custom_scene(
            name=cleaned_name,
            mode=reference_state.mode,
            brightness=reference_state.brightness,
            color=reference_state.color,
            temperature=reference_state.temperature,
            built_in_scene_id=reference_state.scene_id,
            speed=reference_state.speed,
            scene_id=scene_id,
            bulb_states=bulb_states,
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
        bulb_states: dict[str, BulbSceneState] | None = None,
    ) -> CustomScene:
        """Crea un nuevo preset personalizado o actualiza uno existente validando el dominio."""
        cleaned_name = validate_display_name(name, "Custom scene")

        resolved_mode = mode if isinstance(mode, LightMode) else LightMode(str(mode))
        resolved_id = (
            scene_id.strip() if (scene_id is not None and scene_id.strip()) else uuid4().hex[:8]
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
            # Sobrescribir la captura luminica de un preset no debe quitarlo de la bandeja.
            is_favorite=self._is_existing_favorite(resolved_id),
            bulb_states=bulb_states,
        )
        self._ctx.custom_scenes[scene.id] = scene
        self._ctx.persist_scenes()
        return scene

    def set_custom_scene_favorite(self, scene_id: str, is_favorite: bool) -> CustomScene:
        """Marca o desmarca un preset como favorito de la bandeja y persiste el cambio."""
        existing = self._ctx.custom_scenes.get(scene_id)
        if existing is None:
            raise KeyError(f"Custom scene '{scene_id}' does not exist.")
        existing.is_favorite = bool(is_favorite)
        self._ctx.persist_scenes()
        return existing

    def list_favorite_scenes(self) -> list[CustomScene]:
        """Devuelve los presets marcados como favoritos respetando el orden de creacion."""
        return [scene for scene in self._ctx.custom_scenes.values() if scene.is_favorite]

    def _is_existing_favorite(self, scene_id: str) -> bool:
        """Indica si el identificador corresponde a un preset ya marcado como favorito."""
        existing = self._ctx.custom_scenes.get(scene_id)
        return existing.is_favorite if existing is not None else False

    def rename_custom_scene(self, scene_id: str, new_name: str) -> CustomScene:
        """Actualiza el nombre de una escena personalizada existente y la persiste."""
        existing = self._ctx.custom_scenes.get(scene_id)
        if existing is None:
            raise KeyError(f"Custom scene '{scene_id}' does not exist.")
        existing.name = validate_display_name(new_name, "Custom scene")
        self._ctx.persist_scenes()
        return existing

    def delete_custom_scene(self, scene_id: str) -> None:
        """Elimina una escena personalizada del inventario y actualiza el archivo JSON."""
        if scene_id not in self._ctx.custom_scenes:
            raise KeyError(f"Custom scene '{scene_id}' does not exist.")
        del self._ctx.custom_scenes[scene_id]
        self._ctx.persist_scenes()

    async def _apply_state_to_ips(
        self,
        *,
        is_on: bool,
        mode: LightMode,
        brightness: int,
        color: Color | None,
        temperature: int | None,
        built_in_scene_id: int | None,
        speed: int,
        ips: list[str] | None,
    ) -> list[Bulb]:
        if not is_on:
            return await self._bulb_control.set_power(False, ips=ips)
        if mode == LightMode.RGB and color is not None:
            return await self._bulb_control.set_color(
                r=color.r,
                g=color.g,
                b=color.b,
                brightness=brightness,
                ips=ips,
            )
        if mode == LightMode.SCENE and built_in_scene_id is not None:
            return await self._bulb_control.set_builtin_scene(
                scene_id=built_in_scene_id,
                speed=speed,
                brightness=brightness,
                ips=ips,
            )
        kelvin = temperature if temperature is not None else 4200
        return await self._bulb_control.set_temperature(
            kelvin=kelvin,
            brightness=brightness,
            ips=ips,
        )

    async def apply_custom_scene(
        self,
        scene_id: str,
        ips: list[str] | None = None,
    ) -> list[Bulb]:
        """Aplica los parametros guardados en una escena personalizada a los focos objetivo."""
        scene = self._ctx.custom_scenes.get(scene_id)
        if scene is None:
            raise KeyError(f"Custom scene '{scene_id}' does not exist.")

        if scene.bulb_states:
            target_ips = self._ctx.get_target_ips(ips)
            if not target_ips:
                return []
            tasks = []
            for target_ip in target_ips:
                per_bulb = scene.bulb_states.get(target_ip)
                if per_bulb is not None:
                    tasks.append(
                        self._apply_state_to_ips(
                            is_on=per_bulb.is_on,
                            mode=per_bulb.mode,
                            brightness=per_bulb.brightness,
                            color=per_bulb.color,
                            temperature=per_bulb.temperature,
                            built_in_scene_id=per_bulb.built_in_scene_id,
                            speed=per_bulb.speed,
                            ips=[target_ip],
                        )
                    )
                else:
                    tasks.append(
                        self._apply_state_to_ips(
                            is_on=True,
                            mode=scene.mode,
                            brightness=scene.brightness,
                            color=scene.color,
                            temperature=scene.temperature,
                            built_in_scene_id=scene.built_in_scene_id,
                            speed=scene.speed,
                            ips=[target_ip],
                        )
                    )
            await asyncio.gather(*tasks)
            return self._ctx.list_bulbs()

        return await self._apply_state_to_ips(
            is_on=True,
            mode=scene.mode,
            brightness=scene.brightness,
            color=scene.color,
            temperature=scene.temperature,
            built_in_scene_id=scene.built_in_scene_id,
            speed=scene.speed,
            ips=ips,
        )
