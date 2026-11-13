"""Catalogo de presets personalizados: CRUD, favoritos y aplicacion a los focos."""

from __future__ import annotations

from uuid import uuid4

from gestor_luces.application.bulb_control_service import BulbControlService
from gestor_luces.application.service_context import ServiceContext, validate_display_name
from gestor_luces.domain.models import Bulb
from gestor_luces.domain.scenes import CustomScene
from gestor_luces.domain.value_objects import Color, LightMode


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
    ) -> CustomScene:
        """Captura la fotografia luminica actual del foco de referencia y la guarda como preset.

        Si no se especifica `source_ip`, toma el primer foco seleccionado o el primero
        registrado. Si aun no hay focos en el inventario, emplea el estado por defecto
        (4200K al 100%) para permitir crear presets antes de conectar fisicamente un foco.
        """
        cleaned_name = validate_display_name(name, "Custom scene")

        reference_state = self._ctx.resolve_reference_state(source_ip)
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

    async def apply_custom_scene(
        self,
        scene_id: str,
        ips: list[str] | None = None,
    ) -> list[Bulb]:
        """Aplica los parametros guardados en una escena personalizada a los focos objetivo."""
        scene = self._ctx.custom_scenes.get(scene_id)
        if scene is None:
            raise KeyError(f"Custom scene '{scene_id}' does not exist.")

        if scene.mode == LightMode.RGB and scene.color is not None:
            return await self._bulb_control.set_color(
                r=scene.color.r,
                g=scene.color.g,
                b=scene.color.b,
                brightness=scene.brightness,
                ips=ips,
            )
        if scene.mode == LightMode.SCENE and scene.built_in_scene_id is not None:
            return await self._bulb_control.set_builtin_scene(
                scene_id=scene.built_in_scene_id,
                speed=scene.speed,
                brightness=scene.brightness,
                ips=ips,
            )
        kelvin = scene.temperature if scene.temperature is not None else 4200
        return await self._bulb_control.set_temperature(
            kelvin=kelvin,
            brightness=scene.brightness,
            ips=ips,
        )
