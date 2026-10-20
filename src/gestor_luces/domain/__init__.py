"""Capa de Dominio de Gestor de Luces.

Exporta las entidades, objetos de valor y catalogos puros sin dependencias externas.
"""

from gestor_luces.domain.models import Bulb, Group, LightState
from gestor_luces.domain.scenes import (
    BUILTIN_SCENES,
    BuiltInScene,
    CustomScene,
    get_builtin_scene,
    list_builtin_scenes,
)
from gestor_luces.domain.value_objects import (
    Brightness,
    Color,
    ColorTemperature,
    LightMode,
    SceneSpeed,
)

__all__ = [
    "BUILTIN_SCENES",
    "Brightness",
    "Bulb",
    "BuiltInScene",
    "Color",
    "ColorTemperature",
    "CustomScene",
    "Group",
    "LightMode",
    "LightState",
    "SceneSpeed",
    "get_builtin_scene",
    "list_builtin_scenes",
]
